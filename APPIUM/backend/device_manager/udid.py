"""
UDID规范化模块
Phase 3: 解决WiFi设备udid不一致问题
支持三种UDID形式：
1. USB短ID: "2f4f727d"
2. WiFi mDNS名: "adb-2f4f727d-abcde._adb-tls-connect._tcp"
3. WiFi IP:Port: "192.168.1.100:37891"

设计原则：物理设备短ID作为canonical_id（数据库主键），mDNS名/IP:Port作为连接地址
"""
import re
from typing import Optional, Tuple, List


# 正则：物理短ID（8-16位十六进制）
_PHYSICAL_ID_RE = re.compile(r'^[0-9a-fA-F]{8,16}$')

# 正则：IP:Port 格式（WiFi直连）
_IP_PORT_RE = re.compile(r'^(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}):(\d{1,5})$')

# 正则：mDNS服务名格式 adb-<物理ID>-<suffix>._adb-tls-connect._tcp
_MDNS_RE = re.compile(
    r'^adb-([0-9a-fA-F]{8,16})-[a-zA-Z0-9]+\._adb-tls-connect\._tcp$'
)


def normalize_udid(raw_udid: str) -> str:
    """
    将任意形式的UDID规范化为canonical短ID

    Args:
        raw_udid: 原始UDID（短ID/mDNS名/IP:Port）

    Returns:
        规范化后的短ID，如果无法解析则返回原始值
    """
    if not raw_udid:
        return raw_udid

    raw = raw_udid.strip()

    # 1. 已经是短ID
    if _PHYSICAL_ID_RE.match(raw):
        return raw.lower()

    # 2. mDNS名 → 提取物理ID
    m = _MDNS_RE.match(raw)
    if m:
        return m.group(1).lower()

    # 3. IP:Port 格式无法直接提取物理ID（需要adb devices查询）
    #    此时返回原值，后续通过ADBClient.resolve_udid()查询
    return raw


def is_mdns_name(udid: str) -> bool:
    """判断是否为mDNS服务名"""
    return bool(_MDNS_RE.match(udid or ''))


def is_ip_port(udid: str) -> bool:
    """判断是否为IP:Port格式"""
    return bool(_IP_PORT_RE.match(udid or ''))


def is_physical_id(udid: str) -> bool:
    """判断是否为物理短ID"""
    return bool(_PHYSICAL_ID_RE.match(udid or ''))


def parse_ip_port(addr: str) -> Optional[Tuple[str, int]]:
    """
    解析IP:Port格式

    Returns:
        (ip, port) 或 None
    """
    m = _IP_PORT_RE.match(addr or '')
    if m:
        return m.group(1), int(m.group(2))
    return None


def extract_physical_id_from_mdns(mdns_name: str) -> Optional[str]:
    """从mDNS名中提取物理ID"""
    m = _MDNS_RE.match(mdns_name or '')
    if m:
        return m.group(1).lower()
    return None
