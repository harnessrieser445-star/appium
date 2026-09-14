"""
Script Design Service - 脚本编排服务
Phase 2修复：
- 添加logger统一日志
- 抽取_step_validation()消除add_step/update_step重复校验
- 修复remove_element()级联删除后step_order不重编号
- 所有对外返回数据使用深拷贝，防止调用方修改内部状态
- 目录路径使用PathManager
- 改善load_case Repository路径逻辑
"""

import os
import json
import copy
import threading
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime

from backend.utils.logger import get_logger

logger = get_logger(__name__)


# 支持的动作类型及其参数定义
SUPPORTED_ACTIONS = {
    'click': {
        'description': '点击元素',
        'params': []
    },
    'input': {
        'description': '输入文本',
        'params': ['value']
    },
    'swipe': {
        'description': '滑动屏幕',
        'params': ['direction']  # up / down / left / right
    },
    'press_hold': {
        'description': '摇杆按住保持（前进/后退/左转/右转）',
        'params': ['direction', 'hold']  # strength 可选（0.1-1.0，默认0.8）
    },
    'wait': {
        'description': '等待',
        'params': ['timeout']  # 秒
    },
    'back': {
        'description': '按返回键',
        'params': []
    },
    'screenshot': {
        'description': '截图',
        'params': []
    },
}


