"""
Element Service - 管理元素数据
Phase 2修复：
- 替换print()为logger统一日志
- 添加线程锁保护并发访问
- 添加深拷贝返回防止调用方修改内部状态
- 刷新时重置_elem_counter避免ID无限增长
- 添加ElementRepository集成用于快照持久化
- 改善错误处理，TOCTOU问题修复
"""

import re
import copy
import threading
from typing import List, Dict, Any, Optional

from lxml import etree

from backend.utils.logger import get_logger

logger = get_logger(__name__)


class ElementService:
    def __init__(self):
        self._elements: List[Dict[str, Any]] = []
        self._device_service = None
        self._element_repo = None  # 通过setter注入
        self._elem_counter = 0
        self._lock = threading.RLock()  # 保护_elements和_elem_counter

        # 模拟元素（无真实设备时使用）
        self._mock_elements = [
            {
                'id': 'elem_1',
                'tag': 'android.widget.TextView',
                'text': '欢迎登录',
                'content_desc': '',
                'resource_id': 'com.example.app:id/tv_welcome',
                'bounds': [120, 200, 360, 260],
                'class': 'android.widget.TextView',
                'package': 'com.example.app',
                'clickable': False,
                'enabled': True,
                'xpath': '//android.widget.TextView[@text="欢迎登录"]'
            },
            {
                'id': 'elem_2',
                'tag': 'android.widget.EditText',
                'text': '请输入用户名',
                'content_desc': '用户名输入框',
                'resource_id': 'com.example.app:id/et_username',
                'bounds': [80, 300, 400, 360],
                'class': 'android.widget.EditText',
                'package': 'com.example.app',
                'clickable': True,
                'enabled': True,
                'xpath': '//android.widget.EditText[@resource-id="com.example.app:id/et_username"]'
            },
            {
                'id': 'elem_3',
                'tag': 'android.widget.EditText',
                'text': '请输入密码',
                'content_desc': '密码输入框',
                'resource_id': 'com.example.app:id/et_password',
                'bounds': [80, 380, 400, 440],
                'class': 'android.widget.EditText',
                'package': 'com.example.app',
                'clickable': True,
                'enabled': True,
                'xpath': '//android.widget.EditText[@resource-id="com.example.app:id/et_password"]'
            },
            {
                'id': 'elem_4',
                'tag': 'android.widget.Button',
                'text': '登录',
                'content_desc': '登录按钮',
                'resource_id': 'com.example.app:id/btn_login',
                'bounds': [140, 480, 340, 540],
                'class': 'android.widget.Button',
                'package': 'com.example.app',
                'clickable': True,
                'enabled': True,
                'xpath': '//android.widget.Button[@text="登录"]'
            },
            {
                'id': 'elem_5',
                'tag': 'android.widget.CheckBox',
                'text': '记住我',
                'content_desc': '',
                'resource_id': 'com.example.app:id/cb_remember',
                'bounds': [80, 560, 240, 600],
                'class': 'android.widget.CheckBox',
                'package': 'com.example.app',
                'clickable': True,
                'enabled': True,
                'xpath': '//android.widget.CheckBox[@text="记住我"]'
            }
        ]

    def set_device_service(self, device_service):
        """注入 device_service 以获取真实 page_source"""
        self._device_service = device_service

    def set_element_repository(self, repo):
        """注入 ElementRepository 用于快照持久化"""
        self._element_repo = repo

    # ---------- 真实 XML 解析 ----------
    def _parse_bounds(self, bounds_str: str) -> List[int]:
        """解析 bounds 字符串 '[x1,y1][x2,y2]' 为 [x1, y1, x2, y2]"""
        match = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bounds_str or '')
        if match:
            return [int(match.group(1)), int(match.group(2)),
                    int(match.group(3)), int(match.group(4))]
        return [0, 0, 0, 0]

    def _to_bool(self, value: str) -> bool:
        """将 'true'/'false' 字符串转为布尔值"""
        return str(value).lower().strip() == 'true'

    @staticmethod
    def _xpath_attr_value(value: str) -> str:
        """
        构建 XPath 属性值，自动处理双引号/单引号转义。
        XPath 1.0 不支持转义引号，需用 concat() 拼接含两种引号的字符串。
        """
        value = value or ''
        if '"' not in value:
            return f'"{value}"'
        if "'" not in value:
            return f"'{value}'"
        parts = value.split('"')
        concat_parts = []
        for i, part in enumerate(parts):
            if i > 0:
                concat_parts.append('"\""')
            if part:
                concat_parts.append(f'"{part}"')
        return f'concat({", ".join(concat_parts)})'

    def _generate_xpath(self, node, class_name: str) -> str:
        """
        为元素生成 xpath 定位器
        优先级：resource-id > text > content-desc > class + index
        """
        resource_id = node.get('resource-id', '')
        text = node.get('text', '')
        content_desc = node.get('content-desc', '')

        tag = class_name or node.tag

        if resource_id:
            return f'//{tag}[@resource-id={self._xpath_attr_value(resource_id)}]'
        if text:
            return f'//{tag}[@text={self._xpath_attr_value(text)}]'
        if content_desc:
            return f'//{tag}[@content-desc={self._xpath_attr_value(content_desc)}]'

        index = node.get('index', '0')
        return f'//{tag}[@index="{index}"]'

    def parse_page_source(self, page_source: str) -> List[Dict[str, Any]]:
        """
        解析 Appium page_source XML，返回结构化元素列表（文档序）。
        过滤掉 bounds 为 [0,0,0,0] 的未布局节点（但其子节点仍正常挂载到
        最近的有 bounds 祖先下，保证树形层级正确）。

        每个元素在旧字段基础上增量提供（向后兼容）：
        - parent_id: 父元素 id（最近的有 bounds 祖先），根为 None
        - children: 子元素 id 列表
        - scrollable_ancestor: 最近的可滚动祖先元素 id，无则 None
        - obscured_by: 遮挡该元素中心点的顶层元素 id，未被遮挡为 None
          （基于文档序近似 z-order：后出现的兄弟节点在上层，弹窗场景有效）
        - visible: bounds 有效 + 在屏幕内 + 未被遮挡
        """
        elements: List[Dict[str, Any]] = []

        try:
            if isinstance(page_source, str):
                page_source_bytes = page_source.encode('utf-8')
            else:
                page_source_bytes = page_source

            root = etree.fromstring(page_source_bytes)
        except etree.XMLSyntaxError as e:
            logger.error(f'[ElementService] XML解析失败: {e}')
            return []
        except Exception as e:
            logger.error(f'[ElementService] page_source解析异常: {e}', exc_info=True)
            return []

        screen_w = 0
        screen_h = 0

        def _walk(node, kept_parent_id):
            nonlocal screen_w, screen_h
            tag = node.tag
            if not tag or (isinstance(tag, str) and tag.startswith('_')):
                return
            if tag == 'hierarchy':
                for child in node:
                    _walk(child, kept_parent_id)
                return

            bounds = self._parse_bounds(node.get('bounds', '[0,0][0,0]'))
            my_id = kept_parent_id

            if bounds != [0, 0, 0, 0]:
                class_name = node.get('class', tag)
                with self._lock:
                    self._elem_counter += 1
                    elem_id = f'elem_{self._elem_counter}'

                elem = {
                    'id': elem_id,
                    'tag': class_name,
                    'text': node.get('text', ''),
                    'content_desc': node.get('content-desc', ''),
                    'resource_id': node.get('resource-id', ''),
                    'bounds': bounds,
                    'class': class_name,
                    'package': node.get('package', ''),
                    'clickable': self._to_bool(node.get('clickable', 'false')),
                    'enabled': self._to_bool(node.get('enabled', 'true')),
                    'focusable': self._to_bool(node.get('focusable', 'false')),
                    'scrollable': self._to_bool(node.get('scrollable', 'false')),
                    'checked': self._to_bool(node.get('checked', 'false')),
                    'xpath': self._generate_xpath(node, class_name),
                    # ---- 增量字段（1.4 元素树升级） ----
                    'parent_id': kept_parent_id,
                    'children': [],
                    'scrollable_ancestor': None,
                    'obscured_by': None,
                    'visible': True,
                }
                elements.append(elem)
                my_id = elem_id
                screen_w = max(screen_w, bounds[2])
                screen_h = max(screen_h, bounds[3])

            for child in node:
                _walk(child, my_id)

        for top in root:
            _walk(top, None)

        self._annotate_tree(elements, screen_w, screen_h)
        logger.debug(f'[ElementService] 解析完成: {len(elements)} 个元素')
        return elements

    @staticmethod
    def _annotate_tree(elements: List[Dict[str, Any]], screen_w: int, screen_h: int):
        """后处理：填充 children / scrollable_ancestor / obscured_by / visible"""
        by_id = {e['id']: e for e in elements}

        def is_ancestor(maybe_anc, elem):
            pid = elem.get('parent_id')
            while pid:
                if pid == maybe_anc['id']:
                    return True
                pid = by_id.get(pid, {}).get('parent_id')
            return False

        # children + scrollable_ancestor
        for e in elements:
            pid = e.get('parent_id')
            if pid and pid in by_id:
                by_id[pid]['children'].append(e['id'])
            # 最近可滚动祖先
            cur = by_id.get(pid) if pid else None
            while cur is not None:
                if cur.get('scrollable'):
                    e['scrollable_ancestor'] = cur['id']
                    break
                cur = by_id.get(cur.get('parent_id'))

        # obscured_by + visible（文档序近似z-order：后出现者在上层）
        n = len(elements)
        for i in range(n):
            e = elements[i]
            x1, y1, x2, y2 = e['bounds']
            cx, cy = (x1 + x2) // 2, (y1 + y2) // 2

            on_screen = (x2 > 0 and y2 > 0 and
                         (screen_w == 0 or x1 < screen_w) and
                         (screen_h == 0 or y1 < screen_h))

            best = None
            best_area = None
            for j in range(i + 1, n):
                f = elements[j]
                fx1, fy1, fx2, fy2 = f['bounds']
                if not (fx1 <= cx <= fx2 and fy1 <= cy <= fy2):
                    continue
                # 祖先/后代互相覆盖属正常布局，不算遮挡
                if is_ancestor(f, e) or is_ancestor(e, f):
                    continue
                area = (fx2 - fx1) * (fy2 - fy1)
                if best_area is None or area < best_area:
                    best_area = area
                    best = f
            if best is not None:
                e['obscured_by'] = best['id']
            e['visible'] = bool(on_screen and best is None)

    @staticmethod
    def build_tree(elements: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """由扁平元素列表构建嵌套树骨架 {id, text, children:[...]}（轻量，供AI判层级）"""
        by_id = {e['id']: e for e in elements}

        def skeleton(e):
            return {
                'id': e['id'],
                'text': e.get('text', ''),
                'children': [skeleton(by_id[cid]) for cid in e.get('children', []) if cid in by_id],
            }

        return [skeleton(e) for e in elements if not e.get('parent_id')]

    def get_scrollable_containers(self) -> List[Dict[str, Any]]:
        """查询当前页面所有可滚动容器（深拷贝）"""
        with self._lock:
            return copy.deepcopy([e for e in self._elements if e.get('scrollable')])

    # ---------- 刷新元素 ----------
    def refresh_from_page_source(self, page_source: str) -> Dict[str, Any]:
        """
        用调用方已获取的 page_source 刷新元素列表（不重复请求设备）。
        供 /api/snapshot 使用：截图与元素树必须来自同一帧页面，
        由调用方保证 page_source 与其截图的时刻相邻。
        """
        with self._lock:
            self._elem_counter = 0
            real_elements = self.parse_page_source(page_source)
            if real_elements:
                self._elements = real_elements
                logger.info(f'[ElementService] 快照刷新完成: {len(self._elements)} 个真实元素')
                return {
                    'success': True,
                    'count': len(self._elements),
                    'elements': copy.deepcopy(self._elements),
                    'tree': self.build_tree(self._elements),
                    'mode': 'real',
                    'message': f'已解析 {len(self._elements)} 个真实元素'
                }
            logger.warning('[ElementService] 快照page_source解析无元素')
            return {
                'success': False,
                'count': 0,
                'elements': [],
                'mode': 'real',
                'message': 'page_source 解析无元素，请重试'
            }

    def refresh_elements(self) -> Dict[str, Any]:
        """
        刷新元素列表。
        优先使用真实 Appium page_source，模拟模式下使用模拟数据。
        线程安全，所有状态变更在锁内完成。
        """
        with self._lock:
            # 重置计数器，避免ID无限增长
            self._elem_counter = 0

            # 检查设备状态（在锁内读取，避免TOCTOU竞态）
            is_real = False
            is_mock = False
            if self._device_service:
                try:
                    is_real = self._device_service.is_real()
                    is_mock = self._device_service.is_mock()
                except Exception:
                    is_real = False
                    is_mock = False

            # 真实设备模式
            if is_real:
                try:
                    page_source = self._device_service.get_page_source()
                except Exception as e:
                    logger.error(f'[ElementService] 获取page_source失败: {e}')
                    page_source = None

                if page_source:
                    real_elements = self.parse_page_source(page_source)
                    if real_elements:
                        self._elements = real_elements
                        logger.info(f'[ElementService] 刷新完成: {len(self._elements)} 个真实元素')
                        return {
                            'success': True,
                            'count': len(self._elements),
                            'elements': copy.deepcopy(self._elements),
                            'tree': self.build_tree(self._elements),
                            'mode': 'real',
                            'message': f'已解析 {len(self._elements)} 个真实元素'
                        }
                    else:
                        logger.warning('[ElementService] page_source解析无元素')
                        return {
                            'success': False,
                            'count': 0,
                            'elements': [],
                            'mode': 'real',
                            'message': 'page_source 解析无元素，请重试'
                        }
                else:
                    return {
                        'success': False,
                        'count': 0,
                        'elements': [],
                        'mode': 'real',
                        'message': '无法获取 page_source：Appium 会话可能繁忙或 UiAutomator2 暂不可用，请稍后重试；若连续失败再重新连接设备'
                    }

            # 模拟模式
            if is_mock:
                # mock元素补齐树形增量字段（全部为顶层可见元素）
                mock = copy.deepcopy(self._mock_elements)
                for m in mock:
                    m.setdefault('parent_id', None)
                    m.setdefault('children', [])
                    m.setdefault('scrollable_ancestor', None)
                    m.setdefault('obscured_by', None)
                    m.setdefault('visible', True)
                self._elements = mock
                # mock元素有固定ID（elem_1~5），counter从5开始
                self._elem_counter = 5
                logger.info(f'[ElementService] 使用模拟数据: {len(self._elements)} 个元素')
                return {
                    'success': True,
                    'count': len(self._elements),
                    'elements': copy.deepcopy(self._elements),
                    'tree': self.build_tree(self._elements),
                    'mode': 'mock',
                    'message': '使用模拟元素数据'
                }

            # 无设备也无模拟模式
            self._elements = []
            return {
                'success': False,
                'count': 0,
                'elements': [],
                'mode': 'disconnected',
                'message': '未连接设备，请先连接设备或启用模拟模式'
            }

    def get_elements(self) -> List[Dict[str, Any]]:
        """获取当前元素列表（深拷贝，防止调用方修改内部状态）"""
        with self._lock:
            return copy.deepcopy(self._elements)

    def get_element_by_id(self, elem_id: str) -> Optional[Dict[str, Any]]:
        """按ID查找元素（返回深拷贝）"""
        with self._lock:
            for elem in self._elements:
                if elem['id'] == elem_id:
                    return copy.deepcopy(elem)
        return None

    def locate_by_coordinate(self, x: int, y: int) -> Optional[Dict[str, Any]]:
        """
        坐标反查：找到包含坐标 (x, y) 的最小面积元素。
        若多个元素包含该点，返回面积最小的（最精确匹配）。
        返回深拷贝。
        """
        with self._lock:
            candidates = []
            for elem in self._elements:
                bounds = elem.get('bounds', [])
                if len(bounds) != 4:
                    continue
                x1, y1, x2, y2 = bounds
                if x1 <= x <= x2 and y1 <= y <= y2:
                    area = (x2 - x1) * (y2 - y1)
                    candidates.append((area, elem))

            if not candidates:
                return None

            candidates.sort(key=lambda c: c[0])
            return copy.deepcopy(candidates[0][1])

    def save_current_snapshot(self, screenshot_path: str = '',
                              screen_width: int = 0, screen_height: int = 0,
                              package_name: str = '', activity_name: str = '',
                              page_name: str = 'current') -> Dict[str, Any]:
        """
        保存当前元素列表为快照（需要注入ElementRepository）

        Returns:
            {'success': bool, 'snapshot_id': int|None, 'message': str}
        """
        with self._lock:
            elements_copy = copy.deepcopy(self._elements)

        if not elements_copy:
            return {'success': False, 'message': '当前无元素数据，无法保存快照'}

        if self._element_repo is None:
            logger.warning('[ElementService] ElementRepository未注入，快照无法持久化到DB')
            return {'success': False, 'message': 'Repository未配置，快照仅保存在内存中'}

        # 获取当前设备ID
        device_id = None
        if self._device_service:
            try:
                mgr = getattr(self._device_service, 'device_manager', None)
                if mgr:
                    # 尝试通过DeviceRepository查找device_id
                    pass  # device_id在Repository内部通过udid查找
            except Exception:
                pass

        try:
            result = self._element_repo.save_snapshot(
                device_id=device_id,
                elements=elements_copy,
                screenshot_path=screenshot_path,
                screen_width=screen_width,
                screen_height=screen_height,
                package_name=package_name,
                activity_name=activity_name,
                page_name=page_name,
            )
            logger.info(f'[ElementService] 快照保存: {result}')
            return result
        except Exception as e:
            logger.error(f'[ElementService] 保存快照异常: {e}', exc_info=True)
            return {'success': False, 'message': f'保存快照异常: {str(e)}'}


# 全局单例
element_service = ElementService()
