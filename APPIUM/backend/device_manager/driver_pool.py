"""
DriverPool模块
Phase 4: 监听器线程安全、轻量is_alive检测、连接状态查询
"""
import threading
from typing import Optional, Dict, Any, List

from appium.webdriver.webdriver import WebDriver

from backend.utils.logger import get_logger
from backend.device_manager.driver_proxy import DriverProxy

logger = get_logger(__name__)


class DriverEntry:
    """Driver池中单个Driver的条目"""

    def __init__(self, physical_id: str, raw_driver: WebDriver, device_info: Dict[str, Any]):
        self.physical_id = physical_id
        self.raw_driver = raw_driver
        self.proxy = DriverProxy(
            raw_driver,
            max_retries=2,
            retry_delay=0.5,
            on_connection_lost=self._on_connection_lost
        )
        self.device_info = device_info
        self.borrowed = False
        self.borrower: Optional[str] = None
        self.lock = threading.RLock()
        self._pool_ref: Optional['DriverPool'] = None

    def _on_connection_lost(self, error: Exception):
        """连接丢失回调，通知Pool"""
        if self._pool_ref:
            self._pool_ref.notify_connection_lost(self.physical_id, error)

    def borrow(self, borrower: str = 'default') -> bool:
        """借用Driver"""
        with self.lock:
            if self.borrowed:
                return False
            self.borrowed = True
            self.borrower = borrower
            return True

    def release(self):
        """归还Driver"""
        with self.lock:
            self.borrowed = False
            self.borrower = None

    def is_alive(self) -> bool:
        """检查Driver session是否存活（使用proxy的轻量检测）"""
        try:
            return self.proxy.is_session_alive()
        except Exception:
            return False

    def quit(self):
        """安全退出Driver"""
        try:
            if self.raw_driver:
                self.raw_driver.quit()
        except Exception as e:
            logger.debug(f'[DriverPool] quit driver异常(可忽略): {e}')


class DriverPool:
    """
    Driver池

    Phase 4: 单Driver池（一个设备），架构预留多设备扩展
    支持borrow/return模式，异常自动标记
    """

    def __init__(self):
        self._entries: Dict[str, DriverEntry] = {}
        self._lock = threading.RLock()
        self._connection_lost_listeners: List = []
        self._listeners_lock = threading.Lock()  # 专门保护监听器列表

    def add_connection_lost_listener(self, callback):
        """注册连接丢失监听器"""
        with self._listeners_lock:
            self._connection_lost_listeners.append(callback)

    def notify_connection_lost(self, physical_id: str, error: Exception):
        """通知连接丢失（由DriverProxy回调）"""
        logger.warning(f'[DriverPool] Driver {physical_id} 连接丢失: {error}')
        with self._listeners_lock:
            listeners = list(self._connection_lost_listeners)

        for cb in listeners:
            try:
                cb(physical_id, error)
            except Exception as e:
                logger.error(f'[DriverPool] 连接丢失监听器异常: {e}')

    def register(self, physical_id: str, raw_driver: WebDriver, device_info: Dict[str, Any]) -> DriverEntry:
        """
        注册一个Driver到池中

        Args:
            physical_id: 设备物理ID（canonical）
            raw_driver: 原始Appium WebDriver
            device_info: 设备信息

        Returns:
            DriverEntry
        """
        with self._lock:
            if physical_id in self._entries:
                old = self._entries.pop(physical_id)
                old.quit()

            entry = DriverEntry(physical_id, raw_driver, device_info)
            entry._pool_ref = self
            self._entries[physical_id] = entry
            logger.info(f'[DriverPool] 注册Driver: {physical_id}')
            return entry

    def unregister(self, physical_id: str):
        """从池中移除Driver（并quit）"""
        with self._lock:
            entry = self._entries.pop(physical_id, None)
            if entry:
                entry.quit()
                logger.info(f'[DriverPool] 移除Driver: {physical_id}')

    def borrow(self, physical_id: Optional[str] = None, borrower: str = 'default') -> Optional[DriverProxy]:
        """
        借用Driver

        Args:
            physical_id: 设备ID，None则返回第一个可用的
            borrower: 借用者标识

        Returns:
            DriverProxy 或 None
        """
        with self._lock:
            entry = self._get_entry(physical_id)
            if not entry:
                return None
            if entry.borrow(borrower):
                return entry.proxy
            return None

    def release(self, physical_id: Optional[str] = None):
        """归还Driver"""
        with self._lock:
            entry = self._get_entry(physical_id)
            if entry:
                entry.release()

    def get_driver_proxy(self, physical_id: Optional[str] = None) -> Optional[DriverProxy]:
        """获取Driver代理（不标记借用，用于简单查询操作）"""
        with self._lock:
            entry = self._get_entry(physical_id)
            return entry.proxy if entry else None

    def get_raw_driver(self, physical_id: Optional[str] = None) -> Optional[WebDriver]:
        """获取原始driver（兼容旧代码）"""
        with self._lock:
            entry = self._get_entry(physical_id)
            return entry.raw_driver if entry else None

    def has_driver(self, physical_id: Optional[str] = None) -> bool:
        """池中是否有可用Driver"""
        with self._lock:
            entry = self._get_entry(physical_id)
            return entry is not None

    def is_alive(self, physical_id: Optional[str] = None) -> bool:
        """检查Driver是否存活"""
        with self._lock:
            entry = self._get_entry(physical_id)
            if not entry:
                return False
        # is_alive内部调用proxy.is_session_alive()，在锁外执行避免死锁
        return entry.is_alive()

    def get_device_info(self, physical_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """获取设备信息"""
        with self._lock:
            entry = self._get_entry(physical_id)
            return dict(entry.device_info) if entry else None

    def get_active_device_id(self) -> Optional[str]:
        """获取当前活跃的设备ID（Phase 4单设备场景）"""
        with self._lock:
            for pid, entry in self._entries.items():
                return pid
            return None

    def clear_all(self):
        """清空池（断开所有连接）"""
        with self._lock:
            for entry in self._entries.values():
                entry.quit()
            self._entries.clear()
            logger.info('[DriverPool] 已清空所有Driver')

    def replace_driver(self, physical_id: str, new_raw_driver: WebDriver, new_device_info: Dict[str, Any]):
        """替换Driver（重连后调用）"""
        with self._lock:
            old_entry = self._entries.pop(physical_id, None)
            borrowed = False
            borrower_name = 'default'
            if old_entry:
                borrowed = old_entry.borrowed
                borrower_name = old_entry.borrower or 'default'
                old_entry.quit()

            entry = DriverEntry(physical_id, new_raw_driver, new_device_info)
            entry._pool_ref = self
            if borrowed:
                entry.borrow(borrower_name)
            self._entries[physical_id] = entry
            logger.info(f'[DriverPool] Driver已替换: {physical_id}')

    # ---------- 内部 ----------

    def _get_entry(self, physical_id: Optional[str] = None) -> Optional[DriverEntry]:
        if physical_id:
            return self._entries.get(physical_id)
        for entry in self._entries.values():
            return entry
        return None
