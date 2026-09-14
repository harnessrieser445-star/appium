"""
DeviceManager核心模块
Phase 4: 状态锁保护、get_adb_info统一诊断、修复重复ADB连接、心跳优先使用DriverPool Proxy
实现四级异常恢复机制
"""
import time
import threading
from typing import Optional, Dict, Any, Callable
from datetime import datetime

import yaml

from backend.utils.logger import get_logger
from backend.utils.adb import ADB_PATH
from backend.device_manager.adb_client import ADBClient
from backend.device_manager.device_discovery import DeviceDiscovery
from backend.device_manager.driver_pool import DriverPool
from backend.device_manager.udid import normalize_udid
from backend.appium_manager.appium_server import AppiumServer
from backend.appium_manager.capabilities import build_capabilities

from drivers.appium_driver import AppiumDriver

logger = get_logger(__name__)


def _load_config() -> dict:
    """加载config.yaml"""
    import os
    config_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        'config.yaml'
    )
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


class DeviceManager:
    """
    设备管理器

    职责：
    - 管理设备连接（USB/WiFi）
    - 管理Driver生命周期
    - 心跳保活和自动恢复
    - 四级异常恢复机制

    Phase 4修复：
    - 状态变更使用_state_lock保护
    - 添加get_adb_info()统一诊断接口
    - 移除_connect中重复的ADB连接逻辑（由AppiumDriver处理）
    - 心跳优先使用DriverPool Proxy的is_session_alive()
    """

    # 恢复级别
    RECOVERY_LEVEL_NONE = 0
    RECOVERY_LEVEL_SESSION = 1
    RECOVERY_LEVEL_ADB = 2
    RECOVERY_LEVEL_SERVER = 3
    RECOVERY_LEVEL_NOTIFY = 4

    def __init__(self):
        config = _load_config()
        appium_cfg = config.get('appium', {})
        keepalive_cfg = config.get('keepalive', {})

        self._appium_host = appium_cfg.get('host', '127.0.0.1')
        self._appium_port = appium_cfg.get('port', 4723)
        self._new_command_timeout = appium_cfg.get('new_command_timeout', 300)
        self._default_caps_config = appium_cfg.get('default_capabilities', {})

        # 保活配置
        self._keepalive_enabled = keepalive_cfg.get('enabled', True)
        self._keepalive_interval = keepalive_cfg.get('interval', 60)
        self._auto_reconnect = keepalive_cfg.get('auto_reconnect', True)
        self._max_reconnect_attempts = keepalive_cfg.get('max_reconnect_attempts', 3)
        self._reconnect_base_delay = keepalive_cfg.get('reconnect_delay', 5)
        # 探针防抖：连续N次失败才判死（status探针与心跳探针共用计数，避免双重防抖）
        self._probe_fail_threshold = keepalive_cfg.get('probe_fail_threshold', 2)
        # 恢复熔断：累计N轮恢复失败后进 recovery_exhausted 终态，停止自动重试
        self._max_recovery_rounds = keepalive_cfg.get('max_recovery_rounds', 3)

        # 子组件
        self._adb = ADBClient(ADB_PATH)
        self._discovery = DeviceDiscovery(self._adb)
        self._pool = DriverPool()
        self._server = AppiumServer(self._appium_host, self._appium_port, auto_start=True)

        # 状态锁：保护所有连接状态字段的变更
        self._state_lock = threading.RLock()

        # 连接状态
        self._connected = False
        self._is_real = False
        self._mock_mode = False
        self._device_info: Dict[str, Any] = {}
        self._connect_method: Optional[str] = None
        self._current_udid: Optional[str] = None
        self._current_connect_target: Optional[str] = None
        self._current_pair_code: Optional[str] = None

        # 心跳线程
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._heartbeat_stop = threading.Event()
        # 唤醒事件：连接丢失时即时唤醒心跳线程做恢复，避免干等下一个心跳周期
        self._wake_event = threading.Event()

        # 保活状态
        self._last_heartbeat_time: Optional[str] = None
        self._last_heartbeat_ok: bool = True
        self._reconnect_count: int = 0
        self._last_reconnect_time: Optional[str] = None
        self._last_reconnect_ok: bool = False
        self._session_lost: bool = False
        self._recovery_level: int = self.RECOVERY_LEVEL_NONE
        # 断连原因（供AI诊断）：None=正常；连接成功/恢复成功时清除
        self._disconnect_reason: Optional[str] = None
        # 探针防抖计数（probe_session_alive 成功即清零）
        self._probe_fail_count: int = 0
        # 恢复熔断状态：累计失败轮数 / 是否已进入终态（终态后只等显式 connect）
        self._recovery_round_count: int = 0
        self._recovery_exhausted: bool = False

        # AppiumDriver兼容实例
        self._appium_driver: Optional[AppiumDriver] = None

        # 连接丢失回调
        self._connection_lost_callbacks = []
        self._callbacks_lock = threading.Lock()

        # 监听DriverPool的连接丢失事件
        self._pool.add_connection_lost_listener(self._on_pool_connection_lost)

    # ---------- 公共属性（线程安全读取） ----------

    @property
    def is_connected(self) -> bool:
        with self._state_lock:
            return self._connected

    @property
    def is_real(self) -> bool:
        with self._state_lock:
            return self._is_real

    @property
    def is_mock(self) -> bool:
        with self._state_lock:
            return self._mock_mode

    @property
    def device_info(self) -> Dict[str, Any]:
        with self._state_lock:
            return dict(self._device_info)

    @property
    def pool(self) -> DriverPool:
        return self._pool

    @property
    def adb(self) -> ADBClient:
        return self._adb

    @property
    def discovery(self) -> DeviceDiscovery:
        return self._discovery

    @property
    def server(self) -> AppiumServer:
        return self._server

    def add_connection_lost_callback(self, callback: Callable):
        """注册连接丢失回调"""
        with self._callbacks_lock:
            self._connection_lost_callbacks.append(callback)

    def get_adb_info(self) -> Dict[str, Any]:
        """获取ADB和Appium Server诊断信息（供DeviceService调用）"""
        server_info = self._server.get_server_info()
        adb_version = self._adb.get_adb_version()
        with self._state_lock:
            return {
                'adb_path': ADB_PATH,
                'adb_version': adb_version,
                'server_running': server_info['running'],
                'server_url': server_info['url'],
                'server_pid': server_info.get('pid'),
                'server_started_by_us': server_info['started_by_us'],
                'connected': self._connected,
                'is_real': self._is_real,
                'is_mock': self._mock_mode,
                'current_udid': self._current_udid,
                'session_lost': self._session_lost,
            }

    # ---------- 公共API ----------

    def connect_usb(self, udid: Optional[str] = None) -> Dict[str, Any]:
        """USB连接"""
        return self._connect('usb', device_target=udid)

    def connect_wifi(self, ip_port: str, pair_code: Optional[str] = None) -> Dict[str, Any]:
        """WiFi连接"""
        return self._connect('wifi', device_target=ip_port, pair_code=pair_code)

    def disconnect(self) -> Dict[str, Any]:
        """断开连接"""
        self._stop_heartbeat()
        self._pool.clear_all()

        if self._appium_driver:
            try:
                self._appium_driver.disconnect()
            except Exception:
                pass
            self._appium_driver = None

        with self._state_lock:
            self._connected = False
            self._is_real = False
            self._mock_mode = False
            self._device_info = {}
            self._connect_method = None
            self._current_udid = None
            self._current_connect_target = None
            self._current_pair_code = None
            self._session_lost = False
            self._recovery_level = self.RECOVERY_LEVEL_NONE
            self._reconnect_count = 0
            self._disconnect_reason = 'manual_disconnect'
            self._probe_fail_count = 0
            self._recovery_round_count = 0
            self._recovery_exhausted = False

        logger.info('[DeviceManager] 设备已断开')
        return {'success': True, 'message': '设备已断开'}

    def enable_mock(self) -> Dict[str, Any]:
        """启用模拟模式"""
        self._stop_heartbeat()
        self._pool.clear_all()

        if self._appium_driver:
            try:
                self._appium_driver.disconnect()
            except Exception:
                pass
            self._appium_driver = None

        with self._state_lock:
            self._connected = True
            self._is_real = False
            self._mock_mode = True
            self._session_lost = False
            self._recovery_level = self.RECOVERY_LEVEL_NONE
            self._connect_method = 'mock'
            self._device_info = {
                'name': '模拟设备',
                'platform': 'Android',
                'version': '13',
                'udid': 'mock-device',
                'connect_method': 'mock'
            }

        logger.info('[DeviceManager] 已切换至模拟模式')
        return {'success': True, 'message': '已切换至模拟模式'}

    def disable_mock(self) -> Dict[str, Any]:
        """禁用模拟模式"""
        with self._state_lock:
            self._connected = False
            self._mock_mode = False
            self._device_info = {}
            self._connect_method = None
            self._is_real = False
            self._session_lost = False
        logger.info('[DeviceManager] 已退出模拟模式')
        return {'success': True, 'message': '已退出模拟模式'}

    def is_session_usable(self) -> bool:
        """会话是否真实可用（供API层前置判断：元素/快照接口据此映射SESSION_LOST）

        汇总连接态、判死标记与熔断终态为单一布尔——
        API 层不再各自拼凑 _connected/_session_lost，消除判断口径分散。
        """
        with self._state_lock:
            return (self._is_real and self._connected
                    and not self._session_lost
                    and not self._recovery_exhausted)

    def get_status(self) -> Dict[str, Any]:
        with self._state_lock:
            is_real = self._is_real
            should_probe = (is_real and self._connected
                            and not self._session_lost
                            and self._heartbeat_thread is not None
                            and self._heartbeat_thread.is_alive())

        # 存活探针：kill adb 后心跳最长要60s才发现，
        # 这里实时探一次让 status 调用方能立即拿到断连原因（带防抖计数）
        if should_probe and not self.probe_session_alive():
            with self._state_lock:
                # 二次确认（探针耗时期间可能已被心跳标记或恢复）
                if not self._session_lost:
                    self._session_lost = True
                    if not self._disconnect_reason:
                        self._disconnect_reason = 'session_lost:status_probe'
            self._wake_event.set()  # 唤醒心跳线程立即开始恢复

        with self._state_lock:
            status = {
                'connected': self._connected,
                'device': dict(self._device_info) if self._connected else None,
                'mode': 'real' if self._is_real else ('mock' if self._mock_mode else 'disconnected'),
                'disconnect_reason': self._disconnect_reason,
                'session_lost': self._session_lost,
            }
        # 当前页面信息（真实设备且连接时实时查询，失败降级为None不阻塞状态接口）
        status['current_page'] = self.get_current_page() if is_real else None
        return status

    def get_current_page(self) -> Optional[Dict[str, Any]]:
        """获取当前所在页面（package/activity），供AI定位当前状态"""
        with self._state_lock:
            if self._mock_mode or not self._is_real:
                return None
        proxy = self._pool.get_driver_proxy()
        if not proxy:
            return None
        package = None
        activity = None
        try:
            package = proxy.current_package
        except Exception:
            pass
        try:
            activity = proxy.current_activity
        except Exception:
            pass
        if package is None and activity is None:
            return None
        return {'package': package, 'activity': activity}

    def get_keepalive_status(self) -> Dict[str, Any]:
        session_alive = False
        if self._is_real:
            session_alive = self._pool.is_alive()
        with self._state_lock:
            return {
                'enabled': self._keepalive_enabled,
                'interval': self._keepalive_interval,
                'auto_reconnect': self._auto_reconnect,
                'last_heartbeat_time': self._last_heartbeat_time,
                'last_heartbeat_ok': self._last_heartbeat_ok,
                'session_alive': session_alive,
                'session_lost': self._session_lost,
                'recovery_level': self._recovery_level,
                'reconnect_count': self._reconnect_count,
                'last_reconnect_time': self._last_reconnect_time,
                'last_reconnect_ok': self._last_reconnect_ok,
                'new_command_timeout': self._new_command_timeout,
                'probe_fail_count': self._probe_fail_count,
                'probe_fail_threshold': self._probe_fail_threshold,
                'recovery_round_count': self._recovery_round_count,
                'max_recovery_rounds': self._max_recovery_rounds,
                'recovery_exhausted': self._recovery_exhausted,
            }

    def take_screenshot(self, save_path: str) -> bool:
        """截图（优先使用DriverProxy的安全方法）"""
        with self._state_lock:
            if self._mock_mode:
                return False

        proxy = self._pool.get_driver_proxy()
        if proxy:
            return proxy.take_screenshot_safe(save_path)
        if self._appium_driver:
            return self._appium_driver.take_screenshot(save_path)
        return False

    def get_screenshot_bytes(self) -> Optional[bytes]:
        """获取截图PNG字节流（不落盘，避免与HTTP响应读文件产生竞态）"""
        with self._state_lock:
            if self._mock_mode:
                return None

        proxy = self._pool.get_driver_proxy()
        if proxy:
            return proxy.get_screenshot_bytes_safe()
        if self._appium_driver:
            return self._appium_driver.get_screenshot_bytes()
        return None

    def get_page_source(self) -> Optional[str]:
        """获取页面源码"""
        with self._state_lock:
            if self._mock_mode:
                return None

        proxy = self._pool.get_driver_proxy()
        if proxy:
            return proxy.get_page_source_safe()
        if self._appium_driver:
            return self._appium_driver.get_page_source()
        return None

    def get_driver(self):
        """获取原始driver（兼容旧代码）"""
        with self._state_lock:
            if self._mock_mode:
                return None
        raw = self._pool.get_raw_driver()
        if raw:
            return raw
        if self._appium_driver:
            return self._appium_driver.driver
        return None

    def get_driver_proxy(self):
        """获取DriverProxy（新代码优先使用）"""
        with self._state_lock:
            if self._mock_mode:
                return None
        return self._pool.get_driver_proxy()

    def pause_keepalive(self):
        """暂停心跳"""
        self._stop_heartbeat()
        logger.info('[DeviceManager] 心跳已暂停（测试执行中）')

    def resume_keepalive(self):
        """恢复心跳"""
        with self._state_lock:
            should_start = self._is_real and self._keepalive_enabled
        if should_start:
            self._start_heartbeat()
            logger.info('[DeviceManager] 心跳已恢复')

    def scan_devices(self) -> Dict[str, Any]:
        """扫描设备"""
        usb = self._discovery.scan_usb_devices()
        wifi = self._discovery.scan_wifi_devices()
        return {
            'success': True,
            'usb_devices': usb,
            'wifi_devices': wifi,
            'total': len(usb) + len(wifi)
        }

    # ---------- 连接核心逻辑 ----------

    def _connect(self, method: str, device_target: Optional[str] = None,
                 pair_code: Optional[str] = None) -> Dict[str, Any]:
        """统一连接流程"""
        # 停止心跳
        self._stop_heartbeat()

        # 清理旧连接
        self._pool.clear_all()
        if self._appium_driver:
            try:
                self._appium_driver.disconnect()
            except Exception:
                pass
            self._appium_driver = None

        # 1. 确保Appium Server运行
        server_result = self._server.ensure_running(timeout=30)
        if not server_result['success']:
            return {
                'success': False,
                'message': f'Appium Server不可用: {server_result["message"]}'
            }

        # 2. 参数校验
        if method == 'wifi' and not device_target:
            return {'success': False, 'message': 'WiFi 模式需要填写 IP:端口'}

        try:
            # 3. 创建AppiumDriver实例（其内部负责ADB连接和Session创建）
            self._appium_driver = AppiumDriver(
                host=self._appium_host,
                port=self._appium_port,
                new_command_timeout=self._new_command_timeout
            )

            if method == 'wifi':
                result = self._appium_driver.connect_wifi(device_target, pair_code=pair_code)
                udid_to_use = device_target
            else:
                result = self._appium_driver.connect_usb(device_target)
                udid_to_use = device_target

            if not result['success']:
                self._appium_driver = None
                with self._state_lock:
                    self._current_udid = None
                    self._current_connect_target = None
                return {
                    'success': False,
                    'message': f'设备连接失败: {result.get("message", "未知错误")}'
                }

            # 4. 解析物理ID
            raw_driver = self._appium_driver.driver
            device_info = result.get('device', {})
            actual_udid = device_info.get('udid', udid_to_use)
            physical_id = normalize_udid(actual_udid) if actual_udid else (udid_to_use or 'unknown')
            device_info['connect_method'] = method

            with self._state_lock:
                self._current_udid = physical_id
                self._current_connect_target = device_target if method == 'wifi' else udid_to_use
                self._current_pair_code = pair_code
                self._connect_method = method
                self._connected = True
                self._is_real = True
                self._mock_mode = False
                self._device_info = device_info
                self._session_lost = False
                self._recovery_level = self.RECOVERY_LEVEL_NONE
                self._reconnect_count = 0
                self._disconnect_reason = None
                # 显式 connect 成功：探针/熔断状态全清零（含 recovery_exhausted 终态）
                self._probe_fail_count = 0
                self._recovery_round_count = 0
                self._recovery_exhausted = False

            # 5. 注册到DriverPool
            self._pool.register(physical_id, raw_driver, device_info)

            # 6. 启动心跳
            self._start_heartbeat()

            logger.info(f'[DeviceManager] 连接成功: method={method}, udid={physical_id}')
            return {
                'success': True,
                'message': f'Appium 连接成功 ({method.upper()})',
                'device': device_info,
                'mode': 'real'
            }

        except Exception as e:
            logger.error(f'[DeviceManager] 连接异常: {e}', exc_info=True)
            self._appium_driver = None
            with self._state_lock:
                self._connected = False
                self._is_real = False
            return {
                'success': False,
                'message': f'连接异常: {str(e)}'
            }

    # ---------- 心跳与恢复 ----------

    def probe_session_alive(self) -> bool:
        """共享探针（防抖）：连续 threshold 次失败才判死，成功即清零。

        status 探针与心跳探针必须共用此计数——两处探的是同一个会话，
        各自独立计数等于双重防抖（阈值实际翻倍）。
        未达阈值的失败视为抖动容忍，返回 True（不触发判死/恢复）。
        """
        alive = self._pool.is_alive()
        with self._state_lock:
            if alive:
                if self._probe_fail_count:
                    logger.info(f'[DeviceManager] 探针恢复成功，失败计数清零（此前 {self._probe_fail_count} 次）')
                self._probe_fail_count = 0
                return True
            self._probe_fail_count += 1
            if self._probe_fail_count < self._probe_fail_threshold:
                logger.info(f'[DeviceManager] 探针失败 {self._probe_fail_count}/{self._probe_fail_threshold}，'
                            f'未达判死阈值，按抖动容忍')
                return True
            logger.warning(f'[DeviceManager] 探针连续失败 {self._probe_fail_count} 次，判定会话死亡')
            return False

    def _start_heartbeat(self):
        if not self._keepalive_enabled:
            return
        self._heartbeat_stop.clear()
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            return  # 已在运行
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            daemon=True,
            name='device-mgr-keepalive'
        )
        self._heartbeat_thread.start()
        logger.info(f'[DeviceManager] 心跳已启动 (间隔={self._keepalive_interval}s)')

    def _stop_heartbeat(self):
        self._heartbeat_stop.set()
        self._wake_event.set()  # 唤醒等待中的心跳线程使其能立刻检查stop标志退出
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            self._heartbeat_thread.join(timeout=5)
        self._heartbeat_thread = None

    def _heartbeat_loop(self):
        """心跳循环"""
        while not self._heartbeat_stop.is_set():
            # 等待下一个心跳周期；连接丢失回调可通过_wake_event即时唤醒做恢复
            self._wake_event.wait(timeout=self._keepalive_interval)
            self._wake_event.clear()
            if self._heartbeat_stop.is_set():
                break

            with self._state_lock:
                is_real = self._is_real
                is_mock = self._mock_mode

            if not is_real or is_mock:
                continue

            # 1. 发送心跳（优先使用DriverPool Proxy）
            ok = self._do_heartbeat()
            self._last_heartbeat_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            self._last_heartbeat_ok = ok

            if ok:
                with self._state_lock:
                    self._recovery_level = self.RECOVERY_LEVEL_NONE
                    self._session_lost = False
                continue

            # 2. 心跳失败，尝试恢复
            logger.warning('[DeviceManager] 心跳失败，启动恢复机制')

            with self._state_lock:
                auto_reconnect = self._auto_reconnect
                recovery_exhausted = self._recovery_exhausted
                # 失败瞬间就写入原因（此前要等到恢复全部耗尽才有值，
                # 导致断连窗口期 status.disconnect_reason 为 null）
                if not self._disconnect_reason:
                    self._disconnect_reason = 'heartbeat_failed:detected'
                self._session_lost = True

            if recovery_exhausted:
                # 熔断终态：不再自动恢复，保持状态等人工/客户端显式 connect
                logger.warning('[DeviceManager] 已处于 recovery_exhausted 终态，'
                               '跳过自动恢复，等待显式 connect')
                continue

            if not auto_reconnect:
                with self._state_lock:
                    self._session_lost = True
                    self._connected = False
                    self._disconnect_reason = 'heartbeat_failed:auto_reconnect_disabled'
                self._notify_connection_lost('自动重连已禁用')
                continue

            recovered = self._do_progressive_recovery()
            if recovered:
                with self._state_lock:
                    self._session_lost = False
                    self._connected = True
                    self._recovery_level = self.RECOVERY_LEVEL_NONE
                    self._disconnect_reason = None
                    self._recovery_round_count = 0
                logger.info('[DeviceManager] 恢复成功')
            else:
                with self._state_lock:
                    self._session_lost = True
                    self._connected = False
                    self._recovery_level = self.RECOVERY_LEVEL_NOTIFY
                    self._recovery_round_count += 1
                    if self._recovery_round_count >= self._max_recovery_rounds:
                        # 熔断终态：停止无限重试，等人工/客户端显式 connect
                        self._recovery_exhausted = True
                        self._disconnect_reason = 'recovery_exhausted'
                        logger.error(f'[DeviceManager] 恢复连续失败 {self._recovery_round_count} 轮，'
                                     f'进入 recovery_exhausted 终态，停止自动重试')
                        self._notify_connection_lost('恢复已达上限(recovery_exhausted)，请显式重连')
                    else:
                        self._disconnect_reason = 'recovery_failed:all_strategies_exhausted'
                        logger.error(f'[DeviceManager] 第 {self._recovery_round_count}/{self._max_recovery_rounds} 轮恢复失败')
                        self._notify_connection_lost('所有恢复策略均失败')

    def _do_heartbeat(self) -> bool:
        """执行心跳检测（优先DriverPool共享探针带防抖，fallback到AppiumDriver）"""
        try:
            # 优先使用共享探针（与status探针共用防抖计数）
            if self._pool.has_driver():
                return self.probe_session_alive()
            # Fallback到AppiumDriver
            if self._appium_driver:
                return self._appium_driver.keepalive()
            return False
        except Exception as e:
            logger.warning(f'[DeviceManager] 心跳异常: {e}')
            return False

    def _do_progressive_recovery(self) -> bool:
        """四级递进恢复机制"""
        delays = [
            self._reconnect_base_delay,
            self._reconnect_base_delay * 2,
            self._reconnect_base_delay * 4,
        ]

        for attempt in range(self._max_reconnect_attempts):
            if self._heartbeat_stop.is_set():
                return False

            self._reconnect_count += 1
            self._last_reconnect_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            delay = delays[min(attempt, len(delays) - 1)]

            logger.info(f'[DeviceManager] 恢复尝试 {attempt + 1}/{self._max_reconnect_attempts}，'
                        f'延迟{delay}s...')

            if self._heartbeat_stop.wait(delay):
                return False

            if attempt == 0:
                self._recovery_level = self.RECOVERY_LEVEL_SESSION
                with self._state_lock:
                    self._disconnect_reason = 'recovering:session_rebuild'
                ok = self._recover_session()
            elif attempt == 1:
                self._recovery_level = self.RECOVERY_LEVEL_ADB
                with self._state_lock:
                    self._disconnect_reason = 'recovering:adb_reconnect'
                ok = self._recover_adb()
            else:
                self._recovery_level = self.RECOVERY_LEVEL_SERVER
                with self._state_lock:
                    self._disconnect_reason = 'recovering:server_restart'
                ok = self._recover_server()

            self._last_reconnect_ok = ok
            if ok:
                return True

        return False

    def _recover_session(self) -> bool:
        """一级恢复：轻量Session重连"""
        logger.info('[DeviceManager] 一级恢复：重建Session...')
        try:
            if self._appium_driver and self._connect_method:
                ok = self._appium_driver.reconnect()
                if ok and self._appium_driver.driver:
                    raw = self._appium_driver.driver
                    with self._state_lock:
                        self._pool.replace_driver(self._current_udid, raw, self._device_info)
                    return True
        except Exception as e:
            logger.warning(f'[DeviceManager] Session恢复失败: {e}')
        return False

    def _recover_adb(self) -> bool:
        """二级恢复：ADB重连"""
        logger.info('[DeviceManager] 二级恢复：ADB重连...')
        try:
            self._adb.kill_server()
            time.sleep(1)
            self._adb.start_server()
            time.sleep(2)

            with self._state_lock:
                method = self._connect_method
                target = self._current_connect_target

            if method == 'wifi' and target:
                ok, msg = self._adb.connect_wifi(target)
                if not ok:
                    logger.warning(f'[DeviceManager] ADB WiFi重连失败: {msg}')

            return self._recover_session()
        except Exception as e:
            logger.warning(f'[DeviceManager] ADB恢复失败: {e}')
            return False

    def _recover_server(self) -> bool:
        """三级恢复：重启Appium Server"""
        logger.info('[DeviceManager] 三级恢复：重启Appium Server...')
        try:
            result = self._server.restart(timeout=30)
            if not result['success']:
                logger.warning(f'[DeviceManager] Server重启失败: {result["message"]}')
                return False

            time.sleep(2)
            return self._recover_session()
        except Exception as e:
            logger.warning(f'[DeviceManager] Server恢复失败: {e}')
            return False

    def _notify_connection_lost(self, reason: str):
        """四级：通知连接丢失"""
        logger.error(f'[DeviceManager] 连接丢失: {reason}')
        with self._callbacks_lock:
            callbacks = list(self._connection_lost_callbacks)
        for cb in callbacks:
            try:
                cb(reason)
            except Exception as e:
                logger.error(f'[DeviceManager] 回调异常: {e}')

    def _on_pool_connection_lost(self, physical_id: str, error: Exception):
        """DriverPool报告连接丢失"""
        logger.warning(f'[DeviceManager] Driver {physical_id} 报告连接丢失: {error}')
        with self._state_lock:
            self._session_lost = True
            self._disconnect_reason = f'session_lost:{type(error).__name__}:{str(error)[:200]}'
            heartbeat_alive = self._heartbeat_thread is not None and self._heartbeat_thread.is_alive()
        if heartbeat_alive:
            # 心跳线程在跑：即时唤醒它做恢复，不干等下一个心跳周期（10s级恢复的前提）
            self._wake_event.set()
        # 如果心跳暂停（如测试执行中），只标记状态，不立即恢复（避免中断测试）
