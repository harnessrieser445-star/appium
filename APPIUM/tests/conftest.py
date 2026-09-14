"""
pytest 配置和共享fixtures
"""
import os
import sys
import tempfile
import shutil
import pytest

# 确保项目根目录在sys.path中
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


@pytest.fixture(scope='session')
def app():
    """创建Flask应用用于测试（session级别，复用app实例）"""
    from app import create_app
    flask_app, _ = create_app()
    flask_app.config['TESTING'] = True
    # 确保mock模式可用于无设备测试
    yield flask_app


@pytest.fixture(scope='session')
def client(app):
    """Flask测试客户端"""
    return app.test_client()


@pytest.fixture(autouse=True)
def reset_state(app):
    """每个测试前重置设备状态到断开，清空脚本设计"""
    from backend.api.service_registry import (
        get_device_service, get_script_service
    )

    with app.app_context():
        try:
            device_svc = get_device_service()
            if device_svc.is_connected() or device_svc.is_mock():
                device_svc.disconnect()
        except Exception:
            pass

        try:
            script_svc = get_script_service()
            script_svc.clear()
        except Exception:
            pass

    yield


@pytest.fixture
def mock_device(client):
    """启用模拟模式的fixture，测试后自动断开"""
    client.post('/api/mock/enable')
    yield
    client.post('/api/disconnect')
