"""
设备数据访问层
Phase 3: 接入SQLAlchemy ORM实现真实DB持久化
当database.enabled=False时自动降级为内存模式
"""
import json
from datetime import datetime
from typing import List, Dict, Any, Optional

from backend.utils.logger import get_logger

logger = get_logger(__name__)


class DeviceRepository:
    """设备Repository，管理设备记录和Appium会话"""

    def __init__(self, db=None):
        self._db = db
        self._memory_devices: Dict[str, Dict] = {}  # 内存模式回退
        self._memory_sessions: List[Dict] = []

    @property
    def _has_db(self) -> bool:
        return self._db is not None

    def _get_model(self):
        """延迟导入Device模型"""
        from backend.models.device import Device
        return Device

    def _get_session_model(self):
        from backend.models.appium_session import AppiumSession
        return AppiumSession

    def get_device_by_udid(self, udid: str) -> Optional[Dict]:
        """按UDID查询设备"""
        if not udid:
            return None

        if self._has_db:
            try:
                Model = self._get_model()
                device = Model.query.filter_by(udid=udid).first()
                if device:
                    return self._model_to_dict(device)
            except Exception as e:
                logger.warning(f'[DeviceRepository] 查询设备失败(回退内存): {e}')

        return self._memory_devices.get(udid)

    def save_device(self, device_info: Dict) -> Dict:
        """保存/更新设备信息"""
        udid = device_info.get('udid')
        if not udid:
            return {'success': False, 'message': '设备UDID不能为空'}

        now = datetime.now()

        if self._has_db:
            try:
                Model = self._get_model()
                device = Model.query.filter_by(udid=udid).first()
                if device:
                    # 更新
                    device.name = device_info.get('name', device.name)
                    device.platform = device_info.get('platform', device.platform)
                    device.platform_version = device_info.get('version', device.platform_version)
                    device.model = device_info.get('model', device.model)
                    device.brand = device_info.get('brand', device.brand)
                    device.connect_method = device_info.get('connect_method', device.connect_method)
                    device.ip_port = device_info.get('ip_port', device.ip_port)
                    device.status = 'online'
                    device.is_active = device_info.get('is_active', True)
                    device.is_mock = device_info.get('is_mock', False)
                    device.last_connected_at = now
                    if device_info.get('capabilities'):
                        device.capabilities = json.dumps(device_info['capabilities'], ensure_ascii=False)
                else:
                    # 新建
                    device = Model(
                        udid=udid,
                        name=device_info.get('name', ''),
                        platform=device_info.get('platform', 'Android'),
                        platform_version=device_info.get('version', ''),
                        model=device_info.get('model', ''),
                        brand=device_info.get('brand', ''),
                        connect_method=device_info.get('connect_method', 'usb'),
                        ip_port=device_info.get('ip_port', ''),
                        status='online',
                        is_active=device_info.get('is_active', True),
                        is_mock=device_info.get('is_mock', False),
                        last_connected_at=now,
                        capabilities=json.dumps(device_info.get('capabilities', {}), ensure_ascii=False)
                    )
                    self._db.session.add(device)
                self._db.session.commit()
                return {'success': True, 'message': '设备信息已保存', 'udid': udid}
            except Exception as e:
                logger.warning(f'[DeviceRepository] 保存设备失败(回退内存): {e}')
                try:
                    self._db.session.rollback()
                except Exception:
                    pass

        # 内存模式
        self._memory_devices[udid] = {
            **device_info,
            'status': 'online',
            'last_connected_at': now.isoformat()
        }
        return {'success': True, 'message': '设备信息已记录（内存模式）', 'udid': udid}

    def update_device_status(self, udid: str, status: str) -> bool:
        """更新设备状态（online/offline/error）"""
        if not udid:
            return False

        if self._has_db:
            try:
                Model = self._get_model()
                device = Model.query.filter_by(udid=udid).first()
                if device:
                    device.status = status
                    device.last_heartbeat_at = datetime.now()
                    if status == 'online':
                        device.is_active = True
                    elif status in ('offline', 'error'):
                        device.is_active = False
                    self._db.session.commit()
                    return True
            except Exception as e:
                logger.warning(f'[DeviceRepository] 更新状态失败: {e}')
                try:
                    self._db.session.rollback()
                except Exception:
                    pass

        # 内存模式
        if udid in self._memory_devices:
            self._memory_devices[udid]['status'] = status
            self._memory_devices[udid]['last_heartbeat_at'] = datetime.now().isoformat()
            return True
        return False

    def list_devices(self) -> List[Dict]:
        """列出所有设备"""
        if self._has_db:
            try:
                Model = self._get_model()
                devices = Model.query.order_by(Model.last_connected_at.desc()).all()
                return [self._model_to_dict(d) for d in devices]
            except Exception as e:
                logger.warning(f'[DeviceRepository] 列表查询失败(回退内存): {e}')

        return list(self._memory_devices.values())

    def _get_device_id_by_udid(self, udid: str) -> Optional[int]:
        """通过UDID查找Device的ID（外键）"""
        if not udid or not self._has_db:
            return None
        try:
            Model = self._get_model()
            device = Model.query.filter_by(udid=udid).first()
            return device.id if device else None
        except Exception as e:
            logger.warning(f'[DeviceRepository] 查找device_id失败: {e}')
            return None

    def save_appium_session(self, device_udid: str, session_id: str,
                             capabilities: Dict = None,
                             appium_server_url: str = '') -> Dict:
        """保存Appium会话记录"""
        if not device_udid or not session_id:
            return {'success': False, 'message': 'device_udid和session_id不能为空'}

        now = datetime.now()

        if self._has_db:
            try:
                SessionModel = self._get_session_model()
                device_id = self._get_device_id_by_udid(device_udid)

                # 先关闭该设备的旧active session
                if device_id is not None:
                    old_sessions = SessionModel.query.filter_by(
                        device_id=device_id, status='active'
                    ).all()
                else:
                    # 没有device记录时，按session_id匹配（兼容内存模式）
                    old_sessions = SessionModel.query.filter_by(status='active').all()
                for s in old_sessions:
                    s.closed_at = now
                    s.status = 'replaced'
                    s.close_reason = 'replaced_by_new_session'
                    s.last_heartbeat_at = now

                new_session = SessionModel(
                    device_id=device_id,
                    session_id=session_id,
                    appium_server_url=appium_server_url or '',
                    capabilities_used=json.dumps(capabilities or {}, ensure_ascii=False),
                    status='active',
                    last_heartbeat_at=now,
                )
                self._db.session.add(new_session)
                self._db.session.commit()
                logger.info(f'[DeviceRepository] AppiumSession已保存: {session_id[:20]}...')
                return {'success': True, 'session_id': session_id}
            except Exception as e:
                logger.warning(f'[DeviceRepository] 保存session失败: {e}')
                try:
                    self._db.session.rollback()
                except Exception:
                    pass

        # 内存模式
        self._memory_sessions.append({
            'device_udid': device_udid,
            'session_id': session_id,
            'appium_server_url': appium_server_url or '',
            'capabilities_used': json.dumps(capabilities or {}, ensure_ascii=False),
            'status': 'active',
            'created_at': now.isoformat(),
            'last_heartbeat_at': now.isoformat(),
        })
        return {'success': True, 'session_id': session_id}

    def close_appium_session(self, session_id: str, reason: str = 'normal') -> bool:
        """标记session结束"""
        if not session_id:
            return False

        if self._has_db:
            try:
                SessionModel = self._get_session_model()
                s = SessionModel.query.filter_by(session_id=session_id).first()
                if s:
                    s.closed_at = datetime.now()
                    s.status = 'closed'
                    s.close_reason = reason
                    self._db.session.commit()
                    return True
            except Exception as e:
                logger.warning(f'[DeviceRepository] 关闭session失败: {e}')
                try:
                    self._db.session.rollback()
                except Exception:
                    pass

        # 内存模式
        for ms in self._memory_sessions:
            if ms.get('session_id') == session_id:
                ms['status'] = 'closed'
                ms['closed_at'] = datetime.now().isoformat()
                ms['close_reason'] = reason
                return True
        return False

    def heartbeat_session(self, session_id: str) -> bool:
        """更新会话心跳时间"""
        if not session_id:
            return False

        now = datetime.now()
        if self._has_db:
            try:
                SessionModel = self._get_session_model()
                s = SessionModel.query.filter_by(session_id=session_id, status='active').first()
                if s:
                    s.last_heartbeat_at = now
                    self._db.session.commit()
                    return True
            except Exception as e:
                logger.warning(f'[DeviceRepository] 更新心跳失败: {e}')
                try:
                    self._db.session.rollback()
                except Exception:
                    pass

        for ms in self._memory_sessions:
            if ms.get('session_id') == session_id and ms.get('status') == 'active':
                ms['last_heartbeat_at'] = now.isoformat()
                return True
        return False

    @staticmethod
    def _model_to_dict(device) -> Dict:
        """Device模型转字典"""
        caps = {}
        try:
            if device.capabilities:
                caps = json.loads(device.capabilities)
        except Exception:
            caps = {}
        return {
            'udid': device.udid,
            'name': device.name,
            'platform': device.platform,
            'version': device.platform_version,
            'model': device.model,
            'brand': device.brand,
            'connect_method': device.connect_method,
            'ip_port': device.ip_port,
            'status': device.status,
            'is_active': device.is_active,
            'is_mock': device.is_mock,
            'last_connected_at': device.last_connected_at.isoformat() if device.last_connected_at else None,
            'last_heartbeat_at': device.last_heartbeat_at.isoformat() if device.last_heartbeat_at else None,
            'capabilities': caps,
        }
