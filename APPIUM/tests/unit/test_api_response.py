"""
API响应工具单元测试
测试 backend/api/response.py 的统一响应格式
"""
import json
import pytest
from flask import Flask

from backend.api.response import (
    success, fail, bad_request, not_found, conflict,
    server_error, service_unavailable, from_service_result
)


@pytest.fixture
def app():
    app = Flask(__name__)
    app.config['TESTING'] = True
    return app


class TestSuccessResponse:
    def test_success_with_data(self, app):
        with app.test_request_context():
            resp, code = success(data={'key': 'value'})
            assert code == 200
            body = json.loads(resp.data)
            assert body['success'] is True
            assert body['data'] == {'key': 'value'}

    def test_success_with_message(self, app):
        with app.test_request_context():
            resp, code = success(message='操作成功')
            assert code == 200
            body = json.loads(resp.data)
            assert body['success'] is True
            assert body['message'] == '操作成功'

    def test_success_with_extra_fields(self, app):
        with app.test_request_context():
            resp, code = success(data={'items': []}, count=5, mode='test')
            body = json.loads(resp.data)
            assert body['count'] == 5
            assert body['mode'] == 'test'

    def test_success_custom_status(self, app):
        with app.test_request_context():
            resp, code = success(message='created', status_code=201)
            assert code == 201


class TestFailResponse:
    def test_fail_default(self, app):
        with app.test_request_context():
            resp, code = fail('出错了')
            assert code == 400
            body = json.loads(resp.data)
            assert body['success'] is False
            assert body['message'] == '出错了'

    def test_fail_with_error_code(self, app):
        with app.test_request_context():
            resp, code = fail('未找到', status_code=404, error_code='NOT_FOUND')
            assert code == 404
            body = json.loads(resp.data)
            assert body['error_code'] == 'NOT_FOUND'

    def test_bad_request(self, app):
        with app.test_request_context():
            resp, code = bad_request('参数错误')
            assert code == 400
            body = json.loads(resp.data)
            assert body['error_code'] == 'BAD_REQUEST'

    def test_not_found(self, app):
        with app.test_request_context():
            resp, code = not_found('资源不存在')
            assert code == 404
            body = json.loads(resp.data)
            assert body['error_code'] == 'NOT_FOUND'

    def test_conflict(self, app):
        with app.test_request_context():
            resp, code = conflict('资源冲突')
            assert code == 409
            body = json.loads(resp.data)
            assert body['error_code'] == 'CONFLICT'

    def test_server_error(self, app):
        with app.test_request_context():
            resp, code = server_error('内部错误')
            assert code == 500
            body = json.loads(resp.data)
            assert body['error_code'] == 'INTERNAL_ERROR'


class TestFromServiceResult:
    def test_success_result(self, app):
        with app.test_request_context():
            result = {'success': True, 'message': 'ok', 'data': {'id': 1}}
            resp, code = from_service_result(result)
            assert code == 200
            body = json.loads(resp.data)
            assert body['success'] is True

    def test_failure_result_default_400(self, app):
        with app.test_request_context():
            result = {'success': False, 'message': '参数无效'}
            resp, code = from_service_result(result)
            assert code == 400
            body = json.loads(resp.data)
            assert body['success'] is False

    def test_failure_not_found_message(self, app):
        with app.test_request_context():
            result = {'success': False, 'message': '用例不存在'}
            resp, code = from_service_result(result)
            assert code == 404

    def test_failure_conflict_message(self, app):
        with app.test_request_context():
            result = {'success': False, 'message': '已有测试正在执行中'}
            resp, code = from_service_result(result)
            assert code == 409

    def test_explicit_http_status(self, app):
        with app.test_request_context():
            result = {'success': False, 'message': 'err', '_http_status_': 503}
            resp, code = from_service_result(result)
            assert code == 503
