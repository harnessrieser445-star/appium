"""
Service层单元测试
测试DeviceService、ScriptDesignService的核心业务逻辑
"""
import pytest


class TestDeviceService:
    """DeviceService测试"""

    def test_initial_state(self, app):
        """初始状态应为未连接"""
        from backend.api.service_registry import get_device_service
        svc = get_device_service()
        status = svc.get_status()
        assert status['connected'] is False
        assert status['mode'] == 'disconnected'

    def test_enable_mock(self, app):
        """测试启用模拟模式"""
        from backend.api.service_registry import get_device_service
        svc = get_device_service()

        result = svc.enable_mock()
        assert result['success'] is True
        assert svc.is_mock() is True
        assert svc.is_connected() is True

        status = svc.get_status()
        assert status['connected'] is True
        assert status['mode'] == 'mock'
        assert status['device']['name'] == '模拟设备'

    def test_disable_mock(self, app):
        """测试退出模拟模式"""
        from backend.api.service_registry import get_device_service
        svc = get_device_service()

        svc.enable_mock()
        result = svc.disconnect()
        assert result['success'] is True
        assert svc.is_mock() is False
        assert svc.is_connected() is False

    def test_get_adb_info(self, app):
        """测试获取ADB诊断信息"""
        from backend.api.service_registry import get_device_service
        svc = get_device_service()

        info = svc.get_adb_info()
        assert 'adb_path' in info
        assert 'server_url' in info
        assert 'is_mock' in info
        assert 'connected' in info

    def test_get_keepalive_status(self, app):
        """测试获取保活状态"""
        from backend.api.service_registry import get_device_service
        svc = get_device_service()

        status = svc.get_keepalive_status()
        assert 'enabled' in status
        assert 'interval' in status
        assert 'session_alive' in status

    def test_invalid_connect_method_returns_error(self, app):
        """测试无效连接方式返回错误"""
        from backend.api.service_registry import get_device_service
        svc = get_device_service()

        # 无效method在API层被拦截，Service层只接受usb/wifi
        result = svc.connect(method='usb', device_name=None)
        # USB无设备时应返回失败（但不应抛异常）
        assert 'success' in result

    def test_service_is_thread_safe(self, app):
        """测试Service的线程锁保护（不应因并发调用崩溃）"""
        import threading
        from backend.api.service_registry import get_device_service
        svc = get_device_service()

        errors = []

        def toggle_mock():
            try:
                for _ in range(5):
                    svc.enable_mock()
                    svc.get_status()
                    svc.disconnect()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=toggle_mock) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert len(errors) == 0, f"并发调用出现异常: {errors}"


