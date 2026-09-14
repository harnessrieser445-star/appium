"""
全局错误处理中间件
- 捕获所有未处理异常，返回JSON格式错误（而非Flask默认HTML错误页）
- 注册常用HTTP错误码的JSON处理器
- 请求日志中间件
"""
import time
import traceback
import uuid
from flask import Flask, request, g, jsonify

from backend.utils.logger import get_logger

logger = get_logger(__name__)


def register_error_handlers(app: Flask):
    """注册全局错误处理器到Flask app"""

    # ---------- 请求日志 + Request ID ----------
    @app.before_request
    def _before_request():
        g.request_id = str(uuid.uuid4())[:8]
        g.start_time = time.time()
        # 跳过静态资源和健康检查的日志
        if request.path.startswith('/static') or request.path == '/api/health':
            return
        logger.info(f'[REQ][{g.request_id}] {request.method} {request.path}')

    @app.after_request
    def _after_request(response):
        if request.path.startswith('/static') or request.path == '/api/health':
            return response
        elapsed = (time.time() - getattr(g, 'start_time', time.time())) * 1000
        logger.info(f'[RESP][{g.request_id}] {response.status_code} ({elapsed:.1f}ms)')
        return response

    # ---------- 400 Bad Request ----------
    @app.errorhandler(400)
    def _bad_request(e):
        return jsonify({
            'success': False,
            'message': f'请求参数错误: {str(e.description) if hasattr(e, "description") else str(e)}',
            'error_code': 'BAD_REQUEST'
        }), 400

    # ---------- 404 Not Found ----------
    @app.errorhandler(404)
    def _not_found(e):
        # API路径返回JSON，其他路径交给前端
        if request.path.startswith('/api/'):
            return jsonify({
                'success': False,
                'message': f'接口不存在: {request.path}',
                'error_code': 'NOT_FOUND'
            }), 404
        return e

    # ---------- 405 Method Not Allowed ----------
    @app.errorhandler(405)
    def _method_not_allowed(e):
        return jsonify({
            'success': False,
            'message': f'方法不允许: {request.method} {request.path}',
            'error_code': 'METHOD_NOT_ALLOWED'
        }), 405

    # ---------- 413 Request Entity Too Large ----------
    @app.errorhandler(413)
    def _too_large(e):
        return jsonify({
            'success': False,
            'message': '请求体过大',
            'error_code': 'PAYLOAD_TOO_LARGE'
        }), 413

    # ---------- 500 Internal Server Error（兜底） ----------
    @app.errorhandler(Exception)
    def _internal_error(e):
        # HTTPException子类（404/405等已单独处理，剩余的如500）
        from werkzeug.exceptions import HTTPException
        if isinstance(e, HTTPException):
            if e.code and e.code < 500:
                return jsonify({
                    'success': False,
                    'message': e.description if hasattr(e, 'description') else str(e),
                    'error_code': f'HTTP_{e.code}'
                }), e.code

        req_id = getattr(g, 'request_id', 'unknown')
        logger.error(
            f'[ERR][{req_id}] 未捕获异常 {request.method} {request.path}: {e}',
            exc_info=True
        )
        return jsonify({
            'success': False,
            'message': f'服务器内部错误: {str(e)}',
            'error_code': 'INTERNAL_ERROR',
            'request_id': req_id
        }), 500


def get_request_id() -> str:
    """获取当前请求ID（在请求上下文中可用）"""
    from flask import g
    return getattr(g, 'request_id', 'unknown')
