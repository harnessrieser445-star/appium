"""
Action Service - 单动作直执行服务（面向AI助理的机器调用）

特点：
- 一次HTTP调用完成一个动作，不写入用例步骤列表（零污染）
- 每个动作返回 elapsed_ms 耗时埋点
- 错误结构化：error_code ∈ SESSION_LOST / ELEMENT_NOT_FOUND / TIMEOUT /
  BAD_REQUEST / ACTION_FAILED / NO_DEVICE，AI 可据此自动决策
- 支持动作：click / input / wait / screenshot / wait_until / back /
  long_press / double_click / swipe_xy / clear_input / press_hold(8方向)

目标寻址优先级：element(resource_id/xpath/content_desc/text) → bounds中心 → x,y坐标
"""

import base64
import os
import time
import threading
from typing import Any, Dict, Optional, Tuple

from selenium.common.exceptions import (
    InvalidSessionIdException, NoSuchElementException, WebDriverException,
)

from backend.utils.logger import get_logger
from backend.utils.paths import TEST_SCREENSHOTS_DIR

logger = get_logger(__name__)

# press_hold 8方向单位向量（斜向按 √2/2 归一化，保证各方向位移距离一致）
_DIAG = 0.7071
_PRESS_HOLD_VECTORS = {
    'up': (0, -1), 'down': (0, 1), 'left': (-1, 0), 'right': (1, 0),
    'up_left': (-_DIAG, -_DIAG), 'up_right': (_DIAG, -_DIAG),
    'down_left': (-_DIAG, _DIAG), 'down_right': (_DIAG, _DIAG),
}

# WebDriverException 消息中表明"会话已死"的关键字（小写匹配）→ SESSION_LOST
# 2026-09-11 真机实测补全：instrumentation 崩溃时 click 报
# "cannot be proxied to UiAutomator2 server" / InvalidContextError /
# "instrumentation process is not running"，此前漏判为 ACTION_FAILED
_SESSION_LOST_KEYWORDS = (
    'session', 'connection', 'socket',
    'cannot be proxied',
    'invalidcontexterror',
    'instrumentation process is not running',
    'uiautomator2 server',
)


class ActionTimeout(Exception):
    """wait_until 超时（映射为 TIMEOUT）"""