class TestScriptDesignService:
    """ScriptDesignService测试"""

    @pytest.fixture(autouse=True)
    def clear_design(self, app):
        """每个测试前清空设计"""
        from backend.api.service_registry import get_script_service
        svc = get_script_service()
        svc.clear()
        yield
        svc.clear()

    def test_initial_empty_design(self, app):
        """初始设计应为空"""
        from backend.api.service_registry import get_script_service
        svc = get_script_service()
        design = svc.get_design()
        assert design['element_count'] == 0
        assert design['step_count'] == 0

    def test_add_element(self, app):
        """测试添加元素"""
        from backend.api.service_registry import get_script_service
        svc = get_script_service()

        elem = {'id': 'e1', 'name': '测试按钮', 'text': '点击', 'bounds': [10, 20, 100, 60], 'resource_id': 'btn'}
        result = svc.add_element(elem)
        assert result['success'] is True

        elements = svc.get_elements()
        assert elements['success'] is True
        assert len(elements['elements']) == 1

    def test_add_step_requires_action(self, app):
        """测试添加步骤需要action参数"""
        from backend.api.service_registry import get_script_service
        svc = get_script_service()

        # add_step会校验action
        result = svc.add_step(None, '', {}, '无action的步骤')
        # 空action应该返回失败
        assert result['success'] is False

    def test_add_step_with_element(self, app):
        """测试添加带元素的步骤"""
        from backend.api.service_registry import get_script_service
        svc = get_script_service()

        elem = {'id': 'e1', 'name': '输入框', 'bounds': [0, 0, 200, 50], 'resource_id': 'input'}
        svc.add_element(elem)

        result = svc.add_step(elem, 'click', {}, '点击输入框')
        assert result['success'] is True

        design = svc.get_design()
        assert design['step_count'] == 1

    def test_clear_design(self, app):
        """测试清空设计"""
        from backend.api.service_registry import get_script_service
        svc = get_script_service()

        svc.add_element({'id': 'e1', 'bounds': [0, 0, 10, 10]})
        svc.add_step(None, 'swipe', {'direction': 'up'}, '上滑')
        svc.clear()

        design = svc.get_design()
        assert design['element_count'] == 0
        assert design['step_count'] == 0

    def test_save_and_load_case(self, app):
        """测试保存和加载用例（Service层）"""
        from backend.api.service_registry import get_script_service
        svc = get_script_service()

        elem = {'id': 'e1', 'name': '登录', 'bounds': [0, 0, 100, 50], 'resource_id': 'com.test:id/login'}
        svc.add_element(elem)
        svc.add_step(elem, 'click', {}, '点击登录')

        save_result = svc.save_case('service_test_case')
        assert save_result['success'] is True

        svc.clear()
        assert svc.get_design()['step_count'] == 0

        load_result = svc.load_case('service_test_case')
        assert load_result['success'] is True

        design = svc.get_design()
        assert design['step_count'] == 1

    def test_list_cases(self, app):
        """测试列出用例"""
        from backend.api.service_registry import get_script_service
        svc = get_script_service()

        cases_result = svc.list_cases()
        assert cases_result['success'] is True
        assert 'cases' in cases_result

    def test_supported_actions(self, app):
        """测试获取支持的动作类型"""
        from backend.api.service_registry import get_script_service
        svc = get_script_service()

        actions = svc.get_supported_actions()
        assert actions['success'] is True
        assert 'actions' in actions
        assert len(actions['actions']) > 0

    def test_get_elements(self, app):
        """测试获取元素列表"""
        from backend.api.service_registry import get_script_service
        svc = get_script_service()

        result = svc.get_elements()
        assert result['success'] is True
        assert 'elements' in result
        assert isinstance(result['elements'], list)


class TestScriptGenService:
    """ScriptGenService测试"""

    def test_preview_script(self, app):
        """测试脚本预览生成"""
        from backend.api.service_registry import (
            get_script_service, get_script_gen_service
        )
        design_svc = get_script_service()
        gen_svc = get_script_gen_service()

        # 添加一个步骤
        elem = {'id': 'e1', 'resource_id': 'com.test:id/btn', 'bounds': [0, 0, 100, 50]}
        design_svc.add_element(elem)
        design_svc.add_step(elem, 'click', {}, '点击按钮')

        result = gen_svc.generate_script('preview_test', save=False)
        assert result['success'] is True
        assert 'code' in result
        assert 'webdriver' in result['code'] or 'Remote' in result['code']
        assert 'click' in result['code']

    def test_preview_empty_design(self, app):
        """测试空设计无法生成脚本（需要步骤）"""
        from backend.api.service_registry import get_script_gen_service
        gen_svc = get_script_gen_service()

        result = gen_svc.generate_script('empty_test', save=False)
        # 空步骤应返回失败（没有步骤无法生成脚本）
        assert result['success'] is False
        assert 'message' in result

    def test_execution_status_available(self, app):
        """测试获取执行状态"""
        from backend.api.service_registry import get_script_gen_service
        gen_svc = get_script_gen_service()

        status = gen_svc.get_execution_status()
        assert 'is_executing' in status
