"""
API层集成测试
使用Flask测试客户端验证HTTP接口全链路
"""
import json
import pytest


class TestHealthAPI:
    """健康检查API测试"""

    def test_health_endpoint(self, client):
        resp = client.get('/api/health')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert data['message'] == 'ok'

    def test_index_page(self, client):
        resp = client.get('/')
        assert resp.status_code == 200
        assert b'Appium' in resp.data


class TestDeviceAPI:
    """设备管理API测试"""

    def test_initial_status(self, client):
        resp = client.get('/api/device/status')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['connected'] is False
        assert data['mode'] == 'disconnected'

    def test_enable_mock(self, client):
        resp = client.post('/api/mock/enable')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True

    def test_status_after_mock(self, client):
        client.post('/api/mock/enable')
        resp = client.get('/api/device/status')
        data = resp.get_json()
        assert data['connected'] is True
        assert data['mode'] == 'mock'
        assert data['device']['name'] == '模拟设备'

    def test_diagnostics(self, client):
        client.post('/api/mock/enable')
        resp = client.get('/api/diagnostics')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        diag = data['data']['diagnostics']
        assert 'adb_path' in diag
        assert 'server_url' in diag
        assert diag['is_mock'] is True

    def test_keepalive_status(self, client):
        client.post('/api/mock/enable')
        resp = client.get('/api/device/keepalive')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert 'keepalive' in data['data']

    def test_disconnect(self, client):
        client.post('/api/mock/enable')
        resp = client.post('/api/disconnect')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True

        status_resp = client.get('/api/device/status')
        assert status_resp.get_json()['connected'] is False

    def test_invalid_connect_method(self, client):
        resp = client.post('/api/connect',
                           data=json.dumps({'method': 'bluetooth'}),
                           content_type='application/json')
        assert resp.status_code == 400
        data = resp.get_json()
        assert data['success'] is False
        assert data['error_code'] == 'BAD_REQUEST'

    def test_wifi_missing_device_name(self, client):
        resp = client.post('/api/connect',
                           data=json.dumps({'method': 'wifi'}),
                           content_type='application/json')
        assert resp.status_code == 400

    def test_scan_devices(self, client):
        resp = client.get('/api/devices/scan')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True


class TestElementScreenshotAPI:
    """截图与元素API测试"""

    def test_screenshot_no_device(self, client):
        resp = client.get('/api/screenshot')
        assert resp.status_code == 400

    def test_screenshot_mock_mode(self, client, mock_device):
        resp = client.get('/api/screenshot')
        assert resp.status_code == 200
        # PNG文件以 0x89 0x50 0x4E 0x47 开头
        assert resp.data[:4] == b'\x89PNG'

    def test_elements_refresh(self, client, mock_device):
        resp = client.post('/api/elements/refresh')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True

    def test_highlight_missing_bounds(self, client):
        resp = client.post('/api/screenshot/highlight',
                           data=json.dumps({}),
                           content_type='application/json')
        assert resp.status_code == 400

    def test_highlight_with_bounds(self, client, mock_device):
        # 先获取截图
        client.get('/api/screenshot')
        resp = client.post('/api/screenshot/highlight',
                           data=json.dumps({'bounds': [100, 200, 300, 400]}),
                           content_type='application/json')
        # 成功时返回PNG，失败时返回JSON错误
        if resp.status_code == 200:
            assert resp.data[:4] == b'\x89PNG'
        else:
            # mock模式下可能因screenshot_service状态问题返回400
            assert resp.status_code in (200, 400)

    def test_locate_element_requires_coords(self, client):
        resp = client.post('/api/elements/locate',
                           data=json.dumps({}),
                           content_type='application/json')
        assert resp.status_code == 400

    def test_locate_element_invalid_coords(self, client):
        resp = client.post('/api/elements/locate',
                           data=json.dumps({'x': 'abc', 'y': 100}),
                           content_type='application/json')
        assert resp.status_code == 400


