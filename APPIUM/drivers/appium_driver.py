"""
Appium Driver - 封装 Appium WebDriver 连接与操作
支持 USB 连接 与 WiFi IP 连接 两种方式
适配 Android 11+ 无线调试（TLS 配对模式）
内置连接保活与自动重连机制

Phase 4修复：
- 使用logger替换print
- Session创建超时保护
- 修复WiFi配对码传递错误（不再作为命令行参数）
- 使用ADBClient统一ADB操作
- Thread-safe keepalive/disconnect
"""

import os
import sys
import time
import threading
from typing import Optional, Dict, Any

from appium import webdriver
from appium.options.android import UiAutomator2Options

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from backend.utils.adb import ADB_PATH  # noqa: E402
from backend.utils.logger import get_logger  # noqa: E402

logger = get_logger(__name__)

# Session创建默认超时（秒）
_SESSION_CREATE_TIMEOUT = 60


class AppiumDriver:
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 4723,
        new_command_timeout: int = 300
    ):
        self._host = host
        self._port = port
        self._new_command_timeout = new_command_timeout
        self._driver = None
        self._lock = threading.RLock()

        # 保存连接参数，用于自动重连
        self._connect_method: Optional[str] = None
        self._udid: Optional[str] = None
        self._ip_port: Optional[str] = None
        self._pair_code: Optional[str] = None

    # ---------- Session创建 ----------

    def _build_options(self, udid: Optional[str] = None) -> UiAutomator2Options:
        """构建UiAutomator2Options"""
        options = UiAutomator2Options()
        options.platform_name = "Android"
        options.automation_name = "UiAutomator2"
        options.no_reset = True
        options.new_command_timeout = self._new_command_timeout
        options.set_capability('appium:ignoreHiddenApiPolicyError', True)
        options.set_capability('appium:skipServerInstallation', True)  # 已手动安装，跳过安装
        options.set_capability('appium:skipServerStartup', False)
        options.set_capability('appium:skipDeviceInitialization', True)  # 跳过Appium Settings初始化，避免国产系统后台限制
        options.set_capability('appium:uiautomator2ServerLaunchTimeout', 180000)
        options.set_capability('appium:adbExecTimeout', 60000)
        options.set_capability('appium:ignoreUnimportantViews', False)
        # 关闭窗口动画：避免截图抓到动画中间帧导致元素坐标漂移
        options.set_capability('appium:disableWindowAnimation', True)
        options.set_capability('appium:uiautomator2ServerInstallTimeout', 180000)
        options.set_capability('appium:androidInstallTimeout', 180000)
        options.set_capability('appium:settings[waitForIdleTimeout]', 100)
        options.set_capability('appium:settings[waitForSelectorTimeout]', 1000)
        options.set_capability('appium:autoGrantPermissions', True)
        options.set_capability('appium:noSign', True)
        options.set_capability('appium:disableSuppressAccessibilityService', True)
        options.set_capability('appium:enforceAppInstall', False)
        options.set_capability('appium:appWaitDuration', 30000)
        options.set_capability('appium:androidDeviceReadyTimeout', 60)
        options.set_capability('appium:avdLaunchTimeout', 120000)
        options.set_capability('appium:settingsAppWaitTimeout', 30000)
        options.set_capability('appium:ignoreUnimportantViews', False)
        options.set_capability('appium:disableWindowAnimation', True)
        options.set_capability('appium:noReset', True)
        options.set_capability('appium:fullReset', False)
        options.set_capability('appium:dontStopAppOnReset', True)

        if udid:
            options.udid = udid

        if ADB_PATH != 'adb':
            options.set_capability('adbExecPath', ADB_PATH)

        return options

    def _prep_device(self, udid: str):
        """连接前准备设备：启动Appium Settings等"""
        import subprocess
        try:
            # 强制停止并重启Appium Settings
            subprocess.run(
                [ADB_PATH, '-s', udid, 'shell', 'am', 'force-stop', 'io.appium.settings'],
                capture_output=True, timeout=10, stdin=subprocess.DEVNULL
            )
            time.sleep(1)
            # 启动Appium Settings
            subprocess.run(
                [ADB_PATH, '-s', udid, 'shell', 'am', 'start', '-n', 'io.appium.settings/.Settings'],
                capture_output=True, timeout=10, stdin=subprocess.DEVNULL
            )
            logger.info(f'[AppiumDriver] 已启动Appium Settings on {udid}')
            time.sleep(3)
        except Exception as e:
            logger.warning(f'[AppiumDriver] 设备准备失败(可忽略): {e}')

    def _create_session(self, udid: Optional[str] = None) -> Dict[str, Any]:
        """创建 Appium Session（带超时保护）"""
        try:
            options = self._build_options(udid)
            server_url = f"http://{self._host}:{self._port}"

            logger.info(f'[AppiumDriver] 创建Session: udid={udid}, server={server_url}')

            # Phase 4: 使用daemon线程+Event实现超时保护
            result = {'driver': None, 'error': None}
            done = threading.Event()

            def _do_connect():
                try:
                    result['driver'] = webdriver.Remote(
                        command_executor=server_url,
                        options=options
                    )
                except Exception as e:
                    result['error'] = e
                finally:
                    done.set()

            t = threading.Thread(target=_do_connect, daemon=True, name='session-create')
            t.start()
            done.wait(timeout=_SESSION_CREATE_TIMEOUT)

            if not done.is_set():
                logger.error(f'[AppiumDriver] Session创建超时 ({_SESSION_CREATE_TIMEOUT}s)')
                return {
                    'success': False,
                    'message': f'Appium Session创建超时（{_SESSION_CREATE_TIMEOUT}s），请检查设备连接状态'
                }

            if result['error']:
                raise result['error']

            self._driver = result['driver']
            caps = self._driver.capabilities
            device_info = {
                'name': caps.get('deviceName', 'Unknown'),
                'platform': caps.get('platformName', 'Android'),
                'version': caps.get('platformVersion', ''),
                'udid': caps.get('deviceUDID', udid or ''),
                'automation': caps.get('automationName', 'UiAutomator2')
            }
            logger.info(f'[AppiumDriver] Session创建成功: {device_info["name"]} ({device_info["version"]})')
            return {
                'success': True,
                'message': 'Appium 连接成功',
                'device': device_info
            }
        except Exception as e:
            self._driver = None
            logger.error(f'[AppiumDriver] Session创建失败: {e}')
            return {
                'success': False,
                'message': f'Appium 连接失败: {str(e)}'
            }

    def connect_usb(self, udid: Optional[str] = None) -> Dict[str, Any]:
        """USB 连接"""
        with self._lock:
            self._connect_method = 'usb'
            
            # 如果没有指定udid，自动查找已连接的USB设备
            if not udid:
                udid = self._get_connected_udid()
                if not udid:
                    return {
                        'success': False,
                        'message': '未发现已连接的USB设备，请确保设备已连接并开启USB调试'
                    }
                logger.info(f'[AppiumDriver] 自动检测到USB设备: {udid}')
            
            self._udid = udid
            return self._create_session(udid=udid)

    def connect_wifi(self, ip_port: str, pair_code: Optional[str] = None) -> Dict[str, Any]:
        """
        WiFi 连接

        Phase 4修复：使用ADBClient进行配对和连接，配对码通过stdin传递。
        不再将pair_code作为命令行参数传递。
        """
        with self._lock:
            self._connect_method = 'wifi'
            self._ip_port = ip_port
            self._pair_code = pair_code

            try:
                from backend.device_manager.adb_client import ADBClient
                adb = ADBClient(ADB_PATH)
            except Exception:
                adb = None

            # 1. 如果有配对码，执行配对
            if pair_code and adb:
                pair_port = self._discover_pairing_port()
                if pair_port:
                    ip = ip_port.split(':')[0]
                    pair_addr = f"{ip}:{pair_port}"
                    ok, msg = adb.pair_wifi(pair_addr, pair_code)
                    if not ok:
                        logger.warning(f'[AppiumDriver] WiFi配对失败: {msg}')
                        return {
                            'success': False,
                            'message': f'配对失败: {msg}'
                        }
                    time.sleep(2)
                else:
                    logger.warning('[AppiumDriver] 未发现mDNS配对端口，跳过配对直接连接')

            # 2. 执行WiFi连接
            if adb:
                ok, msg = adb.connect_wifi(ip_port)
                if not ok:
                    logger.warning(f'[AppiumDriver] WiFi连接失败: {msg}')
                    return {
                        'success': False,
                        'message': f'WiFi连接失败: {msg}'
                    }
                time.sleep(2)

            # 3. 获取已连接设备UDID
            udid = self._get_connected_udid()
            if not udid:
                return {
                    'success': False,
                    'message': f'未发现已连接的设备，请确保设备无线调试已开启且可连接'
                }

            self._udid = udid
            return self._create_session(udid=udid)

    def _discover_pairing_port(self) -> Optional[int]:
        """通过mDNS发现配对端口"""
        import subprocess
        try:
            result = subprocess.run(
                [ADB_PATH, 'mdns', 'services'],
                capture_output=True, text=True, timeout=10,
                stdin=subprocess.DEVNULL
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    if '_adb-tls-pairing._tcp' in line:
                        parts = line.strip().split()
                        if len(parts) >= 3:
                            addr = parts[-1]
                            if ':' in addr:
                                return int(addr.split(':')[1])
        except Exception as e:
            logger.debug(f'[AppiumDriver] mDNS发现失败: {e}')
        return None

    def _get_connected_udid(self) -> Optional[str]:
        """获取已连接设备的udid"""
        import subprocess
        try:
            result = subprocess.run(
                [ADB_PATH, 'devices'],
                capture_output=True, text=True, timeout=10,
                stdin=subprocess.DEVNULL
            )
            for line in result.stdout.splitlines():
                line = line.strip()
                if not line or line.startswith('List of') or line.startswith('*'):
                    continue
                parts = line.split()
                if len(parts) >= 2 and parts[1] == 'device':
                    return parts[0]
        except Exception as e:
            logger.warning(f'[AppiumDriver] 获取设备列表失败: {e}')
        return None

    # ---------- 保活与重连 ----------

    def keepalive(self) -> bool:
        """
        发送轻量级命令保持Session活跃。
        使用 driver.get_window_size() 发送真实命令，走 UiAutomator2
        instrumentation（与 screenshot 同路径），instrumentation 崩时必然失败，
        同时重置Appium Server的newCommandTimeout计时器。
        注意：driver.session（属性不存在）、session_id（本地值0请求）、
        current_package（不走instrumentation，崩时仍可能成功）均不可用作探针
        （2026-09-11 真机两轮实测确认）。
        """
        with self._lock:
            if not self._driver:
                return False
            try:
                _ = self._driver.get_window_size()
                return True
            except Exception as e:
                logger.warning(f'[AppiumDriver] 心跳失败: {e}')
                return False

    def check_session_alive(self) -> bool:
        """检查Session是否仍然存活"""
        return self.keepalive()

    def reconnect(self) -> bool:
        """
        使用保存的连接参数重连。
        先清理旧driver，再重新创建Session。
        """
        with self._lock:
            if not self._connect_method:
                logger.warning('[AppiumDriver] 无保存的连接参数，无法重连')
                return False

            # 清理旧driver
            self._safe_quit()
            self._driver = None

            logger.info(f'[AppiumDriver] 尝试重连 (method={self._connect_method})...')

            try:
                from backend.device_manager.adb_client import ADBClient
                adb = ADBClient(ADB_PATH)
            except Exception:
                adb = None

            if self._connect_method == 'usb':
                result = self._create_session(udid=self._udid)

            elif self._connect_method == 'wifi':
                # WiFi重连：先adb connect，再创建session（不重复配对）
                if adb and self._ip_port:
                    adb.connect_wifi(self._ip_port)
                    time.sleep(2)
                udid = self._get_connected_udid()
                if not udid:
                    logger.warning('[AppiumDriver] WiFi重连失败：未找到已连接设备')
                    return False
                self._udid = udid
                result = self._create_session(udid=udid)
            else:
                logger.warning(f'[AppiumDriver] 未知连接方式: {self._connect_method}')
                return False

            success = result.get('success', False)
            if success:
                logger.info('[AppiumDriver] 重连成功')
            else:
                logger.warning(f'[AppiumDriver] 重连失败: {result.get("message", "")}')
            return success

    # ---------- 断开与操作 ----------

    def _safe_quit(self):
        """安全退出driver（不抛异常）"""
        if self._driver:
            try:
                self._driver.quit()
            except Exception as e:
                logger.debug(f'[AppiumDriver] quit异常(可忽略): {e}')

    def disconnect(self) -> Dict[str, Any]:
        """断开Appium Session"""
        with self._lock:
            self._safe_quit()
            self._driver = None
            self._connect_method = None
            self._udid = None
            self._ip_port = None
            self._pair_code = None
            logger.info('[AppiumDriver] 已断开')
            return {'success': True, 'message': 'Appium 已断开'}

    def get_screenshot_bytes(self) -> Optional[bytes]:
        """获取截图PNG字节流（不落盘，避免文件读写竞态）"""
        with self._lock:
            if not self._driver:
                return None
            try:
                return self._driver.get_screenshot_as_png()
            except Exception as e:
                logger.warning(f'[AppiumDriver] 获取截图字节流失败: {e}')
                return None

    def take_screenshot(self, save_path: str) -> bool:
        """获取截图并保存"""
        with self._lock:
            if not self._driver:
                return False
            try:
                png_bytes = self._driver.get_screenshot_as_png()
                with open(save_path, 'wb') as f:
                    f.write(png_bytes)
                return True
            except Exception as e:
                logger.warning(f'[AppiumDriver] 截图失败: {e}')
                return False

    def get_page_source(self) -> Optional[str]:
        """获取页面XML"""
        with self._lock:
            if not self._driver:
                return None
            try:
                return self._driver.page_source
            except Exception as e:
                logger.warning(f'[AppiumDriver] 获取page_source失败: {e}')
                return None

    def is_connected(self) -> bool:
        with self._lock:
            return self._driver is not None

    @property
    def driver(self):
        return self._driver
