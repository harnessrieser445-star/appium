"""
设备连接Blueprint
路由：
- POST /api/connect
- POST /api/disconnect
- POST /api/mock/enable
- POST /api/mock/disable
- GET  /api/device/status
- GET  /api/device/keepalive
- GET  /api/devices/scan
- GET  /api/diagnostics

Phase 3: 统一响应格式、参数校验、HTTP状态码
"""
from flask import Blueprint, request, jsonify

from backend.api.service_registry import require_device_service
from backend.api.response import success, fail, bad_request, from_service_result

device_bp = Blueprint('device', __name__)

VALID_CONNECT_METHODS = ('usb', 'wifi')


@device_bp.route('/api/connect', methods=['POST'])
def api_connect():
    """连接设备（USB/WiFi）"""
    device_svc = require_device_service()
    data = request.get_json(silent=True) or {}
    method = data.get('method', 'usb')
    device_name = data.get('device_name')
    pair_code = data.get('pair_code')

    # 参数校验
    if method not in VALID_CONNECT_METHODS:
        return bad_request(f'不支持的连接方式: {method}，支持: {", ".join(VALID_CONNECT_METHODS)}')
    if method == 'wifi' and not device_name:
        return bad_request('WiFi连接必须提供 device_name 参数')

    result = device_svc.connect(method, device_name, pair_code=pair_code)
    return from_service_result(result)


@device_bp.route('/api/disconnect', methods=['POST'])
def api_disconnect():
    """断开设备连接"""
    device_svc = require_device_service()
    result = device_svc.disconnect()
    return from_service_result(result)


@device_bp.route('/api/mock/enable', methods=['POST'])
def api_mock_enable():
    """启用模拟模式"""
    device_svc = require_device_service()
    result = device_svc.enable_mock()
    return from_service_result(result)


@device_bp.route('/api/mock/disable', methods=['POST'])
def api_mock_disable():
    """禁用模拟模式"""
    device_svc = require_device_service()
    result = device_svc.disable_mock()
    return from_service_result(result)


@device_bp.route('/api/device/status', methods=['GET'])
def api_device_status():
    """获取设备状态（兼容前端原有扁平字段结构）"""
    device_svc = require_device_service()
    status = device_svc.get_status()
    # 保持原有扁平字段结构，额外标记success=true
    resp = dict(status)
    resp['success'] = True
    return jsonify(resp)


@device_bp.route('/api/device/keepalive', methods=['GET'])
def api_device_keepalive():
    """查询连接保活状态"""
    device_svc = require_device_service()
    status = device_svc.get_keepalive_status()
    return success(data={'keepalive': status})


@device_bp.route('/api/devices/scan', methods=['GET'])
def api_scan_devices():
    """扫描USB和WiFi设备"""
    device_svc = require_device_service()
    if not hasattr(device_svc, 'scan_devices'):
        return fail('设备扫描功能不可用', status_code=501, error_code='NOT_IMPLEMENTED')
    result = device_svc.scan_devices()
    return from_service_result(result)


@device_bp.route('/api/diagnostics', methods=['GET'])
def api_diagnostics():
    """获取ADB/Appium诊断信息"""
    device_svc = require_device_service()
    if not hasattr(device_svc, 'get_adb_info'):
        return fail('诊断功能不可用', status_code=501, error_code='NOT_IMPLEMENTED')
    info = device_svc.get_adb_info()
    return success(data={'diagnostics': info})
