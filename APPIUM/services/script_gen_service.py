"""
Script Gen Service - 脚本生成与执行服务
Phase 2修复：
- 添加logger统一日志
- 使用DriverProxy代替raw driver（自动重试+连接恢复）
- 修复异常静默吞没，所有异常都记录日志
- 线程安全：_is_executing和_last_execution统一在锁内读写
- 执行结束恢复implicitly_wait原值
- 使用PathManager管理目录路径
- 生成脚本跨平台adb路径处理
- 生成脚本添加步骤级异常处理
"""

import os
import re
import sys
import json
import time
import platform
import threading
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime

from backend.utils.logger import get_logger
from backend.utils.paths import GENERATED_SCRIPTS_DIR, TEST_SCREENSHOTS_DIR

logger = get_logger(__name__)


class ScriptGenService:
    """
    脚本生成与执行服务。

    功能：
        1. generate_script()  - 从设计数据生成完整 Python 脚本
        2. execute_inline()   - 在当前设备上直接执行测试步骤（使用DriverProxy）
        3. get_execution_status() - 查询最近一次执行结果
    """

    # 隐式等待配置（秒）
    # 执行期间使用较长等待保证步骤稳定；执行结束恢复为默认值，
    # 保持后续手工查找仍有等待能力（WebDriver无读取当前值的API，故显式管理）
    _EXECUTION_IMPLICIT_WAIT = 10
    _DEFAULT_IMPLICIT_WAIT = 10

    def __init__(self):
        self._design_service = None
        self._device_service = None
        self._lock = threading.RLock()
        self._last_execution: Optional[Dict[str, Any]] = None
        self._is_executing = False

        # 截图保存目录
        self._screenshot_dir = str(TEST_SCREENSHOTS_DIR)
        os.makedirs(self._screenshot_dir, exist_ok=True)

        # 生成的脚本保存目录
        self._scripts_dir = str(GENERATED_SCRIPTS_DIR)
        os.makedirs(self._scripts_dir, exist_ok=True)

    def set_design_service(self, service):
        """注入 ScriptDesignService"""
        self._design_service = service

    def set_device_service(self, service):
        """注入 DeviceService"""
        self._device_service = service

    # ==================== 脚本生成 ====================

    def generate_script(self, case_name: str = '', save: bool = True) -> Dict[str, Any]:
        """
        从当前设计数据生成完整的 Python 脚本。
        """
        if not self._design_service:
            return {'success': False, 'message': '设计服务未初始化'}

        design = self._design_service.get_design()
        steps = design.get('steps', [])
        elements = design.get('elements', [])

        if not steps:
            return {'success': False, 'message': '没有步骤，无法生成脚本'}

        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        safe_name = case_name or 'generated_test'

        device_udid = ''
        if self._device_service and self._device_service.is_real():
            try:
                device_info = self._device_service.get_status().get('device', {})
                device_udid = device_info.get('udid', '')
            except Exception:
                device_udid = ''

        code = self._build_script_code(steps, safe_name, timestamp, len(elements), device_udid)

        filepath = ''
        filename = f"{safe_name}.py"

        if save:
            filepath = os.path.join(self._scripts_dir, filename)
            try:
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(code)
                logger.info(f'[ScriptGen] 脚本已保存: {filepath}')
            except Exception as e:
                logger.error(f'[ScriptGen] 脚本保存失败: {e}', exc_info=True)
                return {'success': False, 'message': f'脚本保存失败: {str(e)}'}

        return {
            'success': True,
            'code': code,
            'filepath': filepath,
            'filename': filename,
            'step_count': len(steps),
            'message': f'脚本已生成: {filename} ({len(steps)} 步骤)'
        }

    def _build_script_code(
        self,
        steps: List[Dict[str, Any]],
        case_name: str,
        timestamp: str,
        element_count: int,
        device_udid: str = ''
    ) -> str:
        """构建完整的 Python 脚本代码字符串"""
        is_windows = platform.system() == 'Windows'
        adb_filename = 'adb.exe' if is_windows else 'adb'

        lines = []
        lines.append('#!/usr/bin/env python3')
        lines.append('"""')
        lines.append(f'Appium 自动化测试脚本')
        lines.append(f'用例名称: {case_name}')
        lines.append(f'生成时间: {timestamp}')
        lines.append(f'元素数量: {element_count}')
        lines.append(f'步骤数量: {len(steps)}')
        if device_udid:
            lines.append(f'目标设备: {device_udid}')
        lines.append('"""')
        lines.append('')
        lines.append('import os')
        lines.append('import sys')
        lines.append('import time')
        lines.append('import platform')
        lines.append('import traceback')
        lines.append('import yaml')
        lines.append('from appium import webdriver')
        lines.append('from appium.options.android import UiAutomator2Options')
        lines.append('from appium.webdriver.common.appiumby import AppiumBy')
        lines.append('from selenium.common.exceptions import WebDriverException')
        lines.append('')
        lines.append('')
        lines.append('# 项目根目录（generated_scripts 的上一级）')
        lines.append('PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))')
        lines.append('')
        lines.append('')

        # create_driver 函数
        lines.append('def create_driver():')
        lines.append('    """从 config.yaml 创建 Appium driver"""')
        lines.append('    config_path = os.path.join(PROJECT_ROOT, "config.yaml")')
        lines.append('    with open(config_path, "r", encoding="utf-8") as f:')
        lines.append('        config = yaml.safe_load(f) or {}')
        lines.append('    appium_cfg = config.get("appium", {})')
        lines.append('    options = UiAutomator2Options()')
        lines.append('    options.platform_name = "Android"')
        lines.append('    options.automation_name = "UiAutomator2"')
        lines.append('    options.no_reset = True')
        lines.append('    options.new_command_timeout = appium_cfg.get("new_command_timeout", 300)')
        lines.append('    options.set_capability("appium:ignoreHiddenApiPolicyError", True)')
        lines.append('    options.set_capability("appium:skipServerInstallation", True)')
        lines.append('    options.set_capability("appium:skipServerStartup", False)')
        lines.append('    # 使用项目自带的 adb，避免版本不一致')
        lines.append(f'    _adb_name = "adb.exe" if platform.system() == "Windows" else "adb"')
        lines.append('    _adb_path = os.path.join(PROJECT_ROOT, "bin", _adb_name)')
        lines.append('    if os.path.isfile(_adb_path):')
        lines.append('        options.set_capability("adbExecPath", _adb_path)')
        if device_udid:
            lines.append(f'    options.udid = "{device_udid}"  # 目标设备')
        lines.append('    driver = webdriver.Remote(')
        lines.append('        command_executor=f"http://{appium_cfg.get(\'host\', \'127.0.0.1\')}:{appium_cfg.get(\'port\', 4723)}",')
        lines.append('        options=options')
        lines.append('    )')
        lines.append('    driver.implicitly_wait(10)')
        lines.append('    return driver')
        lines.append('')
        lines.append('')

        # find_element 辅助函数
        lines.append('def find_element(driver, element, timeout=10):')
        lines.append('    """使用最佳定位器查找元素（带重试）"""')
        lines.append('    from selenium.common.exceptions import NoSuchElementException')
        lines.append('    last_err = None')
        lines.append('    for attempt in range(3):')
        lines.append('        try:')
        lines.append('            if element.get("resource_id"):')
        lines.append('                return driver.find_element(AppiumBy.ID, element["resource_id"])')
        lines.append('            elif element.get("xpath"):')
        lines.append('                return driver.find_element(AppiumBy.XPATH, element["xpath"])')
        lines.append('            elif element.get("content_desc"):')
        lines.append('                return driver.find_element(AppiumBy.ACCESSIBILITY_ID, element["content_desc"])')
        lines.append('            else:')
        lines.append('                raise ValueError("元素无可用定位器")')
        lines.append('        except NoSuchElementException as e:')
        lines.append('            last_err = e')
        lines.append('            if attempt < 2:')
        lines.append('                time.sleep(1)')
        lines.append('    raise last_err if last_err else NoSuchElementException("元素未找到")')
        lines.append('')
        lines.append('')

        # do_swipe 辅助函数
        lines.append('def do_swipe(driver, direction):')
        lines.append('    """执行滑动操作"""')
        lines.append('    size = driver.get_window_size()')
        lines.append('    w, h = size["width"], size["height"]')
        lines.append('    cx, cy = w // 2, h // 2')
        lines.append('    offset = min(w, h) // 2 - 50')
        lines.append('    if direction == "up":')
        lines.append('        driver.swipe(cx, cy + offset, cx, cy - offset, 500)')
        lines.append('    elif direction == "down":')
        lines.append('        driver.swipe(cx, cy - offset, cx, cy + offset, 500)')
        lines.append('    elif direction == "left":')
        lines.append('        driver.swipe(cx + offset, cy, cx - offset, cy, 500)')
        lines.append('    elif direction == "right":')
        lines.append('        driver.swipe(cx - offset, cy, cx + offset, cy, 500)')
        lines.append('    else:')
        lines.append('        raise ValueError(f"未知滑动方向: {direction}")')
        lines.append('')
        lines.append('')

        # do_press_hold 辅助函数（仅当用例包含 press_hold 步骤时生成，不影响既有用例输出）
        if any(s.get('action') == 'press_hold' for s in steps):
            lines.append('def do_press_hold(driver, cx, cy, tx, ty, hold):')
            lines.append('    """摇杆按住保持手势：按下中心→grab判定停留→8步分段拖偏→保持hold秒→抬起"""')
            lines.append('    from selenium.webdriver.common.action_chains import ActionChains')
            lines.append('    actions = ActionChains(driver)')
            lines.append('    pa = actions.w3c_actions.pointer_action')
            lines.append('    pa.move_to_location(cx, cy)')
            lines.append('    pa.pointer_down()')
            lines.append('    pa.pause(0.25)  # grab 判定窗口，防止被误判为页面滑动')
            lines.append('    segments = 8')
            lines.append('    for i in range(1, segments + 1):')
            lines.append('        ix = int(cx + (tx - cx) * i / segments)')
            lines.append('        iy = int(cy + (ty - cy) * i / segments)')
            lines.append('        pa.move_to_location(ix, iy)')
            lines.append('        pa.pause(0.03)')
            lines.append('    pa.pause(max(0.3, min(60.0, float(hold))))  # 保持偏转，机器人持续运动')
            lines.append('    pa.pointer_up()')
            lines.append('    actions.perform()')
            lines.append('')
            lines.append('')

        # run_test 函数（每个步骤独立try/except）
        lines.append('def run_test(driver, continue_on_failure=False):')
        lines.append('    """执行测试步骤，每个步骤独立异常处理"""')
        lines.append('    results = []')
        lines.append('    all_passed = True')
        step_code_lines = []
        for i, step in enumerate(steps):
            step_code_lines.append(self._build_step_code(step, i == 0))
        lines.extend(step_code_lines)
        lines.append('    return all_passed, results')
        lines.append('')
        lines.append('')

        # main 入口
        lines.append('if __name__ == "__main__":')
        lines.append('    driver = None')
        lines.append('    try:')
        lines.append('        driver = create_driver()')
        lines.append('        print("设备连接成功")')
        lines.append('        passed, results = run_test(driver, continue_on_failure=False)')
        lines.append('        if passed:')
        lines.append('            print("测试执行完成，全部通过")')
        lines.append('        else:')
        lines.append('            print("测试执行完成，存在失败步骤")')
        lines.append('            sys.exit(1)')
        lines.append('    except Exception as e:')
        lines.append('        print(f"测试失败: {e}")')
        lines.append('        traceback.print_exc()')
        lines.append('        if driver:')
        lines.append('            try:')
        lines.append('                driver.save_screenshot("error_screenshot.png")')
        lines.append('            except Exception:')
        lines.append('                pass')
        lines.append('        sys.exit(1)')
        lines.append('    finally:')
        lines.append('        if driver:')
        lines.append('            try:')
        lines.append('                driver.quit()')
        lines.append('            except Exception:')
        lines.append('                pass')
        lines.append('            print("设备已断开")')

        return '\n'.join(lines)

    def _build_step_code(self, step: Dict[str, Any], is_first: bool = False) -> str:
        """将单个步骤转换为 Python 代码行（每个步骤包裹在try/except中）"""
        action = step.get('action', '')
        params = step.get('action_params', {})
        element = step.get('element')
        desc = step.get('description', '')
        order = step.get('step_order', '?')

        comment = f'    # 步骤 {order}: {desc or action}'
        indent = '    '

        lines = [comment]

        if action == 'click' and element:
            elem_repr = self._format_element_for_code(element)
            lines.append(f'{indent}try:')
            lines.append(f'{indent}    el = find_element(driver, {elem_repr})')
            lines.append(f'{indent}    el.click()')
            lines.append(f'{indent}    results.append({{"step": {order}, "action": "click", "success": True, "message": "点击成功"}})')
            lines.append(f'{indent}    print(f"步骤{order} 点击成功")')
            lines.append(f'{indent}except Exception as e:')
            lines.append(f'{indent}    results.append({{"step": {order}, "action": "click", "success": False, "message": str(e)}})')
            lines.append(f'{indent}    print(f"步骤{order} 点击失败: {{e}}")')
            lines.append(f'{indent}    all_passed = False')
            lines.append(f'{indent}    if not continue_on_failure: raise')

        elif action == 'input' and element:
            elem_repr = self._format_element_for_code(element)
            value = params.get('value', '')
            value_repr = json.dumps(value, ensure_ascii=False)
            lines.append(f'{indent}try:')
            lines.append(f'{indent}    el = find_element(driver, {elem_repr})')
            lines.append(f'{indent}    el.clear()')
            lines.append(f'{indent}    el.send_keys({value_repr})')
            lines.append(f'{indent}    results.append({{"step": {order}, "action": "input", "success": True, "message": "输入成功"}})')
            lines.append(f'{indent}    print(f"步骤{order} 输入成功")')
            lines.append(f'{indent}except Exception as e:')
            lines.append(f'{indent}    results.append({{"step": {order}, "action": "input", "success": False, "message": str(e)}})')
            lines.append(f'{indent}    print(f"步骤{order} 输入失败: {{e}}")')
            lines.append(f'{indent}    all_passed = False')
            lines.append(f'{indent}    if not continue_on_failure: raise')

        elif action == 'swipe':
            direction = params.get('direction', 'up')
            lines.append(f'{indent}try:')
            lines.append(f'{indent}    do_swipe(driver, {json.dumps(direction)})')
            lines.append(f'{indent}    results.append({{"step": {order}, "action": "swipe", "success": True, "message": "滑动成功"}})')
            lines.append(f'{indent}    print(f"步骤{order} 滑动{direction}成功")')
            lines.append(f'{indent}except Exception as e:')
            lines.append(f'{indent}    results.append({{"step": {order}, "action": "swipe", "success": False, "message": str(e)}})')
            lines.append(f'{indent}    print(f"步骤{order} 滑动失败: {{e}}")')
            lines.append(f'{indent}    all_passed = False')
            lines.append(f'{indent}    if not continue_on_failure: raise')

        elif action == 'press_hold':
            direction = params.get('direction', 'up')
            hold = params.get('hold', 1)
            try:
                # 生成期从元素 bounds（或显式坐标）算好坐标并内联，脚本零依赖可独立运行
                cx, cy, tx, ty = self._resolve_press_hold_points(step)
                lines.append(f'{indent}try:')
                lines.append(f'{indent}    do_press_hold(driver, {cx}, {cy}, {tx}, {ty}, {json.dumps(hold)})')
                lines.append(f'{indent}    results.append({{"step": {order}, "action": "press_hold", "success": True, "message": "摇杆保持成功"}})')
                lines.append(f'{indent}    print(f"步骤{order} 摇杆保持{direction} {hold}s成功")')
                lines.append(f'{indent}except Exception as e:')
                lines.append(f'{indent}    results.append({{"step": {order}, "action": "press_hold", "success": False, "message": str(e)}})')
                lines.append(f'{indent}    print(f"步骤{order} 摇杆保持失败: {{e}}")')
                lines.append(f'{indent}    all_passed = False')
                lines.append(f'{indent}    if not continue_on_failure: raise')
            except ValueError as e:
                lines.append(f'{indent}results.append({{"step": {order}, "action": "press_hold", "success": False, "message": {json.dumps(str(e), ensure_ascii=False)}}})')
                lines.append(f'{indent}all_passed = False')

        elif action == 'wait':
            timeout = params.get('timeout', 3)
            lines.append(f'{indent}time.sleep({timeout})')
            lines.append(f'{indent}results.append({{"step": {order}, "action": "wait", "success": True, "message": "等待完成"}})')

        elif action == 'back':
            lines.append(f'{indent}try:')
            lines.append(f'{indent}    driver.back()')
            lines.append(f'{indent}    results.append({{"step": {order}, "action": "back", "success": True, "message": "返回成功"}})')
            lines.append(f'{indent}    print(f"步骤{order} 返回成功")')
            lines.append(f'{indent}except Exception as e:')
            lines.append(f'{indent}    results.append({{"step": {order}, "action": "back", "success": False, "message": str(e)}})')
            lines.append(f'{indent}    print(f"步骤{order} 返回失败: {{e}}")')
            lines.append(f'{indent}    all_passed = False')
            lines.append(f'{indent}    if not continue_on_failure: raise')

        elif action == 'screenshot':
            lines.append(f'{indent}try:')
            lines.append(f'{indent}    driver.save_screenshot(f"screenshot_step_{order}.png")')
            lines.append(f'{indent}    results.append({{"step": {order}, "action": "screenshot", "success": True, "message": "截图成功"}})')
            lines.append(f'{indent}except Exception as e:')
            lines.append(f'{indent}    results.append({{"step": {order}, "action": "screenshot", "success": False, "message": str(e)}})')
            lines.append(f'{indent}    print(f"步骤{order} 截图失败: {{e}}")')

        else:
            lines.append(f'{indent}results.append({{"step": {order}, "action": "unknown", "success": False, "message": "未知动作"}})')

        return '\n'.join(lines)

    def _format_element_for_code(self, element: Dict[str, Any]) -> str:
        """将元素数据格式化为 Python dict 字符串"""
        parts = []
        if element.get('resource_id'):
            parts.append(f'"resource_id": {json.dumps(element["resource_id"], ensure_ascii=False)}')
        if element.get('xpath'):
            parts.append(f'"xpath": {json.dumps(element["xpath"], ensure_ascii=False)}')
        if element.get('content_desc'):
            parts.append(f'"content_desc": {json.dumps(element["content_desc"], ensure_ascii=False)}')
        return '{' + ', '.join(parts) + '}'

    # ==================== 内联执行 ====================

    def execute_inline(self, continue_on_failure: bool = False) -> Dict[str, Any]:
        """
        在当前已连接的设备上直接执行测试步骤。
        使用DriverProxy（含自动重试），执行前暂停心跳保活，执行后恢复。
        """
        with self._lock:
            if self._is_executing:
                return {'success': False, 'message': '已有测试正在执行中，请等待完成'}

            # 前置检查
            if not self._device_service:
                return {'success': False, 'message': '设备服务未初始化'}
            if not self._device_service.is_real():
                return {'success': False, 'message': '设备未连接或处于模拟模式，请先连接真实设备'}
            if not self._design_service:
                return {'success': False, 'message': '设计服务未初始化'}

            design = self._design_service.get_design()
            steps = design.get('steps', [])
            if not steps:
                return {'success': False, 'message': '没有可执行的步骤'}

            # 优先使用DriverProxy（含自动重试和连接恢复）
            driver = self._device_service.get_driver_proxy()
            if not driver:
                # 回退到raw driver
                driver = self._device_service.get_driver()
            if not driver:
                return {'success': False, 'message': '无法获取 Appium driver'}

            self._is_executing = True
            logger.info(f'[ScriptGen] 开始内联执行: {len(steps)}步, continue_on_failure={continue_on_failure}')

        # 暂停心跳保活
        self._device_service.pause_keepalive()

        results = []
        all_success = True
        error_screenshot_path = None

        try:
            # 设置执行期隐式等待
            # 注意：WebDriver没有查询当前隐式等待值的API，
            # 执行结束后统一恢复为_DEFAULT_IMPLICIT_WAIT（不再清零，
            # 避免执行后手工查找元素因零等待而失败）
            try:
                driver.implicitly_wait(self._EXECUTION_IMPLICIT_WAIT)
            except Exception as e:
                logger.warning(f'[ScriptGen] 设置implicitly_wait失败: {e}')

            for step in steps:
                step_result = self._execute_step(driver, step)
                results.append({
                    'step_id': step.get('step_id', ''),
                    'step_order': step.get('step_order', 0),
                    'action': step.get('action', ''),
                    'description': step.get('description', ''),
                    'success': step_result['success'],
                    'message': step_result['message'],
                    'screenshot': step_result.get('screenshot', '')
                })

                if not step_result['success']:
                    all_success = False
                    # 失败时截图（记录日志而非静默pass）
                    try:
                        error_screenshot_path = os.path.join(
                            self._screenshot_dir,
                            f'error_step_{step.get("step_order", 0)}_{int(time.time())}.png'
                        )
                        if hasattr(driver, 'take_screenshot_safe'):
                            driver.take_screenshot_safe(error_screenshot_path)
                        elif hasattr(driver, 'get_screenshot_as_file'):
                            driver.get_screenshot_as_file(error_screenshot_path)
                        elif hasattr(driver, 'save_screenshot'):
                            driver.save_screenshot(error_screenshot_path)
                        logger.info(f'[ScriptGen] 失败截图已保存: {error_screenshot_path}')
                    except Exception as e:
                        logger.warning(f'[ScriptGen] 失败截图保存失败: {e}')
                        error_screenshot_path = None

                    if not continue_on_failure:
                        logger.warning(f'[ScriptGen] 步骤失败，停止执行 (continue_on_failure=False)')
                        break  # 遇到失败停止执行

        except Exception as e:
            all_success = False
            logger.error(f'[ScriptGen] 执行异常: {e}', exc_info=True)
            results.append({
                'step_id': '',
                'step_order': len(results) + 1,
                'action': '',
                'description': '',
                'success': False,
                'message': f'执行异常: {str(e)}',
                'screenshot': ''
            })
        finally:
            # 恢复隐式等待为默认值（而非清零），保持执行后的查找操作仍有等待能力
            try:
                driver.implicitly_wait(self._DEFAULT_IMPLICIT_WAIT)
            except Exception:
                pass

            # 恢复心跳保活
            try:
                self._device_service.resume_keepalive()
            except Exception as e:
                logger.error(f'[ScriptGen] 恢复心跳失败: {e}')

            with self._lock:
                self._is_executing = False

        execution_result = {
            'success': all_success,
            'total_steps': len(steps),
            'executed_steps': len(results),
            'results': results,
            'executed_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'error_screenshot': error_screenshot_path if error_screenshot_path else ''
        }

        with self._lock:
            self._last_execution = execution_result

        logger.info(f'[ScriptGen] 执行完成: success={all_success}, executed={len(results)}/{len(steps)}')
        return execution_result

    def _execute_step(self, driver, step: Dict[str, Any]) -> Dict[str, Any]:
        """执行单个测试步骤（通过DriverProxy，含自动重试）"""
        action = step.get('action', '')
        params = step.get('action_params', {})
        element = step.get('element')
        desc = step.get('description', '')
        order = step.get('step_order', '?')

        step_label = f'步骤 {order}: {desc or action}'

        try:
            if action == 'click':
                # 半坐标方案：多模块复用同一 resource_id/xpath 时，find_element 返回
                # 文档序第一个匹配（可能是不可见实例）。优先使用抓取时已保存的
                # bounds 中心坐标 tap；bounds 缺失/解析失败/越界时回退 find_element。
                point = self._resolve_click_point(driver, element)
                if point is not None:
                    self._tap_point(driver, point[0], point[1])
                    logger.debug(f'[ScriptGen] {step_label} - 坐标点击成功 ({point[0]},{point[1]})')
                    return {'success': True, 'message': f'{step_label} - 点击成功(坐标 {point[0]},{point[1]})'}
                # 兜底：原有元素定位逻辑（保留不删）
                el = self._find_element(driver, element)
                el.click()
                logger.debug(f'[ScriptGen] {step_label} - 点击成功')
                return {'success': True, 'message': f'{step_label} - 点击成功'}

            elif action == 'input':
                el = self._find_element(driver, element)
                el.clear()
                el.send_keys(params.get('value', ''))
                logger.debug(f'[ScriptGen] {step_label} - 输入成功')
                return {'success': True, 'message': f'{step_label} - 输入成功: "{params.get("value", "")}"'}

            elif action == 'swipe':
                direction = params.get('direction', 'up')
                self._do_swipe(driver, direction)
                logger.debug(f'[ScriptGen] {step_label} - 滑动成功')
                return {'success': True, 'message': f'{step_label} - 滑动成功: {direction}'}

            elif action == 'press_hold':
                direction = params.get('direction', 'up')
                hold = float(params.get('hold', 1))
                cx, cy, tx, ty = self._resolve_press_hold_points(step)
                self._do_press_hold(driver, cx, cy, tx, ty, hold)
                logger.debug(f'[ScriptGen] {step_label} - 摇杆保持成功')
                return {'success': True, 'message': f'{step_label} - 摇杆保持成功: {direction} {hold}s'}

            elif action == 'wait':
                try:
                    timeout = int(params.get('timeout', 3))
                except (ValueError, TypeError):
                    timeout = 3
                timeout = max(1, min(timeout, 300))
                time.sleep(timeout)
                logger.debug(f'[ScriptGen] {step_label} - 等待{timeout}s完成')
                return {'success': True, 'message': f'{step_label} - 等待 {timeout}s 完成'}

            elif action == 'back':
                driver.back()
                logger.debug(f'[ScriptGen] {step_label} - 返回成功')
                return {'success': True, 'message': f'{step_label} - 返回键已按下'}

            elif action == 'screenshot':
                filepath = os.path.join(
                    self._screenshot_dir,
                    f'step_{order}_{int(time.time())}.png'
                )
                # 兼容DriverProxy和raw driver
                if hasattr(driver, 'take_screenshot_safe'):
                    driver.take_screenshot_safe(filepath)
                elif hasattr(driver, 'get_screenshot_as_file'):
                    driver.get_screenshot_as_file(filepath)
                else:
                    driver.save_screenshot(filepath)
                logger.debug(f'[ScriptGen] {step_label} - 截图已保存')
                return {'success': True, 'message': f'{step_label} - 截图已保存', 'screenshot': filepath}

            else:
                logger.warning(f'[ScriptGen] {step_label} - 未知动作: {action}')
                return {'success': False, 'message': f'{step_label} - 未知动作: {action}'}

        except Exception as e:
            logger.error(f'[ScriptGen] {step_label} - 执行失败: {e}')
            return {'success': False, 'message': f'{step_label} - 执行失败: {str(e)}'}

    def _resolve_click_point(self, driver, element: Optional[Dict[str, Any]]) -> Optional[Tuple[int, int]]:
        """
        半坐标方案：解析元素 bounds 的中心点，供坐标点击使用。
        解决多模块复用同一 resource_id/xpath 时 find_element 命中不可见实例的问题。
        bounds 缺失、解析失败、或中心点超出屏幕范围时返回 None（调用方回退 find_element）。
        兼容两种 bounds 格式：列表 [x1,y1,x2,y2]（平台抓取格式）、字符串 "[x1,y1][x2,y2]"。
        """
        if not element:
            return None
        bounds = element.get('bounds')
        if not bounds:
            return None
        try:
            if isinstance(bounds, str):
                nums = re.findall(r'-?\d+', bounds)
                if len(nums) != 4:
                    return None
                x1, y1, x2, y2 = [int(v) for v in nums]
            else:
                if len(bounds) != 4:
                    return None
                x1, y1, x2, y2 = [int(v) for v in bounds]
        except (TypeError, ValueError):
            return None
        # 全零/翻转的 bounds 视为无效（未布局或已失效元素）
        if x2 <= x1 or y2 <= y1:
            return None
        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
        # 屏幕范围校验：越界说明抓取后布局已变化，坐标不可信
        try:
            size = driver.get_window_size()
            if not (0 <= cx <= int(size.get('width', 0)) and 0 <= cy <= int(size.get('height', 0))):
                logger.debug(f'[ScriptGen] bounds 中心 ({cx},{cy}) 越界，回退元素定位')
                return None
        except Exception:
            pass  # 尺寸获取失败时不阻断坐标路径
        return cx, cy

    def _tap_point(self, driver, x: int, y: int):
        """
        坐标点击：优先 Appium driver.tap（MJSONWP touch 接口，UiAutomator2 稳定）；
        若 driver 无 tap 方法，退化为 W3C Actions 点触（与 press_hold 同一事件通道）。
        """
        if hasattr(driver, 'tap'):
            driver.tap([(x, y)])
            return
        from selenium.webdriver.common.action_chains import ActionChains
        actions = ActionChains(driver)
        pa = actions.w3c_actions.pointer_action
        pa.move_to_location(x, y)
        pa.pointer_down()
        pa.pause(0.05)
        pa.pointer_up()
        actions.perform()

    def _find_element(self, driver, element: Optional[Dict[str, Any]]):
        """使用最佳定位器查找元素（通过DriverProxy自动重试）"""
        from appium.webdriver.common.appiumby import AppiumBy

        if not element:
            raise ValueError('元素数据为空')

        if element.get('resource_id'):
            return driver.find_element(AppiumBy.ID, element['resource_id'])
        elif element.get('xpath'):
            return driver.find_element(AppiumBy.XPATH, element['xpath'])
        elif element.get('content_desc'):
            return driver.find_element(AppiumBy.ACCESSIBILITY_ID, element['content_desc'])
        else:
            raise ValueError('元素无可用定位器')

    def _do_swipe(self, driver, direction: str):
        """执行滑动操作（通过DriverProxy自动重试）"""
        size = driver.get_window_size()
        w = size['width']
        h = size['height']
        cx = w // 2
        cy = h // 2
        offset = min(w, h) // 2 - 50

        if direction == 'up':
            driver.swipe(cx, cy + offset, cx, cy - offset, 500)
        elif direction == 'down':
            driver.swipe(cx, cy - offset, cx, cy + offset, 500)
        elif direction == 'left':
            driver.swipe(cx + offset, cy, cx - offset, cy, 500)
        elif direction == 'right':
            driver.swipe(cx - offset, cy, cx + offset, cy, 500)
        else:
            raise ValueError(f'未知滑动方向: {direction}')

    def _resolve_press_hold_points(self, step: Dict[str, Any]) -> Tuple[int, int, int, int]:
        """
        解析 press_hold 的中心点与偏转目标点坐标。
        显式 center_x/center_y + radius 优先（自绘控件退路），否则用元素 bounds 推导。
        返回 (cx, cy, tx, ty)。
        """
        params = step.get('action_params', {})
        element = step.get('element') or {}
        direction = params.get('direction', 'up')
        try:
            strength = float(params.get('strength', 0.8) or 0.8)
        except (ValueError, TypeError):
            strength = 0.8
        strength = max(0.1, min(1.0, strength))

        if 'center_x' in params and 'center_y' in params:
            cx, cy = int(params['center_x']), int(params['center_y'])
            radius = int(params.get('radius', 100))
        else:
            bounds = element.get('bounds')
            if not bounds or len(bounds) != 4 or list(bounds) == [0, 0, 0, 0]:
                raise ValueError('press_hold 缺少坐标来源（元素 bounds 或 center_x/center_y + radius）')
            x1, y1, x2, y2 = [int(v) for v in bounds]
            cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
            radius = min(x2 - x1, y2 - y1) // 2

        # 0.8 安全系数防止拖出控件边界，导致事件流被路由到其他 View
        dist = max(1, int(radius * 0.8 * strength))
        vectors = {'up': (0, -1), 'down': (0, 1), 'left': (-1, 0), 'right': (1, 0)}
        vx, vy = vectors.get(direction, (0, -1))
        return cx, cy, cx + vx * dist, cy + vy * dist

    def _do_press_hold(self, driver, cx: int, cy: int, tx: int, ty: int, hold: float):
        """
        摇杆按住保持手势（W3C Actions 五段事件流，通过DriverProxy自动重试）：
        按下摇杆中心 → 250ms grab判定停留 → 8步分段拖偏 → 保持hold秒 → 抬起。
        """
        from selenium.webdriver.common.action_chains import ActionChains

        actions = ActionChains(driver)
        pa = actions.w3c_actions.pointer_action
        pa.move_to_location(cx, cy)
        pa.pointer_down()
        pa.pause(0.25)  # grab 判定窗口，防止被 App 误判为页面滑动
        segments = 8
        for i in range(1, segments + 1):
            ix = int(cx + (tx - cx) * i / segments)
            iy = int(cy + (ty - cy) * i / segments)
            pa.move_to_location(ix, iy)
            pa.pause(0.03)  # 连续 move 事件流密度 ≈ 真实手指（总时长约240ms）
        pa.pause(max(0.3, min(60.0, float(hold))))  # 保持偏转，机器人持续运动
        pa.pointer_up()
        actions.perform()

    # ==================== 状态查询 ====================

    def get_execution_status(self) -> Dict[str, Any]:
        """获取最近一次执行结果（线程安全）"""
        with self._lock:
            is_exec = self._is_executing
            last_exec = self._last_execution

        if not last_exec:
            return {
                'success': False,
                'message': '暂无执行记录',
                'is_executing': is_exec
            }
        result = dict(last_exec)
        result['is_executing'] = is_exec
        return result

    def is_executing(self) -> bool:
        """是否正在执行（线程安全）"""
        with self._lock:
            return self._is_executing


# 全局单例
script_gen_service = ScriptGenService()
