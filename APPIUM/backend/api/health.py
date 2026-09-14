"""
健康检查和首页Blueprint
路由：
- GET /
- GET /api/health
"""
from flask import Blueprint, render_template

from backend.api.response import success

health_bp = Blueprint('health', __name__)


@health_bp.route('/')
def index():
    """首页（Web编辑器）"""
    return render_template('index.html')


@health_bp.route('/api/health')
def health():
    """健康检查"""
    return success(message='ok')
