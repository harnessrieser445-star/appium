"""
设备发现模块
Phase 3: 提供USB和WiFi设备扫描能力
支持：USB设备列表、mDNS服务发现、已连接设备列表
"""
import subprocess
from typing import List, Dict, Any, Optional

from backend.utils.adb import ADB_PATH
from backend.utils.logger import get_logger
from backend.device_manager.adb_client import ADBClient
from backend.device_manager.udid import normalize_udid, is_mdns_name, extract_physical_id_from_mdns

logger = get_logger(__name__)


class DeviceDiscovery:
    """设备发现：扫描USB/WiFi设备"""

    def __init__(self, adb_client: Optional[ADBClient] = None):
        self._adb = adb_client or ADBClient()

    def scan_usb_devices(self) -> List[Dict[str, Any]]:
        """
        扫描USB连接的设备

        Returns:
            [{'udid', 'physical_id', 'state', 'type': 'usb', 'props': {...}}, ...]
        """
        devices = []
        for d in self._adb.list_devices():
            # USB设备特征：udid不含冒号、不是mDNS名
            if ':' not in d['udid'] and not is_mdns_name(d['udid']):
                info = {
                    'udid': d['udid'],
                    'physical_id': d['physical_id'],
                    'state': d['state'],
                    'type': 'usb'
                }
                if d['state'] == 'device':
                    info['props'] = self._adb.get_device_props(d['udid'])
                devices.append(info)
        return devices

    def scan_wifi_devices(self) -> List[Dict[str, Any]]:
        """
        扫描已连接的WiFi设备

        Returns:
            [{'udid', 'physical_id', 'state', 'type': 'wifi', 'address': 'ip:port'}, ...]
        """
        devices = []
        for d in self._adb.list_devices():
            # WiFi设备特征：udid包含冒号（IP:Port）或为mDNS名
            if ':' in d['udid'] or is_mdns_name(d['udid']):
                info = {
                    'udid': d['udid'],
                    'physical_id': d['physical_id'],
                    'state': d['state'],
                    'type': 'wifi',
                    'address': d['udid']
                }
                devices.append(info)
        return devices

    def scan_all_devices(self) -> List[Dict[str, Any]]:
        """扫描所有设备（USB+WiFi）"""
        return self.scan_usb_devices() + self.scan_wifi_devices()

    def discover_mdns_services(self, timeout: float = 3) -> List[Dict[str, str]]:
        """
        通过mDNS发现无线调试设备（Android 11+）

        注意：此功能依赖系统mdns工具（Windows可能需要Bonjour），失败时返回空列表

        Returns:
            [{'name', 'physical_id', 'ip', 'port'}, ...]
        """
        services = []
        try:
            # 尝试使用adb的mdns功能
            ok, stdout, stderr = self._adb._run(
                ['mdns', 'services'], timeout=10
            )
            if ok and stdout:
                for line in stdout.splitlines():
                    line = line.strip()
                    if '_adb-tls-connect' in line:
                        # 解析mDNS服务名
                        parts = line.split()
                        for part in parts:
                            if is_mdns_name(part):
                                pid = extract_physical_id_from_mdns(part)
                                services.append({
                                    'name': part,
                                    'physical_id': pid or '',
                                    'ip': '',
                                    'port': ''
                                })
        except Exception as e:
            logger.debug(f'[DeviceDiscovery] mDNS扫描跳过: {e}')

        return services
