"""
统一API响应格式工具
规范所有JSON响应结构，避免各Blueprint自行构造响应格式不一致。

响应格式：
  成功: {"success": true, "data": {...}, "message": "..."}
  失败: {"success": false, "message": "...", "error_code": "..."}
"""
from flask import jsonify
from typing import Any, Dict, Optional, Tuple


def success(data: Any = None, message: str = '', status_code: int = 200, **kwargs) -> Tuple:
    """
    成功响应

    Args:
        data: 响应数据主体
        message: 可选提示信息
        status_code: HTTP状态码（默认200）
        **kwargs: 额外顶层字段（如count、mode等与data平级的字段）
    """
    resp: Dict[str, Any] = {'success': True}
    if data is not None:
        resp['data'] = data
    if message:
        resp['message'] = message
    resp.update(kwargs)
    return jsonify(resp), status_code


def fail(message: str, status_code: int = 400, error_code: str = '', **kwargs) -> Tuple:
    """
    失败响应

    Args:
        message: 错误描述
        status_code: HTTP状态码（默认400）
        error_code: 机器可读错误码（可选）
        **kwargs: 额外顶层字段
    """
    resp: Dict[str, Any] = {'success': False, 'message': message}
    if error_code:
        resp['error_code'] = error_code
    resp.update(kwargs)
    return jsonify(resp), status_code


# ---------- 常用快捷方法 ----------

def not_found(message: str = '资源不存在', **kwargs) -> Tuple:
    """404 Not Found"""
    return fail(message, status_code=404, error_code='NOT_FOUND', **kwargs)


def bad_request(message: str = '请求参数错误', **kwargs) -> Tuple:
    """400 Bad Request"""
    return fail(message, status_code=400, error_code='BAD_REQUEST', **kwargs)


def conflict(message: str = '资源冲突', **kwargs) -> Tuple:
    """409 Conflict（如正在执行中）"""
    return fail(message, status_code=409, error_code='CONFLICT', **kwargs)


def server_error(message: str = '服务器内部错误', **kwargs) -> Tuple:
    """500 Internal Server Error"""
    return fail(message, status_code=500, error_code='INTERNAL_ERROR', **kwargs)


def service_unavailable(message: str = '服务暂不可用', **kwargs) -> Tuple:
    """503 Service Unavailable"""
    return fail(message, status_code=503, error_code='SERVICE_UNAVAILABLE', **kwargs)


def from_service_result(result: Dict[str, Any], success_status: int = 200) -> Tuple:
    """
    将Service层返回的 {'success': bool, ...} 字典转换为标准HTTP响应。
    根据success字段自动选择200或对应错误码（400/404/409），
    调用方可通过result中的_http_status_字段显式指定状态码。
    """
    is_ok = bool(result.get('success', False))
    status = result.pop('_http_status_', None)

    if is_ok:
        if status is None:
            status = success_status
        return jsonify(result), status

    # 失败：根据message内容或显式error_code推断状态码
    if status is None:
        msg = result.get('message', '')
        error_code = result.get('error_code', '')
        if error_code == 'NOT_FOUND' or '不存在' in msg or 'not found' in msg.lower():
            status = 404
        elif error_code == 'CONFLICT' or '执行中' in msg or '已存在' in msg:
            status = 409
        else:
            status = 400
    return jsonify(result), status
