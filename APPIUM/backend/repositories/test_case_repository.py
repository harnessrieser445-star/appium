"""
测试用例数据访问层
隔离ScriptDesignService与数据库Model，提供JSON文件和SQLite双存储支持
"""
import json
import os
from datetime import datetime
from typing import List, Dict, Any, Optional

from backend.utils.logger import get_logger

logger = get_logger(__name__)


class TestCaseRepository:
    """
    测试用例Repository。
    支持两种存储后端：
    - json: 旧的JSON文件存储（db=None时使用）
    - db: SQLite数据库存储（db传入时使用，JSON同时写入作为备份）
    """

    def __init__(self, test_cases_dir: Optional[str] = None, db=None):
        """
        Args:
            test_cases_dir: JSON用例目录，默认使用PathManager的TEST_CASES_DIR
            db: SQLAlchemy db实例，None则仅使用JSON存储
        """
        if test_cases_dir is None:
            from backend.utils.paths import TEST_CASES_DIR
            test_cases_dir = str(TEST_CASES_DIR)
        self._test_cases_dir = test_cases_dir
        self._db = db
        os.makedirs(self._test_cases_dir, exist_ok=True)

    def _is_db_enabled(self) -> bool:
        """检查是否启用数据库存储（db实例传入即启用）"""
        return self._db is not None

    # ==================== JSON文件操作（旧路径） ====================

    def _json_path(self, name: str) -> str:
        """获取JSON文件路径"""
        safe_name = ''.join(c for c in name if c.isalnum() or c in ('_', '-'))
        return os.path.join(self._test_cases_dir, f'{safe_name}.json')

    def _read_json(self, name: str) -> Optional[Dict]:
        """读取JSON用例文件"""
        filepath = self._json_path(name)
        if not os.path.exists(filepath):
            return None
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return None

    def _write_json(self, name: str, data: Dict) -> bool:
        """写入JSON用例文件"""
        filepath = self._json_path(name)
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False

    def _list_json_cases(self) -> List[Dict]:
        """列出所有JSON用例"""
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
                            'elements': data.get('elements', []),
                            'steps': data.get('steps', []),
                            'element_count': len(data.get('elements', [])),
                            'step_count': len(data.get('steps', []))
                        })
                    except Exception:
                        continue
        return cases

    # ==================== DB操作（新路径） ====================

    def _get_default_app_id(self) -> Optional[int]:
        """获取默认APP ID"""
        from backend.models.app import App
        app = App.query.filter_by(package_name='default').first()
        return app.id if app else None

    def _db_save_case(self, name: str, elements: List[Dict], steps: List[Dict]) -> Dict:
        """保存用例到数据库"""
        from backend.models.test_case import TestCase, TestStep
        db = self._db

        safe_name = ''.join(c for c in name if c.isalnum() or c in ('_', '-'))
        if not safe_name:
            return {'success': False, 'message': '用例名称无效'}

        try:
            # 检查是否已存在
            existing = TestCase.query.filter_by(name=safe_name).first()
            if existing:
                # 删除旧步骤，重新写入
                TestStep.query.filter_by(case_id=existing.id).delete()
                existing.step_count = len(steps)
                existing.updated_at = datetime.now()
                case = existing
            else:
                # 创建新用例
                case = TestCase(
                    app_id=self._get_default_app_id(),
                    name=safe_name,
                    step_count=len(steps),
                    created_at=datetime.now()
                )
                db.session.add(case)
                db.session.flush()

            # 创建步骤
            for step_data in steps:
                elem = step_data.get('element')
                step = TestStep(
                    case_id=case.id,
                    step_order=step_data.get('step_order', 1),
                    action=step_data.get('action', ''),
                    action_params=json.dumps(step_data.get('action_params', {}), ensure_ascii=False),
                    description=step_data.get('description', ''),
                    elem_snapshot_data=json.dumps(elem, ensure_ascii=False) if elem else None,
                    timeout=30,
                    retry_count=1,
                    is_enabled=True,
                    created_at=datetime.now()
                )
                db.session.add(step)

            db.session.commit()
            return {'success': True, 'message': f'用例已保存到DB: {safe_name}'}
        except Exception as e:
            db.session.rollback()
            return {'success': False, 'message': f'DB保存失败: {str(e)}'}

    def _db_load_case(self, name: str) -> Optional[Dict]:
        """从数据库加载用例"""
        from backend.models.test_case import TestCase
        safe_name = ''.join(c for c in name if c.isalnum() or c in ('_', '-'))
        case = TestCase.query.filter_by(name=safe_name).first()
        if not case:
            return None

        elements = []
        steps = []
        for s in case.steps:
            step_dict = {
                'step_id': f'step_{s.id}',
                'step_order': s.step_order,
                'element': json.loads(s.elem_snapshot_data) if s.elem_snapshot_data else None,
                'action': s.action,
                'action_params': json.loads(s.action_params) if s.action_params else {},
                'description': s.description or '',
                'created_at': s.created_at.strftime('%Y-%m-%d %H:%M:%S') if s.created_at else ''
            }
            steps.append(step_dict)
            if step_dict['element'] and step_dict['element'] not in elements:
                elements.append(step_dict['element'])

        return {
            'name': case.name,
            'saved_at': case.created_at.strftime('%Y-%m-%d %H:%M:%S') if case.created_at else '',
            'elements': elements,
            'steps': steps,
            'element_count': len(elements),
            'step_count': len(steps)
        }

    def _db_list_cases(self) -> List[Dict]:
        """列出数据库中所有用例"""
        from backend.models.test_case import TestCase
        cases = TestCase.query.order_by(TestCase.created_at.desc()).all()
        result = []
        for c in cases:
            result.append({
                'name': c.name,
                'saved_at': c.created_at.strftime('%Y-%m-%d %H:%M:%S') if c.created_at else '',
                'element_count': c.step_count,
                'step_count': c.step_count
            })
        return result

    # ==================== 公共接口 ====================

    def save_case(self, name: str, elements: List[Dict], steps: List[Dict]) -> Dict:
        """保存用例（根据Feature Flag选择存储后端）"""
        safe_name = ''.join(c for c in name if c.isalnum() or c in ('_', '-'))
        if not safe_name:
            return {'success': False, 'message': '用例名称无效'}

        data = {
            'name': safe_name,
            'saved_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'elements': list(elements),
            'steps': list(steps)
        }

        # JSON始终写入（作为备份）
        json_ok = self._write_json(safe_name, data)

        if self._is_db_enabled():
            db_result = self._db_save_case(safe_name, elements, steps)
            if not db_result['success']:
                return db_result
            return {'success': True, 'filepath': self._json_path(safe_name), 'message': db_result['message']}

        if json_ok:
            return {'success': True, 'filepath': self._json_path(safe_name), 'message': f'用例已保存: {safe_name}.json'}
        return {'success': False, 'message': '保存失败'}

    def load_case(self, name: str) -> Dict:
        """加载用例（优先DB，其次JSON）"""
        safe_name = ''.join(c for c in name if c.isalnum() or c in ('_', '-'))
        if not safe_name:
            return {'success': False, 'message': '用例名称无效'}

        data = None
        if self._is_db_enabled():
            data = self._db_load_case(safe_name)

        if data is None:
            data = self._read_json(safe_name)

        if data is None:
            return {'success': False, 'message': f'用例文件不存在: {safe_name}.json'}

        return {
            'success': True,
            'design': {
                'elements': data.get('elements', []),
                'steps': data.get('steps', []),
                'element_count': len(data.get('elements', [])),
                'step_count': len(data.get('steps', []))
            },
            'message': f'用例已加载: {safe_name}.json'
        }

    def list_cases(self) -> Dict:
        """列出所有用例（DB+JSON合并去重）"""
        cases = []
        seen_names = set()

        # DB优先
        if self._is_db_enabled():
            for c in self._db_list_cases():
                cases.append(c)
                seen_names.add(c['name'])

        # JSON补充（DB中没有的）
        for c in self._list_json_cases():
            if c['name'] not in seen_names:
                cases.append(c)
                seen_names.add(c['name'])

        return {'success': True, 'count': len(cases), 'cases': cases}

    def delete_case(self, name: str) -> Dict:
        """
        删除测试用例（SQLite + JSON 双删，幂等）。
        - DB启用时：删除 TestCase 行，ORM cascade='all, delete-orphan' 自动级联删 TestStep；
        - JSON文件：若存在则删除，不存在视为成功（幂等）；
        - 任一存储缺失不阻断另一边，最终在 message 中汇总。
        """
        safe_name = ''.join(c for c in name if c.isalnum() or c in ('_', '-'))
        if not safe_name:
            return {'success': False, 'message': '用例名称无效'}

        messages = []

        # 1. DB删除（若启用）：ORM级联自动删 test_steps
        if self._is_db_enabled():
            try:
                from backend.models.test_case import TestCase
                case = TestCase.query.filter_by(name=safe_name).first()
                if case:
                    db = self._db
                    db.session.delete(case)  # 级联删 TestStep
                    db.session.commit()
                    messages.append('DB记录已删除')
                else:
                    messages.append('DB无记录')
            except Exception as e:
                # 外键约束可能因 scripts/executions 关联失败
                self._db.session.rollback()
                logger.error(f'[TestCaseRepo] DB删除失败: {e}', exc_info=True)
                messages.append(f'DB删除失败: {e}')

        # 2. JSON文件删除（无论DB是否启用都执行）
        filepath = self._json_path(safe_name)
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
                messages.append('JSON文件已删除')
            else:
                messages.append('JSON文件不存在')
        except Exception as e:
            logger.error(f'[TestCaseRepo] JSON删除失败: {e}', exc_info=True)
            messages.append(f'JSON删除失败: {e}')

        return {
            'success': True,
            'message': f'用例 {safe_name} 删除完成: ' + ' | '.join(messages)
        }
