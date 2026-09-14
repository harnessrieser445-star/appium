"""
元素数据访问层
管理元素快照和元素地图，支持DB持久化和内存模式回退
"""
import json
from datetime import datetime
from typing import List, Dict, Any, Optional

from backend.utils.logger import get_logger

logger = get_logger(__name__)


class ElementRepository:
    """元素Repository，管理元素快照和元素地图"""

    def __init__(self, db=None):
        self._db = db
        # 内存模式回退存储
        self._memory_snapshots: List[Dict] = []
        self._memory_elements: List[Dict] = []
        self._memory_element_maps: List[Dict] = []
        self._snapshot_counter = 0

    @property
    def _has_db(self) -> bool:
        return self._db is not None

    def _get_snapshot_model(self):
        from backend.models.element_snapshot import ElementSnapshot
        return ElementSnapshot

    def _get_element_model(self):
        from backend.models.element import Element
        return Element

    # ==================== 元素快照操作 ====================

    def save_snapshot(self, device_id: Optional[int], elements: List[Dict],
                      screenshot_path: str = '', screen_width: int = 0,
                      screen_height: int = 0, package_name: str = '',
                      activity_name: str = '', page_name: str = 'current') -> Dict:
        """
        保存元素快照

        Args:
            device_id: 设备ID（外键）
            elements: 元素列表（每个元素是dict）
            screenshot_path: 截图文件路径
            screen_width: 屏幕宽度
            screen_height: 屏幕高度
            package_name: 当前包名
            activity_name: 当前Activity名
            page_name: 页面名称

        Returns:
            {'success': bool, 'snapshot_id': int|None, 'element_count': int}
        """
        now = datetime.now()
        element_count = len(elements)

        if self._has_db:
            try:
                SnapshotModel = self._get_snapshot_model()
                ElementModel = self._get_element_model()

                # 创建快照记录
                snapshot = SnapshotModel(
                    device_id=device_id,
                    page_name=page_name,
                    package_name=package_name,
                    activity_name=activity_name,
                    screenshot_path=screenshot_path,
                    element_count=element_count,
                    screen_width=screen_width,
                    screen_height=screen_height,
                )
                self._db.session.add(snapshot)
                self._db.session.flush()  # 获取snapshot.id

                # 批量创建元素记录
                for idx, elem in enumerate(elements):
                    bounds = elem.get('bounds', [0, 0, 0, 0])
                    x1, y1, x2, y2 = (bounds + [0, 0, 0, 0])[:4] if isinstance(bounds, list) else (0, 0, 0, 0)

                    db_elem = ElementModel(
                        snapshot_id=snapshot.id,
                        tag=elem.get('tag', elem.get('class', '')),
                        text=elem.get('text', ''),
                        content_desc=elem.get('content_desc', elem.get('content-desc', '')),
                        resource_id=elem.get('resource_id', elem.get('resource-id', '')),
                        xpath=elem.get('xpath', ''),
                        x1=int(x1) if x1 else 0,
                        y1=int(y1) if y1 else 0,
                        x2=int(x2) if x2 else 0,
                        y2=int(y2) if y2 else 0,
                        class_name=elem.get('class', elem.get('tag', '')),
                        package_name=elem.get('package', package_name),
                        clickable=bool(elem.get('clickable', False)),
                        enabled=bool(elem.get('enabled', True)),
                        focusable=bool(elem.get('focusable', False)),
                        scrollable=bool(elem.get('scrollable', False)),
                        checked=bool(elem.get('checked', False)),
                        bounds_hash=f"{x1}_{y1}_{x2}_{y2}",
                    )
                    self._db.session.add(db_elem)

                self._db.session.commit()
                logger.info(f'[ElementRepository] 快照已保存: id={snapshot.id}, 元素数={element_count}')
                return {
                    'success': True,
                    'snapshot_id': snapshot.id,
                    'element_count': element_count,
                    'message': f'快照已保存({element_count}个元素)'
                }
            except Exception as e:
                logger.warning(f'[ElementRepository] 保存快照失败(回退内存): {e}')
                try:
                    self._db.session.rollback()
                except Exception:
                    pass

        # 内存模式
        self._snapshot_counter += 1
        snapshot_id = self._snapshot_counter
        snapshot_data = {
            'id': snapshot_id,
            'device_id': device_id,
            'page_name': page_name,
            'package_name': package_name,
            'activity_name': activity_name,
            'screenshot_path': screenshot_path,
            'element_count': element_count,
            'screen_width': screen_width,
            'screen_height': screen_height,
            'elements': list(elements),
            'created_at': now.isoformat(),
        }
        self._memory_snapshots.append(snapshot_data)
        # 只保留最近10个快照
        if len(self._memory_snapshots) > 10:
            self._memory_snapshots = self._memory_snapshots[-10:]

        return {
            'success': True,
            'snapshot_id': snapshot_id,
            'element_count': element_count,
            'message': f'快照已保存(内存模式, {element_count}个元素)'
        }

    def get_latest_snapshot(self) -> Optional[Dict]:
        """获取最新快照（包含元素列表）"""
        if self._has_db:
            try:
                SnapshotModel = self._get_snapshot_model()
                snapshot = SnapshotModel.query.order_by(
                    SnapshotModel.created_at.desc()
                ).first()
                if snapshot:
                    return self._snapshot_to_dict(snapshot, include_elements=True)
            except Exception as e:
                logger.warning(f'[ElementRepository] 查询最新快照失败: {e}')

        # 内存模式
        if self._memory_snapshots:
            return dict(self._memory_snapshots[-1])
        return None

    def get_snapshot(self, snapshot_id: int) -> Optional[Dict]:
        """按ID获取快照"""
        if self._has_db:
            try:
                SnapshotModel = self._get_snapshot_model()
                snapshot = SnapshotModel.query.get(snapshot_id)
                if snapshot:
                    return self._snapshot_to_dict(snapshot, include_elements=True)
            except Exception as e:
                logger.warning(f'[ElementRepository] 查询快照失败: {e}')

        for s in self._memory_snapshots:
            if s.get('id') == snapshot_id:
                return dict(s)
        return None

    def list_snapshots(self, limit: int = 20) -> List[Dict]:
        """列出快照（不含元素详情）"""
        result = []

        if self._has_db:
            try:
                SnapshotModel = self._get_snapshot_model()
                snapshots = SnapshotModel.query.order_by(
                    SnapshotModel.created_at.desc()
                ).limit(limit).all()
                for s in snapshots:
                    result.append(self._snapshot_to_dict(s, include_elements=False))
                return result
            except Exception as e:
                logger.warning(f'[ElementRepository] 列表查询失败: {e}')

        for s in reversed(self._memory_snapshots[-limit:]):
            snap_dict = {k: v for k, v in s.items() if k != 'elements'}
            result.append(snap_dict)
        return result

    def delete_snapshot(self, snapshot_id: int) -> bool:
        """删除快照"""
        if self._has_db:
            try:
                SnapshotModel = self._get_snapshot_model()
                snapshot = SnapshotModel.query.get(snapshot_id)
                if snapshot:
                    self._db.session.delete(snapshot)
                    self._db.session.commit()
                    return True
            except Exception as e:
                logger.warning(f'[ElementRepository] 删除快照失败: {e}')
                try:
                    self._db.session.rollback()
                except Exception:
                    pass

        self._memory_snapshots = [s for s in self._memory_snapshots if s.get('id') != snapshot_id]
        return True

    # ==================== 元素地图操作（命名保存的定位器） ====================

    def save_element_map(self, name: str, xpath: str, **kwargs) -> Dict:
        """保存元素到元素地图（命名定位器）"""
        if not name:
            return {'success': False, 'message': '元素名称不能为空'}

        now = datetime.now()
        map_data = {
            'name': name,
            'xpath': xpath,
            'resource_id': kwargs.get('resource_id', ''),
            'content_desc': kwargs.get('content_desc', ''),
            'tag': kwargs.get('tag', ''),
            'description': kwargs.get('description', ''),
            'created_at': now.isoformat(),
        }

        if self._has_db:
            try:
                from backend.models.element_map import ElementMap
                existing = ElementMap.query.filter_by(name=name).first()
                if existing:
                    existing.xpath = xpath
                    existing.resource_id = kwargs.get('resource_id', existing.resource_id)
                    existing.content_desc = kwargs.get('content_desc', existing.content_desc)
                    existing.updated_at = now
                else:
                    em = ElementMap(
                        name=name,
                        xpath=xpath,
                        resource_id=kwargs.get('resource_id', ''),
                        content_desc=kwargs.get('content_desc', ''),
                        tag=kwargs.get('tag', ''),
                    )
                    self._db.session.add(em)
                self._db.session.commit()
                return {'success': True, 'message': f'元素地图已保存: {name}'}
            except Exception as e:
                logger.warning(f'[ElementRepository] 保存元素地图失败(回退内存): {e}')
                try:
                    self._db.session.rollback()
                except Exception:
                    pass

        # 内存模式
        for i, em in enumerate(self._memory_element_maps):
            if em.get('name') == name:
                self._memory_element_maps[i] = map_data
                return {'success': True, 'message': f'元素地图已更新(内存): {name}'}
        self._memory_element_maps.append(map_data)
        return {'success': True, 'message': f'元素地图已保存(内存): {name}'}

    def list_element_maps(self) -> List[Dict]:
        """列出所有元素地图"""
        result = []

        if self._has_db:
            try:
                from backend.models.element_map import ElementMap
                maps = ElementMap.query.order_by(ElementMap.created_at.desc()).all()
                for m in maps:
                    result.append({
                        'id': m.id,
                        'name': m.name,
                        'xpath': m.xpath,
                        'resource_id': m.resource_id,
                        'content_desc': m.content_desc,
                        'tag': m.tag,
                        'created_at': m.created_at.strftime('%Y-%m-%d %H:%M:%S') if m.created_at else '',
                    })
                return result
            except Exception as e:
                logger.warning(f'[ElementRepository] 查询元素地图失败: {e}')

        return [dict(m) for m in self._memory_element_maps]

    def delete_element_map(self, name: str) -> bool:
        """删除元素地图"""
        if self._has_db:
            try:
                from backend.models.element_map import ElementMap
                m = ElementMap.query.filter_by(name=name).first()
                if m:
                    self._db.session.delete(m)
                    self._db.session.commit()
                    return True
            except Exception as e:
                logger.warning(f'[ElementRepository] 删除元素地图失败: {e}')
                try:
                    self._db.session.rollback()
                except Exception:
                    pass

        self._memory_element_maps = [m for m in self._memory_element_maps if m.get('name') != name]
        return True

    # ==================== 辅助方法 ====================

    @staticmethod
    def _element_to_dict(elem) -> Dict:
        """Element模型转字典"""
        return {
            'id': elem.id,
            'tag': elem.tag,
            'text': elem.text,
            'content_desc': elem.content_desc,
            'resource_id': elem.resource_id,
            'xpath': elem.xpath,
            'bounds': [elem.x1, elem.y1, elem.x2, elem.y2],
            'class': elem.class_name,
            'package_name': elem.package_name,
            'clickable': elem.clickable,
            'enabled': elem.enabled,
            'focusable': elem.focusable,
            'scrollable': elem.scrollable,
            'checked': elem.checked,
        }

    @staticmethod
    def _snapshot_to_dict(snapshot, include_elements: bool = False) -> Dict:
        """ElementSnapshot模型转字典"""
        result = {
            'id': snapshot.id,
            'device_id': snapshot.device_id,
            'page_name': snapshot.page_name,
            'package_name': snapshot.package_name,
            'activity_name': snapshot.activity_name,
            'screenshot_path': snapshot.screenshot_path,
            'element_count': snapshot.element_count,
            'screen_width': snapshot.screen_width,
            'screen_height': snapshot.screen_height,
            'created_at': snapshot.created_at.strftime('%Y-%m-%d %H:%M:%S') if snapshot.created_at else '',
        }
        if include_elements:
            result['elements'] = [
                ElementRepository._element_to_dict(e)
                for e in snapshot.elements.order_by('id').all()
            ]
        return result