class ScriptDesignService:
    """
    脚本编排服务，管理元素和测试步骤。
    """

    def __init__(self):
        self._elements: List[Dict[str, Any]] = []
        self._steps: List[Dict[str, Any]] = []
        self._lock = threading.RLock()
        self._elem_counter = 0
        self._step_counter = 0

        # 用例JSON保存目录（Repository不使用DB时的fallback）
        from backend.utils.paths import OLD_TEST_CASES_DIR
        self._test_cases_dir = str(OLD_TEST_CASES_DIR)
        os.makedirs(self._test_cases_dir, exist_ok=True)

        # Repository（通过setter注入）
        self._case_repository = None

    def set_case_repository(self, repo):
        """注入TestCaseRepository依赖"""
        self._case_repository = repo
        logger.info('[ScriptDesignService] CaseRepository已注入')

    # ==================== 参数校验（抽取公共方法） ====================

    def _validate_step_params(self, action: str, action_params: Dict[str, Any],
                              element: Optional[Dict[str, Any]]) -> Tuple[bool, str, Dict[str, Any]]:
        """
        校验步骤参数，返回 (is_valid, error_message, normalized_params)

        Returns:
            (True, '', normalized_params) 校验通过
            (False, error_msg, {}) 校验失败
        """
        normalized = dict(action_params) if action_params else {}

        # 校验动作类型
        if action not in SUPPORTED_ACTIONS:
            return False, f'不支持的动作类型: {action}，支持: {", ".join(SUPPORTED_ACTIONS.keys())}', {}

        # 校验必填参数
        required_params = SUPPORTED_ACTIONS[action]['params']
        for param in required_params:
            if param not in normalized:
                return False, f'动作 {action} 缺少必要参数: {param}', {}

        # wait: timeout必须是1-300整数
        if action == 'wait':
            try:
                timeout_val = int(normalized.get('timeout', 3))
            except (ValueError, TypeError):
                return False, 'wait 的 timeout 必须为整数', {}
            if timeout_val < 1 or timeout_val > 300:
                return False, 'wait 的 timeout 须在 1-300 秒之间', {}
            normalized['timeout'] = timeout_val

        # swipe: direction必须是up/down/left/right
        elif action == 'swipe':
            direction = normalized.get('direction', '')
            if direction not in ('up', 'down', 'left', 'right'):
                return False, 'swipe 的 direction 须为 up/down/left/right', {}

        # press_hold: 摇杆方向保持（按下摇杆中心→拖偏→保持hold秒→抬起）
        elif action == 'press_hold':
            direction = normalized.get('direction', '')
            if direction not in ('up', 'down', 'left', 'right'):
                return False, 'press_hold 的 direction 须为 up/down/left/right', {}
            # hold: 保持秒数，0.3-60，支持小数（低于0.3s易被App判为误触）
            try:
                hold_val = float(normalized.get('hold', 0))
            except (ValueError, TypeError):
                return False, 'press_hold 的 hold 必须为数字', {}
            if hold_val < 0.3 or hold_val > 60:
                return False, 'press_hold 的 hold 须在 0.3-60 秒之间', {}
            normalized['hold'] = hold_val
            # strength: 偏转强度，可选，0.1-1.0，默认0.8
            try:
                strength_val = float(normalized.get('strength', 0.8) or 0.8)
            except (ValueError, TypeError):
                return False, 'press_hold 的 strength 必须为数字', {}
            if strength_val < 0.1 or strength_val > 1.0:
                return False, 'press_hold 的 strength 须在 0.1-1.0 之间', {}
            normalized['strength'] = strength_val
            # 坐标来源二选一：显式 center_x/center_y + radius（自绘控件退路），或绑定带 bounds 的元素
            has_explicit_center = ('center_x' in normalized and 'center_y' in normalized)
            if has_explicit_center:
                try:
                    normalized['center_x'] = int(normalized['center_x'])
                    normalized['center_y'] = int(normalized['center_y'])
                    normalized['radius'] = int(normalized.get('radius', 0))
                except (ValueError, TypeError):
                    return False, 'press_hold 的 center_x/center_y/radius 必须为整数坐标', {}
                if normalized['radius'] < 10:
                    return False, '使用 center_x/center_y 时必须提供 radius（摇杆半径像素，>=10）', {}
            else:
                bounds = (element or {}).get('bounds')
                if not bounds or len(bounds) != 4 or list(bounds) == [0, 0, 0, 0]:
                    return False, 'press_hold 必须绑定带有效 bounds 的元素（或提供 center_x/center_y + radius）', {}

        # click/input: 必须有元素
        elif action in ('click', 'input'):
            if not element:
                return False, f'动作 {action} 必须指定目标元素', {}
            if action == 'input' and not str(normalized.get('value', '')):
                return False, 'input 的 value 不能为空', {}

        return True, '', normalized

    def _renumber_steps(self):
        """在锁内重新编号step_order（级联删除/删除/重排后调用）"""
        for i, s in enumerate(self._steps):
            s['step_order'] = i + 1

    def _resolve_element(self, element_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        在锁内解析元素：查找匹配的design元素或自动添加。
        返回内部design元素的引用（非拷贝，调用方在锁内使用）。
        必须在 self._lock 内调用。
        """
        # 标准化key字段
        key = {
            'xpath': element_data.get('xpath', ''),
            'text': element_data.get('text', ''),
            'resource_id': element_data.get('resource_id', ''),
        }

        # 查找已存在的design元素
        for existing in self._elements:
            if (existing.get('xpath') == key['xpath']
                    and existing.get('text') == key['text']
                    and existing.get('resource_id') == key['resource_id']):
                return existing

        # 不存在则自动添加
        self._elem_counter += 1
        new_elem = {
            'tag': element_data.get('tag', ''),
            'resource_id': element_data.get('resource_id', ''),
            'xpath': element_data.get('xpath', ''),
            'bounds': list(element_data.get('bounds', [0, 0, 0, 0])),
            'text': element_data.get('text', ''),
            'content_desc': element_data.get('content_desc', ''),
            'class': element_data.get('class', ''),
            'clickable': bool(element_data.get('clickable', False)),
            'design_elem_id': f'design_elem_{self._elem_counter}',
        }
        self._elements.append(new_elem)
        logger.debug(f'[ScriptDesignService] add_step自动添加元素: {new_elem["design_elem_id"]}')
        return new_elem

    # ==================== 元素管理 ====================

    def add_element(self, element_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        接收元素，保存完整深拷贝副本。
        生成独立的 design_elem_id，与 ElementService 的 elem_id 解耦。
        """
        element = {
            'tag': element_data.get('tag', ''),
            'resource_id': element_data.get('resource_id', ''),
            'xpath': element_data.get('xpath', ''),
            'bounds': list(element_data.get('bounds', [0, 0, 0, 0])),
            'text': element_data.get('text', ''),
            'content_desc': element_data.get('content_desc', ''),
            'class': element_data.get('class', ''),
            'clickable': bool(element_data.get('clickable', False)),
        }

        with self._lock:
            # 去重：xpath+text+resource_id相同视为已存在
            for existing in self._elements:
                if (existing.get('xpath') == element['xpath']
                        and existing.get('text') == element['text']
                        and existing.get('resource_id') == element['resource_id']):
                    return {
                        'success': True,
                        'element': copy.deepcopy(existing),
                        'message': '元素已存在，未重复添加'
                    }

            self._elem_counter += 1
            element['design_elem_id'] = f'design_elem_{self._elem_counter}'
            self._elements.append(element)
            logger.debug(f'[ScriptDesignService] 添加元素: {element["design_elem_id"]}')

        return {
            'success': True,
            'element': copy.deepcopy(element),
            'message': '元素已添加'
        }

    def get_elements(self) -> Dict[str, Any]:
        """获取所有已接收的元素列表（深拷贝）"""
        with self._lock:
            return {
                'success': True,
                'count': len(self._elements),
                'elements': copy.deepcopy(self._elements)
            }

    def remove_element(self, design_elem_id: str) -> Dict[str, Any]:
        """
        移除元素。同时移除引用该元素的步骤，并重新编号step_order。
        """
        with self._lock:
            target = None
            for e in self._elements:
                if e.get('design_elem_id') == design_elem_id:
                    target = e
                    break

            if not target:
                return {'success': False, 'message': f'元素 {design_elem_id} 不存在'}

            self._elements.remove(target)

            # 级联删除引用该元素的步骤
            before_count = len(self._steps)
            self._steps = [
                s for s in self._steps
                if (s.get('element') or {}).get('design_elem_id') != design_elem_id
            ]
            removed_steps = before_count - len(self._steps)

            # 修复：级联删除后重新编号step_order
            self._renumber_steps()

            logger.info(f'[ScriptDesignService] 移除元素 {design_elem_id}, 关联删除{removed_steps}个步骤')

        return {
            'success': True,
            'message': f'元素已移除，关联 {removed_steps} 个步骤已清理',
            'design_elem_id': design_elem_id,
            'removed_steps': removed_steps
        }

    # ==================== 步骤管理 ====================

    def add_step(
        self,
        element: Optional[Dict[str, Any]],
        action: str,
        action_params: Optional[Dict[str, Any]] = None,
        description: str = ''
    ) -> Dict[str, Any]:
        """
        添加一个测试步骤。
        """
        valid, msg, normalized_params = self._validate_step_params(action, action_params, element)
        if not valid:
            return {'success': False, 'message': msg}

        with self._lock:
            self._step_counter += 1

            # 解析元素：自动匹配或添加到design元素列表，确保design_elem_id存在
            resolved_elem = None
            if element:
                resolved_elem = self._resolve_element(element)

            step = {
                'step_id': f'step_{self._step_counter}',
                'step_order': len(self._steps) + 1,
                'element': copy.deepcopy(resolved_elem) if resolved_elem else None,
                'action': action,
                'action_params': normalized_params,
                'description': description,
                'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            self._steps.append(step)
            logger.debug(f'[ScriptDesignService] 添加步骤: {step["step_id"]} action={action}')

        return {
            'success': True,
            'step': copy.deepcopy(step),
            'message': f'步骤已添加 (action={action})'
        }

    def update_step(
        self,
        step_id: str,
        action: Optional[str] = None,
        action_params: Optional[Dict[str, Any]] = None,
        description: Optional[str] = None,
        element: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """修改步骤。只更新传入的非 None 字段。"""
        with self._lock:
            target = None
            for s in self._steps:
                if s['step_id'] == step_id:
                    target = s
                    break

            if not target:
                return {'success': False, 'message': f'步骤 {step_id} 不存在'}

            # 如果传了新动作，校验新动作参数
            if action is not None:
                check_params = action_params if action_params is not None else target.get('action_params', {})
                effective_element = element if element is not None else target.get('element')
                valid, msg, normalized = self._validate_step_params(action, check_params, effective_element)
                if not valid:
                    return {'success': False, 'message': msg}

                target['action'] = action
                if action_params is not None:
                    target['action_params'] = normalized

            if action_params is not None and action is None:
                # 仅更新参数时，用当前action校验新参数
                valid, msg, normalized = self._validate_step_params(
                    target['action'], action_params, target.get('element')
                )
                if not valid:
                    return {'success': False, 'message': msg}
                target['action_params'] = normalized

            if description is not None:
                target['description'] = description

            if element is not None:
                resolved = self._resolve_element(element)
                target['element'] = copy.deepcopy(resolved)

            logger.debug(f'[ScriptDesignService] 更新步骤: {step_id}')

        return {
            'success': True,
            'step': copy.deepcopy(target),
            'message': f'步骤 {step_id} 已更新'
        }

    def delete_step(self, step_id: str) -> Dict[str, Any]:
        """删除步骤"""
        with self._lock:
            target = None
            for s in self._steps:
                if s['step_id'] == step_id:
                    target = s
                    break

            if not target:
                return {'success': False, 'message': f'步骤 {step_id} 不存在'}

            self._steps.remove(target)
            self._renumber_steps()
            logger.info(f'[ScriptDesignService] 删除步骤: {step_id}')

        return {
            'success': True,
            'message': f'步骤 {step_id} 已删除'
        }

    def reorder_steps(self, step_id_list: List[str]) -> Dict[str, Any]:
        """按传入的 step_id 顺序重新排列步骤。"""
        with self._lock:
            step_map = {s['step_id']: s for s in self._steps}

            missing = [sid for sid in step_id_list if sid not in step_map]
            if missing:
                return {
                    'success': False,
                    'message': f'步骤 ID 不存在: {", ".join(missing)}'
                }

            if len(step_id_list) != len(self._steps):
                return {
                    'success': False,
                    'message': f'步骤数量不匹配: 传入 {len(step_id_list)} 个，实际 {len(self._steps)} 个'
                }

            new_steps = []
            for i, sid in enumerate(step_id_list):
                step = step_map[sid]
                step['step_order'] = i + 1
                new_steps.append(step)

            self._steps = new_steps
            logger.info(f'[ScriptDesignService] 步骤重排完成: {len(new_steps)}个步骤')

        return {
            'success': True,
            'steps': copy.deepcopy(self._steps),
            'message': '步骤顺序已更新'
        }

    # ==================== 完整设计 ====================

    def get_design(self) -> Dict[str, Any]:
        """获取完整的测试设计（元素 + 步骤），返回深拷贝。"""
        with self._lock:
            return {
                'success': True,
                'elements': copy.deepcopy(self._elements),
                'steps': copy.deepcopy(self._steps),
                'element_count': len(self._elements),
                'step_count': len(self._steps)
            }

    def clear(self) -> Dict[str, Any]:
        """清空所有元素和步骤"""
        with self._lock:
            self._elements.clear()
            self._steps.clear()
            self._elem_counter = 0
            self._step_counter = 0
        logger.info('[ScriptDesignService] 设计数据已清空')
        return {'success': True, 'message': '已清空所有设计数据'}

    # ==================== 用例持久化 ====================

    @staticmethod
    def _safe_name(name: str) -> str:
        """清理文件名（防止路径遍历）"""
        return ''.join(c for c in name if c.isalnum() or c in ('_', '-'))

    def save_case(self, name: str) -> Dict[str, Any]:
        """保存当前设计为测试用例。"""
        safe_name = self._safe_name(name)
        if not safe_name:
            return {'success': False, 'message': '用例名称无效'}

        with self._lock:
            elements_copy = copy.deepcopy(self._elements)
            steps_copy = copy.deepcopy(self._steps)

        # 优先使用Repository
        if self._case_repository is not None:
            try:
                result = self._case_repository.save_case(safe_name, elements_copy, steps_copy)
                if result.get('success') and 'filepath' not in result:
                    result['filepath'] = os.path.join(self._test_cases_dir, f'{safe_name}.json')
                logger.info(f'[ScriptDesignService] 用例已保存(Repo): {safe_name}')
                return result
            except Exception as e:
                logger.error(f'[ScriptDesignService] Repository保存失败，回退JSON: {e}')
                # fall through到JSON路径

        # 旧路径：直接写JSON
        filepath = os.path.join(self._test_cases_dir, f'{safe_name}.json')
        data = {
            'name': safe_name,
            'saved_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'elements': elements_copy,
            'steps': steps_copy
        }
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info(f'[ScriptDesignService] 用例已保存(JSON): {safe_name}')
        except Exception as e:
            logger.error(f'[ScriptDesignService] 保存JSON失败: {e}', exc_info=True)
            return {'success': False, 'message': f'保存失败: {str(e)}'}

        return {
            'success': True,
            'filepath': filepath,
            'message': f'用例已保存: {safe_name}.json'
        }

    @staticmethod
    def _safe_parse_id(id_str: str) -> int:
        """安全解析 ID 字符串中的数字部分，失败返回 0"""
        try:
            return int(id_str.split('_')[-1])
        except (ValueError, AttributeError, IndexError):
            return 0

    def _restore_counters(self, elements: List[Dict], steps: List[Dict]):
        """从加载的数据恢复计数器（必须在锁内调用）"""
        self._elem_counter = max(
            (self._safe_parse_id(e.get('design_elem_id', '')) for e in elements if isinstance(e, dict)),
            default=0
        )
        self._step_counter = max(
            (self._safe_parse_id(s.get('step_id', '')) for s in steps if isinstance(s, dict)),
            default=0
        )

    def load_case(self, name: str) -> Dict[str, Any]:
        """加载已保存的测试用例。"""
        safe_name = self._safe_name(name)
        if not safe_name:
            return {'success': False, 'message': '用例名称无效'}

        # 优先使用Repository
        design_data = None
        if self._case_repository is not None:
            try:
                result = self._case_repository.load_case(safe_name)
                if result.get('success') and result.get('design'):
                    design_data = result['design']
                elif result.get('success') and not result.get('design'):
                    return {'success': False, 'message': '用例数据为空'}
                # 如果Repository返回失败，继续尝试JSON路径
            except Exception as e:
                logger.error(f'[ScriptDesignService] Repository加载失败: {e}')

        # Repository没有时从JSON加载
        if design_data is None:
            filepath = os.path.join(self._test_cases_dir, f'{safe_name}.json')
            if not os.path.exists(filepath):
                return {'success': False, 'message': f'用例文件不存在: {safe_name}.json'}
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                design_data = {
                    'elements': data.get('elements', []),
                    'steps': data.get('steps', []),
                    'element_count': len(data.get('elements', [])),
                    'step_count': len(data.get('steps', [])),
                }
            except Exception as e:
                logger.error(f'[ScriptDesignService] 加载JSON失败: {e}', exc_info=True)
                return {'success': False, 'message': f'加载失败: {str(e)}'}

        elements = design_data.get('elements', [])
        steps = design_data.get('steps', [])

        with self._lock:
            self._elements = copy.deepcopy(elements)
            self._steps = copy.deepcopy(steps)
            self._restore_counters(self._elements, self._steps)
            # 确保step_order连续
            self._renumber_steps()

        logger.info(f'[ScriptDesignService] 用例已加载: {safe_name} ({len(steps)}步)')

        return {
            'success': True,
            'design': {
                'elements': copy.deepcopy(self._elements),
                'steps': copy.deepcopy(self._steps),
                'element_count': len(self._elements),
                'step_count': len(self._steps)
            },
            'message': f'用例已加载: {safe_name}'
        }

    def list_cases(self) -> Dict[str, Any]:
        """列出所有已保存的测试用例。"""
        if self._case_repository is not None:
            try:
                return self._case_repository.list_cases()
            except Exception as e:
                logger.error(f'[ScriptDesignService] Repository列表查询失败: {e}')

        # 旧路径：遍历JSON目录
        cases = []
        if os.path.isdir(self._test_cases_dir):
            for filename in sorted(os.listdir(self._test_cases_dir)):
                if filename.endswith('.json'):
                    filepath = os.path.join(self._test_cases_dir, filename)
                    try:
                        with open(filepath, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                        cases.append({
                            'name': data.get('name', filename[:-5]),
                            'saved_at': data.get('saved_at', ''),
                            'element_count': len(data.get('elements', [])),
                            'step_count': len(data.get('steps', []))
                        })
                    except Exception:
                        continue

        return {
            'success': True,
            'count': len(cases),
            'cases': cases
        }

    def delete_case(self, name: str) -> Dict[str, Any]:
        """删除已保存的测试用例（Repository双删，fallback直接删JSON）。"""
        safe_name = self._safe_name(name)
        if not safe_name:
            return {'success': False, 'message': '用例名称无效'}

        # 优先使用Repository（SQLite + JSON 双删）
        if self._case_repository is not None:
            try:
                return self._case_repository.delete_case(safe_name)
            except Exception as e:
                logger.error(f'[ScriptDesignService] Repository删除失败: {e}', exc_info=True)
                return {'success': False, 'message': f'删除失败: {str(e)}'}

        # 旧路径：直接删 JSON 文件
        filepath = os.path.join(self._test_cases_dir, f'{safe_name}.json')
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
                return {'success': True, 'message': f'用例已删除: {safe_name}.json'}
            return {'success': True, 'message': f'用例文件不存在: {safe_name}.json'}
        except Exception as e:
            logger.error(f'[ScriptDesignService] JSON删除失败: {e}', exc_info=True)
            return {'success': False, 'message': f'删除失败: {str(e)}'}

    # ==================== 动作类型查询 ====================

    def get_supported_actions(self) -> Dict[str, Any]:
        """返回支持的动作类型及其参数定义"""
        return {
            'success': True,
            'actions': SUPPORTED_ACTIONS
        }


# 全局单例
script_design_service = ScriptDesignService()
