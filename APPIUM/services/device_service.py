"""
Device Service - Facade层
Phase 2修复：
- 添加logger统一日志
- 添加线程锁保护connect/disconnect等状态变更操作
- 修复get_adb_info()破坏封装问题
- 删除重复的_load_config()
- 所有方法添加异常保护，返回统一错误格式
"""

import threading
from typing import Optional, Dict, Any

from backend.utils.logger import get_logger
from backend.device_manager.manager import DeviceManager

logger = get_logger(__name__)


class DeviceService:
    """
    DeviceService Facade

    保持原有API签名不变，内部委托给DeviceManager。
    新增方法：scan_devices() 用于设备扫描API。
    """

    def __init__(self):
        self._mgr = DeviceManager()
        self._lock = threading.RLock()  # 可重入锁保护状态变更操作

    # ---------- 原有公共API（签名和返回格式保持不变） ----------

    def connect(
        self,
        method: str = 'usb',
        device_name: Optional[str] = None,
        pair_code: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        连接设备
        :param method: 'usb' 或 'wifi'
        :param device_name: USB 模式为 udid；WiFi 模式为 ip:port
        :param pair_code: WiFi 模式下的配对码（Android 11+ 无线调试需要）
        """
        with self._lock:
            try:
                if method == 'wifi':
                    result = self._mgr.connect_wifi(device_name, pair_code=pair_code)
                else:
                    result = self._mgr.connect_usb(device_name)
                logger.info(f'[DeviceService] 连接设备: method={method}, result={result.get("success", False)}')
                return result
            except Exception as e:
                logger.error(f'[DeviceService] 连接设备异常: {e}', exc_info=True)
                return {'success': False, 'message': f'连接异常: {str(e)}'}

    def disconnect(self) -> Dict[str, Any]:
        """断开设备"""
        with self._lock:
            try:
                result = self._mgr.disconnect()
                logger.info(f'[DeviceService] 断开设备: {result.get("success", False)}')
                return result
            except Exception as e:
                logger.error(f'[DeviceService] 断开设备异常: {e}', exc_info=True)
                return {'success': False, 'message': f'断开异常: {str(e)}'}

    def enable_mock(self) -> Dict[str, Any]:
        """启用模拟模式（用于无设备时的演示）"""
        with self._lock:
            try:
                result = self._mgr.enable_mock()
                logger.info('[DeviceService] 启用模拟模式')
                return result
            except Exception as e:
                logger.error(f'[DeviceService] 启用模拟模式异常: {e}', exc_info=True)
                return {'success': False, 'message': f'启用模拟模式异常: {str(e)}'}

    def disable_mock(self) -> Dict[str, Any]:
        """禁用模拟模式"""
        with self._lock:
            try:
                result = self._mgr.disable_mock()
                logger.info('[DeviceService] 禁用模拟模式')
                return result
            except Exception as e:
                logger.error(f'[DeviceService] 禁用模拟模式异常: {e}', exc_info=True)
                return {'success': False, 'message': f'禁用模拟模式异常: {str(e)}'}

    def get_status(self) -> Dict[str, Any]:
        """获取设备状态"""
        try:
            return self._mgr.get_status()
        except Exception as e:
            logger.error(f'[DeviceService] 获取状态异常: {e}', exc_info=True)
            return {
                'connected': False,
                'is_mock': False,
                'is_real': False,
                'device_info': {},
                'error': str(e)
            }

    def get_keepalive_status(self) -> Dict[str, Any]:
        """获取保活状态信息"""
        try:
            return self._mgr.get_keepalive_status()
        except Exception as e:
            logger.error(f'[DeviceService] 获取保活状态异常: {e}', exc_info=True)
            return {'error': str(e)}

    def is_connected(self) -> bool:
        """设备是否已连接（线程安全读取）"""
        with self._lock:
            try:
                return self._mgr.is_connected
            except Exception:
                return False

    def is_real(self) -> bool:
        """是否为真实设备"""
        with self._lock:
            try:
                return self._mgr.is_real
            except Exception:
                return False

    def is_mock(self) -> bool:
        """是否为模拟模式"""
        with self._lock:
            try:
                return self._mgr.is_mock
            except Exception:
                return False

    def is_session_usable(self) -> bool:
        """会话是否真实可用（供API层映射SESSION_LOST）"""
        try:
            return self._mgr.is_session_usable()
        except Exception:
            return False

    def take_screenshot(self, save_path: str) -> bool:
        """截图保存到指定路径"""
        try:
            return self._mgr.take_screenshot(save_path)
        except Exception as e:
            logger.error(f'[DeviceService] 截图异常: {e}', exc_info=True)
            return False

    def get_screenshot_bytes(self) -> Optional[bytes]:
        """获取截图PNG字节流（不落盘，供API内存直传）"""
        try:
            return self._mgr.get_screenshot_bytes()
        except Exception as e:
            logger.error(f'[DeviceService] 获取截图字节流异常: {e}', exc_info=True)
            return None

    def get_page_source(self) -> Optional[str]:
        """获取当前页面XML源码"""
        try:
            return self._mgr.get_page_source()
        except Exception as e:
            logger.error(f'[DeviceService] 获取页面源码异常: {e}', exc_info=True)
            return None

    def get_driver(self):
        """获取当前 Appium driver（供 ScriptGenService 执行测试用）"""
        try:
            return self._mgr.get_driver()
        except Exception as e:
            logger.error(f'[DeviceService] 获取driver异常: {e}', exc_info=True)
            return None

    def get_driver_proxy(self):
        """
        获取DriverProxy（推荐使用，包含自动重试和异常恢复）
        与get_driver()不同，此方法返回的是DriverProxy代理对象，
        对StaleElementReferenceException等异常有自动重试能力。
        """
        try:
            return self._mgr.get_driver_proxy()
        except Exception as e:
            logger.error(f'[DeviceService] 获取DriverProxy异常: {e}', exc_info=True)
            return None

    def pause_keepalive(self):
        """暂停心跳保活（测试执行前调用）"""
        try:
            self._mgr.pause_keepalive()
            logger.debug('[DeviceService] 心跳已暂停')
        except Exception as e:
            logger.error(f'[DeviceService] 暂停心跳异常: {e}', exc_info=True)

    def resume_keepalive(self):
        """恢复心跳保活（测试执行后调用）"""
        try:
            self._mgr.resume_keepalive()
            logger.debug('[DeviceService] 心跳已恢复')
        except Exception as e:
            logger.error(f'[DeviceService] 恢复心跳异常: {e}', exc_info=True)

    # ---------- Phase 3 新增API ----------

    def scan_devices(self) -> Dict[str, Any]:
        """扫描USB和WiFi设备（新增）"""
        try:
            return self._mgr.scan_devices()
        except Exception as e:
            logger.error(f'[DeviceService] 扫描设备异常: {e}', exc_info=True)
            return {'success': False, 'message': f'扫描异常: {str(e)}', 'devices': []}

    def get_adb_info(self) -> Dict[str, Any]:
        """获取ADB和Appium Server诊断信息（委托给DeviceManager）"""
        try:
            return self._mgr.get_adb_info()
        except Exception as e:
            logger.warning(f'[DeviceService] 获取ADB诊断信息失败: {e}')
            return {
                'adb_path': 'N/A',
                'adb_version': None,
                'server_running': False,
                'server_url': '',
                'server_pid': None,
                'server_started_by_us': False,
                'connected': False,
                'is_real': False,
                'is_mock': self._mgr.is_mock if hasattr(self._mgr, 'is_mock') else False,
                'current_udid': None,
                'session_lost': False,
            }

    @property
    def device_manager(self) -> DeviceManager:
        """暴露DeviceManager（供内部模块使用，不对外API）"""
        return self._mgr


# 全局单例（保持原有名称，app.py和其他模块的import不受影响）
device_service = DeviceService()
