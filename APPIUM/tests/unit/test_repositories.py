"""
Repository层单元测试
测试TestCaseRepository（JSON模式）、DeviceRepository、ElementRepository
"""
import os
import json
import tempfile
import shutil
import pytest


class TestTestCaseRepositoryJson:
    """TestCaseRepository JSON存储模式测试"""

    @pytest.fixture
    def case_dir(self, tmp_path):
        """临时JSON用例目录"""
        d = tmp_path / "test_cases"
        d.mkdir()
        return str(d)

    @pytest.fixture
    def repo(self, case_dir):
        from backend.repositories.test_case_repository import TestCaseRepository
        return TestCaseRepository(test_cases_dir=case_dir, db=None)

    def test_save_and_load_case(self, repo):
        """测试保存和加载用例"""
        elements = [{'id': 'e1', 'name': '按钮', 'resource_id': 'com.test:id/btn'}]
        steps = [{'step_id': 's1', 'action': 'click', 'element': elements[0], 'description': '点击按钮'}]

        result = repo.save_case('test_login', elements, steps)
        assert result['success'] is True

        loaded = repo.load_case('test_login')
        assert loaded['success'] is True
        design = loaded['design']
        assert design['element_count'] == 1
        assert design['step_count'] == 1

    def test_list_cases(self, repo):
        """测试列出用例"""
        repo.save_case('case_a', [], [])
        repo.save_case('case_b', [], [])

        result = repo.list_cases()
        assert result['success'] is True
        names = [c['name'] for c in result['cases']]
        assert 'case_a' in names
        assert 'case_b' in names
        assert result['count'] >= 2

    def test_load_nonexistent_case(self, repo):
        """测试加载不存在的用例"""
        result = repo.load_case('nonexistent_case_xyz')
        assert result['success'] is False

    def test_save_overwrites_existing(self, repo):
        """测试保存同名用例覆盖"""
        repo.save_case('overwrite_test', [{'id': 'e1'}], [])
        repo.save_case('overwrite_test', [{'id': 'e2'}, {'id': 'e3'}], [])

        loaded = repo.load_case('overwrite_test')
        assert loaded['design']['element_count'] == 2

    def test_case_persists_to_disk(self, repo, case_dir):
        """测试JSON文件确实写入磁盘"""
        repo.save_case('disk_test', [{'id': 'e1'}], [{'step_id': 's1', 'action': 'click'}])

        json_path = os.path.join(case_dir, 'disk_test.json')
        assert os.path.exists(json_path)

        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        assert 'elements' in data
        assert 'steps' in data


class TestDeviceRepository:
    """DeviceRepository测试（使用DB或JSON回退）"""

    @pytest.fixture
    def repo(self, app):
        """从app config获取device repo，如果不可用则用内存模式"""
        try:
            return app.config['DEVICE_REPO']
        except (KeyError, RuntimeError):
            # fallback: create standalone with no db
            from backend.repositories.device_repository import DeviceRepository
            return DeviceRepository(db=None)

    def test_save_and_get_device(self, repo):
        """测试保存和查询设备"""
        device_info = {
            'udid': 'test-device-001',
            'name': '测试手机',
            'platform': 'Android',
            'version': '13',
            'status': 'online'
        }
        result = repo.save_device(device_info)
        assert result['success'] is True

        found = repo.get_device_by_udid('test-device-001')
        assert found is not None
        assert found['udid'] == 'test-device-001'

    def test_list_devices(self, repo):
        """测试列出设备"""
        repo.save_device({'udid': 'dev-a', 'name': 'A', 'platform': 'Android', 'status': 'online'})
        repo.save_device({'udid': 'dev-b', 'name': 'B', 'platform': 'Android', 'status': 'offline'})

        devices = repo.list_devices()
        assert isinstance(devices, list)
        udids = [d['udid'] for d in devices]
        assert 'dev-a' in udids
        assert 'dev-b' in udids

    def test_update_device_status(self, repo):
        """测试更新设备状态"""
        repo.save_device({'udid': 'dev-status', 'name': 'Status Test', 'platform': 'Android', 'status': 'online'})

        ok = repo.update_device_status('dev-status', 'error')
        assert ok is True

        found = repo.get_device_by_udid('dev-status')
        assert found is not None


class TestElementRepository:
    """ElementRepository测试"""

    @pytest.fixture
    def repo(self, app):
        try:
            return app.config['ELEMENT_REPO']
        except (KeyError, RuntimeError):
            from backend.repositories.element_repository import ElementRepository
            return ElementRepository(db=None)

    def test_save_and_get_snapshot(self, repo):
        """测试保存和获取元素快照"""
        elements = [
            {'id': 'e1', 'name': '按钮1', 'bounds': [0, 0, 100, 50], 'resource_id': 'btn1'},
            {'id': 'e2', 'name': '输入框', 'bounds': [0, 60, 300, 100], 'resource_id': 'input1'}
        ]
        result = repo.save_snapshot(
            device_id=None,
            elements=elements,
            screenshot_path='/tmp/test.png',
            screen_width=1080,
            screen_height=2400,
            package_name='com.test',
            activity_name='.MainActivity'
        )
        assert result['success'] is True

        latest = repo.get_latest_snapshot()
        assert latest is not None

    def test_list_snapshots(self, repo):
        """测试列出快照"""
        repo.save_snapshot(None, [{'id': 'e1'}], package_name='com.a')
        repo.save_snapshot(None, [{'id': 'e2'}], package_name='com.b')

        snapshots = repo.list_snapshots(limit=10)
        assert isinstance(snapshots, list)
        assert len(snapshots) >= 2

    def test_save_and_list_element_maps(self, repo):
        """测试保存和列出元素定位器"""
        repo.save_element_map('提交按钮', xpath='//button[@text="提交"]', resource_id='com.test:id/submit')
        repo.save_element_map('用户名输入框', xpath='//input[@id="username"]')

        maps = repo.list_element_maps()
        assert isinstance(maps, list)
        names = [m['name'] for m in maps]
        assert '提交按钮' in names

    def test_delete_element_map(self, repo):
        """测试删除元素定位器"""
        repo.save_element_map('待删除', xpath='//delete')
        ok = repo.delete_element_map('待删除')
        assert ok is True

        maps = repo.list_element_maps()
        names = [m['name'] for m in maps]
        assert '待删除' not in names