class ActionService:
    """单动作直执行服务"""

    SUPPORTED_ACTIONS = (
        'click', 'input', 'wait', 'screenshot', 'wait_until', 'back',
        'long_press', 'double_click', 'swipe_xy', 'clear_input', 'press_hold',
    )

    def __init__(self):
        self._device_service = None
        self._element_service = None
        self._lock = threading.RLock()

    def set_device_service(self, service):
        self._device_service = service

    def set_element_service(self, service):
        self._element_service = service

    # ==================== 入口 ====================

    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行单个动作。

        Args:
            payload: {action, element?, bounds?, x?, y?, params?}

        Returns:
            {success, action, elapsed_ms, message, error_code?, ...动作附加字段}
        """
        started = time.monotonic()
        action = (payload or {}).get('action', '')
        params = (payload or {}).get('params') or {}

        def _finish(ok: bool, message: str, error_code: str = '', **extra):
            result = {
                'success': ok,
                'action': action,
                'elapsed_ms': int((time.monotonic() - started) * 1000),
                'message': message,
            }
            if error_code:
                result['error_code'] = error_code
            result.update(extra)
            return result

        try:
            if action not in self.SUPPORTED_ACTIONS:
                return _finish(False, f'不支持的动作: {action}，支持: {", ".join(self.SUPPORTED_ACTIONS)}',
                               error_code='BAD_REQUEST')

            if not self._device_service or not self._device_service.is_real():
                return _finish(False, '未连接真实设备（动作执行需要真实设备会话）',
                               error_code='NO_DEVICE')

            driver = self._require_driver()

            if action == 'click':
                msg = self._do_click(driver, payload)
            elif action == 'input':
                msg = self._do_input(driver, payload, params)
            elif action == 'wait':
                msg = self._do_wait(params)
            elif action == 'screenshot':
                return self._do_screenshot(driver, params, _finish)
            elif action == 'wait_until':
                msg = self._do_wait_until(driver, payload, params)
            elif action == 'back':
                driver.back()
                msg = '返回键已按下'
            elif action == 'long_press':
                msg = self._do_long_press(driver, payload, params)
            elif action == 'double_click':
                msg = self._do_double_click(driver, payload)
            elif action == 'swipe_xy':
                msg = self._do_swipe_xy(driver, params)
            elif action == 'clear_input':
                msg = self._do_clear_input(driver, payload)
            elif action == 'press_hold':
                msg = self._do_press_hold(driver, payload, params)
            else:
                msg = ''  # pragma: no cover

            logger.info(f'[Action] {action} 成功: {msg}')
            return _finish(True, msg)

        except (InvalidSessionIdException, ConnectionError) as e:
            logger.error(f'[Action] {action} 会话丢失: {e}')
            return _finish(False, f'会话已断开: {str(e)[:200]}', error_code='SESSION_LOST')
        except NoSuchElementException as e:
            logger.warning(f'[Action] {action} 元素未找到: {e}')
            return _finish(False, f'元素未找到: {str(e)[:200]}', error_code='ELEMENT_NOT_FOUND')
        except ActionTimeout as e:
            return _finish(False, str(e), error_code='TIMEOUT',
                           page_digest=self._build_page_digest())
        except ValueError as e:
            return _finish(False, f'参数错误: {e}', error_code='BAD_REQUEST')
        except WebDriverException as e:
            msg = str(e).lower()
            if any(k in msg for k in _SESSION_LOST_KEYWORDS):
                return _finish(False, f'会话异常: {str(e)[:200]}', error_code='SESSION_LOST')
            logger.error(f'[Action] {action} 执行失败: {e}')
            return _finish(False, f'执行失败: {str(e)[:200]}', error_code='ACTION_FAILED')
        except Exception as e:
            logger.error(f'[Action] {action} 异常: {e}', exc_info=True)
            return _finish(False, f'执行异常: {str(e)[:200]}', error_code='ACTION_FAILED')

    # ==================== 设备/定位 ====================

    def _require_driver(self):
        """获取DriverProxy，未连接时抛ValueError（NO_DEVICE由API层前置判断）"""
        if not self._device_service:
            raise ValueError('设备服务未初始化')
        if not self._device_service.is_real():
            raise ValueError('NO_DEVICE:未连接真实设备')
        driver = self._device_service.get_driver_proxy()
        if not driver:
            raise ConnectionError('无法获取 Appium driver（会话可能已断开）')
        return driver

    @staticmethod
    def _locator_from(target: Dict[str, Any]) -> Tuple[str, str]:
        """从target字典构建(by, value)定位器"""
        from appium.webdriver.common.appiumby import AppiumBy
        from services.element_service import ElementService

        if target.get('resource_id'):
            return AppiumBy.ID, target['resource_id']
        if target.get('xpath'):
            return AppiumBy.XPATH, target['xpath']
        if target.get('content_desc'):
            return AppiumBy.ACCESSIBILITY_ID, target['content_desc']
        if target.get('text'):
            quoted = ElementService._xpath_attr_value(target['text'])
            return AppiumBy.XPATH, f'//*[@text={quoted}]'
        raise ValueError('element/target 缺少可用定位器（resource_id/xpath/content_desc/text）')

    def _find_element(self, driver, element: Dict[str, Any]):
        by, value = self._locator_from(element)
        return driver.find_element(by, value)

    def _resolve_point(self, driver, payload: Dict[str, Any]) -> Tuple[int, int]:
        """
        解析点击坐标：element.bounds中心 > element定位 > bounds中心 > x,y。
        """
        element = payload.get('element')
        bounds = payload.get('bounds')

        # bounds 中心（元素自带或显式传入）
        src = (element or {}).get('bounds') or bounds
        if src:
            if isinstance(src, str):
                import re
                nums = re.findall(r'-?\d+', src)
                src = [int(v) for v in nums] if len(nums) == 4 else None
            if src and len(src) == 4:
                x1, y1, x2, y2 = [int(v) for v in src]
                if x2 > x1 and y2 > y1:
                    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
                    try:
                        size = driver.get_window_size()
                        if 0 <= cx <= int(size.get('width', 0)) and 0 <= cy <= int(size.get('height', 0)):
                            return cx, cy
                    except Exception:
                        return cx, cy  # 尺寸获取失败不阻断

        # 元素定位取中心
        if element:
            el = self._find_element(driver, element)
            rect = el.rect
            return int(rect['x'] + rect['width'] / 2), int(rect['y'] + rect['height'] / 2)

        # 纯坐标
        x, y = payload.get('x'), payload.get('y')
        if x is not None and y is not None:
            return int(x), int(y)

        raise ValueError('缺少操作目标（element / bounds / x,y 至少提供一个）')

    @staticmethod
    def _tap(driver, x: int, y: int):
        if hasattr(driver, 'tap'):
            driver.tap([(x, y)])
            return
        from selenium.webdriver.common.action_chains import ActionChains
        raw = getattr(driver, 'raw_driver', driver)
        actions = ActionChains(raw)
        pa = actions.w3c_actions.pointer_action
        pa.move_to_location(x, y)
        pa.pointer_down()
        pa.pause(0.05)
        pa.pointer_up()
        actions.perform()

    # ==================== 动作实现 ====================

    def _do_click(self, driver, payload) -> str:
        x, y = self._resolve_point(driver, payload)
        self._tap(driver, x, y)
        return f'点击成功 ({x},{y})'

    def _do_input(self, driver, payload, params) -> str:
        element = payload.get('element')
        if not element:
            raise ValueError('input 需要 element 参数')
        text = params.get('text', params.get('value', ''))
        el = self._find_element(driver, element)
        if params.get('clear_first', True):
            el.clear()
        el.send_keys(text)
        return f'输入成功: "{text}"'

    def _do_wait(self, params) -> str:
        try:
            seconds = float(params.get('seconds', params.get('timeout', 3)))
        except (ValueError, TypeError):
            seconds = 3
        seconds = max(0.1, min(seconds, 300))
        time.sleep(seconds)
        return f'等待 {seconds}s 完成'

    def _do_screenshot(self, driver, params, _finish) -> Dict[str, Any]:
        png = self._device_service.get_screenshot_bytes()
        if not png:
            raise ConnectionError('截图获取失败（会话可能已断开）')
        extra = {}
        if params.get('save', False):
            os.makedirs(str(TEST_SCREENSHOTS_DIR), exist_ok=True)
            path = os.path.join(str(TEST_SCREENSHOTS_DIR), f'action_{int(time.time())}.png')
            with open(path, 'wb') as f:
                f.write(png)
            extra['path'] = path
        if params.get('return_base64', True):
            extra['screenshot'] = base64.b64encode(png).decode('ascii')
        return _finish(True, '截图成功', **extra)

    def _do_wait_until(self, driver, payload, params) -> str:
        target = payload.get('target') or payload.get('element')
        if not target:
            raise ValueError('wait_until 需要 target 参数')
        state = params.get('state', 'visible')
        if state not in ('visible', 'gone'):
            raise ValueError(f"state 仅支持 'visible'|'gone'，收到: {state}")
        try:
            timeout = float(params.get('timeout', 10))
        except (ValueError, TypeError):
            timeout = 10
        timeout = max(0.5, min(timeout, 120))

        by, value = self._locator_from(target)
        deadline = time.monotonic() + timeout
        poll = 0.5

        while True:
            try:
                driver.find_element(by, value)
                found = True
            except NoSuchElementException:
                found = False

            if (state == 'visible' and found) or (state == 'gone' and not found):
                return f'条件满足: {value} {state}'

            if time.monotonic() >= deadline:
                raise ActionTimeout(
                    f'等待超时({timeout}s): {value} 未{("出现" if state == "visible" else "消失")}')
            time.sleep(poll)

    def _do_long_press(self, driver, payload, params) -> str:
        x, y = self._resolve_point(driver, payload)
        try:
            duration = float(params.get('duration', params.get('hold', 1.0)))
        except (ValueError, TypeError):
            duration = 1.0
        duration = max(0.1, min(duration, 60))

        from selenium.webdriver.common.action_chains import ActionChains
        raw = getattr(driver, 'raw_driver', driver)
        actions = ActionChains(raw)
        pa = actions.w3c_actions.pointer_action
        pa.move_to_location(x, y)
        pa.pointer_down()
        pa.pause(duration)
        pa.pointer_up()
        actions.perform()
        return f'长按成功 ({x},{y}) {duration}s'

    def _do_double_click(self, driver, payload) -> str:
        x, y = self._resolve_point(driver, payload)
        self._tap(driver, x, y)
        time.sleep(0.1)
        self._tap(driver, x, y)
        return f'双击成功 ({x},{y})'

    def _do_swipe_xy(self, driver, params) -> str:
        try:
            sx = int(params['start_x']); sy = int(params['start_y'])
            ex = int(params['end_x']); ey = int(params['end_y'])
        except (KeyError, TypeError, ValueError):
            raise ValueError('swipe_xy 需要整数参数 start_x/start_y/end_x/end_y')
        try:
            duration_ms = int(params.get('duration_ms', params.get('duration', 500)))
        except (ValueError, TypeError):
            duration_ms = 500
        duration_ms = max(50, min(duration_ms, 10000))
        driver.swipe(sx, sy, ex, ey, duration_ms)
        return f'滑动成功 ({sx},{sy})->({ex},{ey}) {duration_ms}ms'

    def _do_clear_input(self, driver, payload) -> str:
        element = payload.get('element')
        if not element:
            raise ValueError('clear_input 需要 element 参数')
        el = self._find_element(driver, element)
        el.clear()
        return '输入框已清空'

    def _do_press_hold(self, driver, payload, params) -> str:
        direction = params.get('direction', 'up')
        if direction not in _PRESS_HOLD_VECTORS:
            raise ValueError(f'未知方向: {direction}，支持: {", ".join(_PRESS_HOLD_VECTORS)}')

        try:
            hold = float(params.get('hold', params.get('duration', 1)))
        except (ValueError, TypeError):
            hold = 1
        try:
            strength = float(params.get('strength', 0.8) or 0.8)
        except (ValueError, TypeError):
            strength = 0.8
        strength = max(0.1, min(1.0, strength))

        # 中心点与半径来源（与 click 寻址优先级对齐）：
        # params.center_x/center_y > element.bounds > 顶层 bounds > 顶层 x,y
        element = payload.get('element') or {}
        if 'center_x' in params and 'center_y' in params:
            cx, cy = int(params['center_x']), int(params['center_y'])
            radius = int(params.get('radius', 100))
        else:
            bounds = element.get('bounds') or payload.get('bounds')
            if bounds:
                if isinstance(bounds, str):
                    import re
                    nums = re.findall(r'-?\d+', bounds)
                    bounds = [int(v) for v in nums] if len(nums) == 4 else None
            if bounds and len(bounds) == 4:
                x1, y1, x2, y2 = [int(v) for v in bounds]
                if x2 <= x1 or y2 <= y1:
                    bounds = None
            if bounds:
                cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
                radius = min(x2 - x1, y2 - y1) // 2
            elif payload.get('x') is not None and payload.get('y') is not None:
                cx, cy = int(payload['x']), int(payload['y'])
                radius = int(params.get('radius', 100))
            else:
                raise ValueError(
                    'press_hold 缺少坐标来源（element.bounds / 顶层 bounds / '
                    '顶层 x,y / params.center_x,center_y 四选一）')

        dist = max(1, int(radius * 0.8 * strength))
        vx, vy = _PRESS_HOLD_VECTORS[direction]
        tx, ty = int(cx + vx * dist), int(cy + vy * dist)

        from selenium.webdriver.common.action_chains import ActionChains
        raw = getattr(driver, 'raw_driver', driver)
        actions = ActionChains(raw)
        pa = actions.w3c_actions.pointer_action
        pa.move_to_location(cx, cy)
        pa.pointer_down()
        pa.pause(0.25)  # grab判定窗口，防止被误判为页面滑动
        segments = 8
        for i in range(1, segments + 1):
            ix = int(cx + (tx - cx) * i / segments)
            iy = int(cy + (ty - cy) * i / segments)
            pa.move_to_location(ix, iy)
            pa.pause(0.03)
        pa.pause(max(0.3, min(60.0, hold)))
        pa.pointer_up()
        actions.perform()
        return f'摇杆保持成功: {direction} {hold}s ({cx},{cy})->({tx},{ty})'

    # ==================== 辅助 ====================

    def _build_page_digest(self, max_items: int = 20) -> Dict[str, Any]:
        """构建当前页面元素摘要（wait_until超时失败时附带上文，供AI决策）"""
        digest = {'texts': [], 'element_count': 0}
        try:
            if not self._device_service or not self._device_service.is_real():
                return digest
            page_source = self._device_service.get_page_source()
            if not page_source or not self._element_service:
                return digest
            result = self._element_service.refresh_from_page_source(page_source)
            elements = result.get('elements', [])
            digest['element_count'] = len(elements)
            seen = set()
            for e in elements:
                if not e.get('visible', True):
                    continue
                t = e.get('text') or e.get('content_desc') or ''
                if t and t not in seen:
                    seen.add(t)
                    digest['texts'].append(t)
                    if len(digest['texts']) >= max_items:
                        break
        except Exception as e:
            logger.debug(f'[Action] 构建页面摘要失败: {e}')
        return digest


# 全局单例
action_service = ActionService()
