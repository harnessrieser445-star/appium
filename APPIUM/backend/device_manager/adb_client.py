"""
统一ADB客户端模块
Phase 4: 修复WiFi配对阻塞、增加超时容错、统一日志
"""
import re
import time
import subprocess
from typing import Optional, Dict, List, Tuple

from backend.utils.adb import ADB_PATH
from backend.utils.logger import get_logger
from backend.device_manager.udid import (
    normalize_udid, is_ip_port, parse_ip_port, is_mdns_name
)

logger = get_logger(__name__)


class ADBClient:
    """统一ADB操作客户端"""

    def __init__(self, adb_path: Optional[str] = None):
        self._adb_path = adb_path or ADB_PATH
        logger.info(f'[ADBClient] 使用ADB路径: {self._adb_path}')

    @property
    def adb_path(self) -> str:
        return self._adb_path

    def _run(self, args: List[str], timeout: int = 15, stdin_data: Optional[str] = None) -> Tuple[bool, str, str]:
        """
        执行adb命令

        Args:
            args: adb命令参数列表
            timeout: 超时秒数
            stdin_data: 通过stdin传入的数据（如配对码）

        Returns:
            (success, stdout, stderr)
        """
        cmd = [self._adb_path] + args
        try:
            # stdin: 有stdin_data则用PIPE，否则DEVNULL避免挂起
            stdin = subprocess.PIPE if stdin_data is not None else subprocess.DEVNULL
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=timeout, encoding='utf-8', errors='replace',
                stdin=stdin, input=stdin_data
            )
            return result.returncode == 0, result.stdout.strip(), result.stderr.strip()
        except subprocess.TimeoutExpired:
            logger.warning(f'[ADBClient] 命令超时 ({timeout}s): {" ".join(cmd)}')
            return False, '', f'命令超时 ({timeout}s): {" ".join(cmd)}'
        except FileNotFoundError:
            logger.error(f'[ADBClient] adb未找到: {self._adb_path}')
            return False, '', f'adb未找到: {self._adb_path}'
        except Exception as e:
            logger.error(f'[ADBClient] 命令执行异常: {e}')
            return False, '', str(e)

    def version(self) -> Optional[str]:
        """获取adb版本"""
        ok, stdout, stderr = self._run(['version'], timeout=10)
        if ok:
            lines = stdout.splitlines()
            return lines[0] if lines else None
        return None

    def kill_server(self):
        """停止adb server"""
        logger.debug('[ADBClient] kill-server')
        self._run(['kill-server'], timeout=10)

    def start_server(self):
        """启动adb server"""
        logger.debug('[ADBClient] start-server')
        ok, stdout, stderr = self._run(['start-server'], timeout=15)
        if not ok:
            logger.warning(f'[ADBClient] start-server失败: {stderr}')

    def list_devices(self) -> List[Dict[str, str]]:
        """
        列出所有已连接设备

        Returns:
            [{'udid': ..., 'state': 'device'/'offline'/'unauthorized', 'physical_id': ...}, ...]
        """
        ok, stdout, stderr = self._run(['devices'], timeout=10)
        devices = []
        if not ok:
            logger.warning(f'[ADBClient] list_devices失败: {stderr}')
            return devices

        lines = stdout.splitlines()
        for line in lines[1:]:  # 跳过标题行
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) >= 2:
                raw_udid = parts[0]
                state = parts[1]
                # 处理多词状态如 "unauthorized" 已经是单个词，不需要特殊处理
                devices.append({
                    'udid': raw_udid,
                    'state': state,
                    'physical_id': normalize_udid(raw_udid)
                })
        return devices

    def find_online_devices(self) -> List[Dict[str, str]]:
        """查找所有在线设备（state=device）"""
        return [d for d in self.list_devices() if d['state'] == 'device']

    def find_usb_device(self, udid: Optional[str] = None) -> Optional[Dict[str, str]]:
        """
        查找USB设备

        Args:
            udid: 指定UDID（可选，不指定则返回第一个USB设备）

        Returns:
            设备信息或None
        """
        online = self.find_online_devices()
        for d in online:
            # USB设备的udid是物理短ID（非IP:Port，非mDNS）
            if ':' not in d['udid'] and not d['udid'].startswith('adb-'):
                if udid is None or normalize_udid(d['udid']) == normalize_udid(udid):
                    return d
        return None

    def pair_wifi(self, ip_port: str, pair_code: str) -> Tuple[bool, str]:
        """
        WiFi配对（Android 11+ 无线调试需要）

        Phase 4修复：直接通过stdin传入配对码，避免先_run无stdin导致的15秒阻塞。

        Args:
            ip_port: 配对地址（IP:配对端口，注意：配对端口不同于连接端口）
            pair_code: 6位配对码

        Returns:
            (success, message)
        """
        if not ip_port or not pair_code:
            return False, 'WiFi配对需要IP:端口和配对码'

        # 直接通过stdin传入配对码，避免阻塞
        ok, stdout, stderr = self._run(['pair', ip_port], timeout=20, stdin_data=pair_code + '\n')
        combined = (stdout + ' ' + stderr).lower()

        if ok or 'successfully' in combined or 'successful' in combined:
            logger.info(f'[ADBClient] WiFi配对成功: {ip_port}')
            return True, f'WiFi配对成功: {ip_port}'

        # 失败时返回详细错误
        err_msg = stderr.strip() or stdout.strip() or '未知错误'
        logger.warning(f'[ADBClient] WiFi配对失败: {err_msg}')
        return False, f'WiFi配对失败: {err_msg}'

    def connect_wifi(self, ip_port: str) -> Tuple[bool, str]:
        """
        WiFi连接设备

        Args:
            ip_port: 设备地址（IP:连接端口）

        Returns:
            (success, message)
        """
        if not ip_port:
            return False, 'WiFi连接需要IP:端口'

        ok, stdout, stderr = self._run(['connect', ip_port], timeout=20)
        combined = (stdout + ' ' + stderr).lower()
        if ok and ('connected' in combined or 'already connected' in combined):
            logger.info(f'[ADBClient] WiFi连接成功: {ip_port}')
            return True, f'WiFi连接成功: {ip_port}'

        err_msg = stderr.strip() or stdout.strip() or '未知错误'
        logger.warning(f'[ADBClient] WiFi连接失败: {err_msg}')
        return False, f'WiFi连接失败: {err_msg}'

    def disconnect_device(self, udid: Optional[str] = None):
        """
        断开设备连接

        Args:
            udid: 指定设备，None则断开所有
        """
        if udid:
            self._run(['disconnect', udid], timeout=10)
        else:
            self._run(['disconnect'], timeout=10)

    def resolve_physical_id(self, raw_udid: str) -> Optional[str]:
        """
        通过ADB查询设备的物理ID

        当输入是IP:Port或mDNS名时，需要查询设备列表获取对应的物理短ID

        Args:
            raw_udid: 原始UDID

        Returns:
            物理短ID或None
        """
        if not raw_udid:
            return None

        # 如果本身就是物理ID直接返回
        if normalize_udid(raw_udid) == raw_udid and ':' not in raw_udid:
            return raw_udid.lower()

        # 查询设备列表匹配
        devices = self.find_online_devices()
        for d in devices:
            if d['udid'] == raw_udid:
                return self._get_prop_serialno(d['udid']) or normalize_udid(raw_udid)

        return normalize_udid(raw_udid)

    def _get_prop_serialno(self, udid: str) -> Optional[str]:
        """通过getprop ro.serialno获取设备序列号"""
        ok, stdout, stderr = self._run(
            ['-s', udid, 'shell', 'getprop', 'ro.serialno'],
            timeout=10
        )
        if ok and stdout.strip():
            return stdout.strip().lower()
        return None

    def get_device_props(self, udid: str) -> Dict[str, str]:
        """获取设备属性（型号、版本等）"""
        props = {}
        prop_keys = [
            'ro.product.model',
            'ro.build.version.release',
            'ro.product.brand',
            'ro.product.manufacturer',
            'ro.serialno',
        ]
        for key in prop_keys:
            ok, stdout, stderr = self._run(
                ['-s', udid, 'shell', 'getprop', key],
                timeout=10
            )
            if ok and stdout.strip():
                props[key.replace('ro.', '').replace('.', '_')] = stdout.strip()
        return props

    def is_device_available(self, udid: str) -> bool:
        """检查设备是否在线可用"""
        for d in self.list_devices():
            if d['udid'] == udid and d['state'] == 'device':
                return True
        return False

    def get_adb_version(self) -> Optional[str]:
        """获取ADB版本字符串"""
        return self.version()