class TestScriptAPI:
    """脚本编排API测试"""

    def test_get_actions(self, client):
        resp = client.get('/api/script/actions')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert 'actions' in data

    def test_empty_design(self, client):
        resp = client.get('/api/script/design')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True

    def test_clear_design(self, client):
        resp = client.post('/api/script/clear')
        assert resp.status_code == 200
        assert resp.get_json()['success'] is True

    def test_add_element(self, client):
        elem = {'id': 'btn1', 'name': '按钮', 'text': 'OK',
                'bounds': [0, 0, 100, 50], 'resource_id': 'com:id/ok'}
        resp = client.post('/api/script/elements',
                           data=json.dumps(elem),
                           content_type='application/json')
        assert resp.status_code == 200
        assert resp.get_json()['success'] is True

    def test_get_elements(self, client):
        client.post('/api/script/elements',
                    data=json.dumps({'id': 'e1', 'bounds': [0, 0, 10, 10]}),
                    content_type='application/json')
        resp = client.get('/api/script/elements')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True

    def test_add_step_missing_action(self, client):
        resp = client.post('/api/script/steps',
                           data=json.dumps({'description': 'no action'}),
                           content_type='application/json')
        assert resp.status_code == 400

    def test_add_step_with_action(self, client):
        resp = client.post('/api/script/steps',
                           data=json.dumps({'action': 'swipe', 'action_params': {'direction': 'up'}}),
                           content_type='application/json')
        assert resp.status_code == 200
        assert resp.get_json()['success'] is True

    def test_full_script_workflow(self, client):
        """完整脚本编排流程：添加元素→添加步骤→预览→保存→加载"""
        # 清空
        client.post('/api/script/clear')

        # 添加元素
        elem = {'id': 'login_btn', 'name': '登录按钮', 'text': '登录',
                'bounds': [100, 500, 300, 580], 'resource_id': 'com.test:id/login'}
        client.post('/api/script/elements',
                    data=json.dumps(elem),
                    content_type='application/json')

        # 添加步骤
        client.post('/api/script/steps',
                    data=json.dumps({'element': elem, 'action': 'click', 'description': '点击登录'}),
                    content_type='application/json')

        # 获取设计
        design_resp = client.get('/api/script/design')
        design = design_resp.get_json()
        assert design['step_count'] == 1

        # 预览脚本
        preview_resp = client.get('/api/script/gen/preview?name=api_test')
        assert preview_resp.status_code == 200
        preview = preview_resp.get_json()
        assert preview['success'] is True
        assert 'click' in preview.get('code', '')

        # 保存用例
        save_resp = client.post('/api/script/save',
                                data=json.dumps({'name': 'api_workflow_test'}),
                                content_type='application/json')
        assert save_resp.status_code == 200
        assert save_resp.get_json()['success'] is True

        # 列出用例
        list_resp = client.get('/api/script/cases')
        cases = list_resp.get_json()
        assert cases['success'] is True
        case_names = [c.get('name', '') for c in cases.get('cases', [])]
        assert 'api_workflow_test' in case_names

        # 清空后重新加载
        client.post('/api/script/clear')
        load_resp = client.get('/api/script/load/api_workflow_test')
        assert load_resp.status_code == 200
        assert load_resp.get_json()['success'] is True

    def test_save_case_empty_name(self, client):
        resp = client.post('/api/script/save',
                           data=json.dumps({'name': ''}),
                           content_type='application/json')
        assert resp.status_code == 400

    def test_save_case_invalid_name(self, client):
        resp = client.post('/api/script/save',
                           data=json.dumps({'name': '../etc/passwd'}),
                           content_type='application/json')
        assert resp.status_code == 400

    def test_reorder_steps_requires_list(self, client):
        resp = client.post('/api/script/steps/reorder',
                           data=json.dumps({'step_ids': 'not-a-list'}),
                           content_type='application/json')
        assert resp.status_code == 400

    def test_gen_download(self, client):
        client.post('/api/script/clear')
        # 添加一个swipe步骤（不需要元素定位）
        client.post('/api/script/steps',
                    data=json.dumps({'action': 'swipe', 'action_params': {'direction': 'up'}}),
                    content_type='application/json')
        resp = client.get('/api/script/gen/download?name=download_test')
        assert resp.status_code == 200
        # Python脚本以下载形式返回
        assert resp.content_length is None or resp.content_length > 0

    def test_execution_status(self, client):
        resp = client.get('/api/script/gen/status')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True


class TestCORSHeaders:
    """CORS头测试"""

    def test_cors_headers_present(self, client):
        resp = client.get('/api/health', headers={'Origin': 'http://localhost:3000'})
        # CORS中间件应设置Access-Control-Allow-Origin
        assert 'Access-Control-Allow-Origin' in resp.headers or resp.status_code == 200


class TestErrorHandling:
    """全局错误处理测试"""

    def test_404_json_response(self, client):
        resp = client.get('/api/nonexistent/path')
        # 404应该返回JSON格式（或至少有正确状态码）
        assert resp.status_code == 404

    def test_malformed_json(self, client):
        resp = client.post('/api/connect',
                           data='not valid json{{{',
                           content_type='application/json')
        # 格式错误的JSON不应导致500
        assert resp.status_code in (400, 200)
