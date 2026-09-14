"""
CORS跨域支持（无需flask-cors依赖）
"""
from flask import Flask, request, make_response


def setup_cors(app: Flask, origins: str = '*'):
    """
    为Flask app注册CORS支持。

    Args:
        app: Flask应用实例
        origins: 允许的Origin，默认'*'允许所有
    """

    @app.after_request
    def _add_cors_headers(response):
        # 跳过非API路径（静态资源和首页使用默认CORS策略）
        if not request.path.startswith('/api/'):
            return response

        origin = request.headers.get('Origin', '')
        allowed_origin = origins if origins == '*' else (origin if origin in origins.split(',') else '')

        if allowed_origin:
            response.headers['Access-Control-Allow-Origin'] = allowed_origin
            response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
            response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-Requested-With'
            response.headers['Access-Control-Max-Age'] = '86400'
            response.headers['Access-Control-Allow-Credentials'] = 'true'

        return response

    @app.before_request
    def _handle_preflight():
        """处理OPTIONS预检请求"""
        if request.method == 'OPTIONS' and request.path.startswith('/api/'):
            response = make_response('', 204)
            origin = request.headers.get('Origin', '')
            allowed_origin = origins if origins == '*' else (origin if origin in origins.split(',') else '')
            if allowed_origin:
                response.headers['Access-Control-Allow-Origin'] = allowed_origin
                response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
                response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-Requested-With'
                response.headers['Access-Control-Max-Age'] = '86400'
                response.headers['Access-Control-Allow-Credentials'] = 'true'
            return response
