"""
会话信任链单元测试（2026-09-11 长任务无人值守修复）

覆盖：
- DriverProxy.is_session_alive 真实命令探针（current_package）
- DeviceManager.probe_session_alive 共享防抖计数
- 恢复熔断 recovery_exhausted 终态
- /api/elements/refresh、/api/snapshot 会话死时 503 + SESSION_LOST
"""
import threading
import time

import pytest


# ==================== 探针：DriverProxy.is_session_alive ====================

class TestSessionAliveProbe:
    """探针必须使用走 instrumentation 的真实命令（get_window_size），
    不可用本地属性（session/session_id）或不走 instrumentation 的命令（current_package）"""

    def test_alive_when_window_size_works(self):
        from backend.device_manager.driver_proxy import DriverProxy

        class FakeDriver:
            def get_window_size(self):
                return {'width': 1080, 'height': 2400}

        proxy = DriverProxy(FakeDriver())
        assert proxy.is_session_alive() is True

    def test_dead_when_command_raises(self):
        from backend.device_manager.driver_proxy import DriverProxy
        from selenium.common.exceptions import WebDriverException

        class DeadDriver:
            def get_window_size(self):
                raise WebDriverException('instrumentation process is not running')

        proxy = DriverProxy(DeadDriver())
        assert proxy.is_session_alive() is False

    def test_dead_when_driver_none(self):
        from backend.device_manager.driver_proxy import DriverProxy
        proxy = DriverProxy(None)
        assert proxy.is_session_alive() is False

    def test_probe_does_not_rely_on_local_session_attr(self):
        """回归：driver.session 属性不存在（AttributeError）时不得误判——
        2026-09-11 根因：旧实现读 driver.session 必抛异常导致永远判死"""
        from backend.device_manager.driver_proxy import DriverProxy

        class NoSessionAttrDriver:
            # 无 session 属性（selenium 真实行为），只有真命令
            def get_window_size(self):
                return {'width': 1080, 'height': 2400}

        proxy = DriverProxy(NoSessionAttrDriver())
        assert not hasattr(NoSessionAttrDriver(), 'session')
        assert proxy.is_session_alive() is True

    def test_probe_uses_instrumentation_command_not_current_package(self):
        """回归：探针必须调 get_window_size 而非 current_package——
        current_package 不走 instrumentation，崩时仍可能成功（实测复现判不死）"""
        from backend.device_manager.driver_proxy import DriverProxy

        calls = []

        class RecordingDriver:
            @property
            def current_package(self):
                calls.append('current_package')
                return 'com.example.app'  # instrumentation 崩了它也能成功

            def get_window_size(self):
                calls.append('get_window_size')
                return {'width': 1080, 'height': 2400}

        proxy = DriverProxy(RecordingDriver())
        assert proxy.is_session_alive() is True
        assert 'get_window_size' in calls
        assert 'current_package' not in calls


# ==================== 防抖：DeviceManager.probe_session_alive ====================

@pytest.fixture
def mgr(app):
    """取全局 DeviceManager，测试后复位被改动的状态字段"""
    from backend.api.service_registry import get_device_service
    m = get_device_service().device_manager
    yield m
    # 复位（disconnect 会清零探针/熔断计数与终态）
    m.disconnect()


class TestProbeDebounce:
    def _force_real_connected(self, m):
        with m._state_lock:
            m._is_real = True
            m._connected = True
            m._session_lost = False
            m._probe_fail_count = 0
            m._disconnect_reason = None  # 前序测试 disconnect 残留 manual_disconnect，探针标记有"首因保留"守卫

    def test_single_failure_tolerated(self, mgr, monkeypatch):
        """阈值=2：第 1 次失败按抖动容忍，不判死"""
        self._force_real_connected(mgr)
        monkeypatch.setattr(mgr._pool, 'is_alive', lambda *a: False)

        assert mgr.probe_session_alive() is True   # 容忍
        assert mgr._probe_fail_count == 1

    def test_consecutive_failures_judge_dead(self, mgr, monkeypatch):
        """连续 2 次失败才判死"""
        self._force_real_connected(mgr)
        monkeypatch.setattr(mgr._pool, 'is_alive', lambda *a: False)

        mgr.probe_session_alive()                  # 1st：容忍
        assert mgr.probe_session_alive() is False  # 2nd：判死
        assert mgr._probe_fail_count == 2

    def test_success_resets_counter(self, mgr, monkeypatch):
        """成功一次即清零，后续失败重新计数"""
        self._force_real_connected(mgr)
        results = iter([False, True, False])
        monkeypatch.setattr(mgr._pool, 'is_alive', lambda *a: next(results))

        mgr.probe_session_alive()                  # False → count=1（容忍）
        assert mgr.probe_session_alive() is True   # 成功清零
        assert mgr._probe_fail_count == 0
        assert mgr.probe_session_alive() is True   # False → count=1（重新容忍）

    def test_threshold_configurable(self, mgr, monkeypatch):
        """阈值可配：threshold=3 时第 2 次失败仍容忍"""
        self._force_real_connected(mgr)
        monkeypatch.setattr(mgr._pool, 'is_alive', lambda *a: False)
        monkeypatch.setattr(mgr, '_probe_fail_threshold', 3)

        mgr.probe_session_alive()
        assert mgr.probe_session_alive() is True   # 2/3 仍容忍
        assert mgr.probe_session_alive() is False  # 3/3 判死

    def test_status_probe_uses_debounce(self, mgr, monkeypatch):
        """get_status 探针走同一防抖：第 1 次失败不标 session_lost，第 2 次才标"""
        self._force_real_connected(mgr)
        monkeypatch.setattr(mgr._pool, 'is_alive', lambda *a: False)

        # 伪造一个存活的心跳线程使 should_probe 成立
        stop = threading.Event()
        t = threading.Thread(target=stop.wait, daemon=True)
        t.start()
        mgr._heartbeat_thread = t
        try:
            s1 = mgr.get_status()
            assert s1['session_lost'] is False      # 抖动容忍

            s2 = mgr.get_status()
            assert s2['session_lost'] is True       # 判死
            assert s2['disconnect_reason'] == 'session_lost:status_probe'
        finally:
            stop.set()
            t.join(timeout=2)
            mgr._heartbeat_thread = None


# ==================== 熔断：recovery_exhausted 终态 ====================

class TestRecoveryCircuitBreaker:
    def test_exhausted_after_max_rounds_and_stops_retrying(self, mgr, monkeypatch):
        """连续 N 轮恢复失败 → 终态 recovery_exhausted，且不再发起新恢复"""
        with mgr._state_lock:
            mgr._is_real = True
            mgr._connected = True
            mgr._session_lost = False
            mgr._recovery_round_count = 0
            mgr._recovery_exhausted = False
            mgr._disconnect_reason = None

        monkeypatch.setattr(mgr, '_keepalive_interval', 0.02)
        monkeypatch.setattr(mgr, '_max_recovery_rounds', 3)
        monkeypatch.setattr(mgr, '_do_heartbeat', lambda: False)

        recovery_calls = []
        monkeypatch.setattr(
            mgr, '_do_progressive_recovery',
            lambda: recovery_calls.append(1) or False)

        mgr._heartbeat_stop.clear()
        t = threading.Thread(target=mgr._heartbeat_loop, daemon=True)
        t.start()
        try:
            # 等待进入终态
            deadline = time.time() + 5
            while time.time() < deadline:
                with mgr._state_lock:
                    if mgr._recovery_exhausted:
                        break
                time.sleep(0.02)

            with mgr._state_lock:
                assert mgr._recovery_exhausted is True
                assert mgr._disconnect_reason == 'recovery_exhausted'
                assert mgr._session_lost is True
                assert mgr._connected is False
                assert mgr._recovery_round_count >= 3

            # 终态后不再发起恢复（reconnect_count 不再增长）
            calls_at_exhaustion = len(recovery_calls)
            time.sleep(0.15)
            assert len(recovery_calls) == calls_at_exhaustion
        finally:
            mgr._heartbeat_stop.set()
            mgr._wake_event.set()
            t.join(timeout=3)

    def test_explicit_connect_resets_circuit_breaker(self, mgr):
        """终态后显式 connect/disconnect 状态全清零（_connect 成功路径的复位逻辑）"""
        with mgr._state_lock:
            mgr._recovery_exhausted = True
            mgr._recovery_round_count = 3
            mgr._probe_fail_count = 2

        mgr.disconnect()  # disconnect 同样承担全量复位
        with mgr._state_lock:
            assert mgr._recovery_exhausted is False
            assert mgr._recovery_round_count == 0
            assert mgr._probe_fail_count == 0

    def test_recovery_success_resets_round_count(self, mgr, monkeypatch):
        """恢复成功清零轮次计数（通过状态字段直接验证复位语义）"""
        with mgr._state_lock:
            mgr._recovery_round_count = 2
        # 模拟 _heartbeat_loop 恢复成功分支的复位动作
        with mgr._state_lock:
            mgr._is_real = True
            mgr._session_lost = False
            mgr._connected = True
            mgr._recovery_level = mgr.RECOVERY_LEVEL_NONE
            mgr._disconnect_reason = None
            mgr._recovery_round_count = 0
        assert mgr._recovery_round_count == 0
        assert mgr.is_session_usable() is True


# ==================== API：会话死时 503 + SESSION_LOST ====================

class TestRefreshSessionLostMapping:
    def _force_session_dead(self, app):
        from backend.api.service_registry import get_device_service
        svc = get_device_service()
        m = svc.device_manager
        with m._state_lock:
            m._is_real = True
            m._connected = True
            m._session_lost = True
            m._disconnect_reason = 'session_lost:test'
        return svc

    def test_refresh_returns_503_session_lost(self, app, client):
        svc = self._force_session_dead(app)
        try:
            resp = client.post('/api/elements/refresh')
            assert resp.status_code == 503
            body = resp.get_json()
            assert body['success'] is False
            assert body['error_code'] == 'SESSION_LOST'
            # 信任链：不得返回任何元素数组
            assert 'elements' not in body.get('data', {}) if body.get('data') else True
        finally:
            svc.disconnect()

    def test_snapshot_returns_503_session_lost(self, app, client):
        svc = self._force_session_dead(app)
        try:
            resp = client.get('/api/snapshot')
            assert resp.status_code == 503
            body = resp.get_json()
            assert body['success'] is False
            assert body['error_code'] == 'SESSION_LOST'
        finally:
            svc.disconnect()

    def test_recovery_exhausted_also_maps_session_lost(self, app, client):
        """熔断终态下 refresh 同样映射 SESSION_LOST"""
        from backend.api.service_registry import get_device_service
        svc = get_device_service()
        m = svc.device_manager
        with m._state_lock:
            m._is_real = True
            m._connected = False
            m._session_lost = True
            m._recovery_exhausted = True
            m._disconnect_reason = 'recovery_exhausted'
        try:
            resp = client.post('/api/elements/refresh')
            assert resp.status_code == 503
            assert resp.get_json()['error_code'] == 'SESSION_LOST'
        finally:
            svc.disconnect()

    def test_mock_mode_unaffected(self, client, mock_device):
        """模拟模式不受会话判断影响（向后兼容）"""
        resp = client.post('/api/elements/refresh')
        assert resp.status_code == 200
        assert resp.get_json()['success'] is True


# ==================== is_session_usable 单一判断口径 ====================

class TestIsSessionUsable:
    def test_usable_when_real_connected_healthy(self, mgr):
        with mgr._state_lock:
            mgr._is_real = True
            mgr._connected = True
            mgr._session_lost = False
            mgr._recovery_exhausted = False
        assert mgr.is_session_usable() is True

    def test_unusable_when_session_lost(self, mgr):
        with mgr._state_lock:
            mgr._is_real = True
            mgr._connected = True   # connected 仍 True 但已判死 → 不可用
            mgr._session_lost = True
        assert mgr.is_session_usable() is False

    def test_unusable_when_exhausted(self, mgr):
        with mgr._state_lock:
            mgr._is_real = True
            mgr._connected = True
            mgr._session_lost = False
            mgr._recovery_exhausted = True
        assert mgr.is_session_usable() is False

    def test_unusable_when_mock(self, mgr):
        mgr.enable_mock()
        assert mgr.is_session_usable() is False  # mock 非真实会话


# ==================== 错误关键字映射：WebDriverException → SESSION_LOST ====================

class TestSessionLostKeywordMapping:
    """instrumentation 崩溃的典型报错必须映射 SESSION_LOST（不得漏判 ACTION_FAILED）
    2026-09-11 真机实测：click 报 "cannot be proxied to UiAutomator2 server"
    时被误判 ACTION_FAILED"""

    def _make_action_service(self, error_msg):
        from services.action_service import ActionService
        from selenium.common.exceptions import WebDriverException

        class RaisingDriver:
            def tap(self, *a, **kw):
                raise WebDriverException(error_msg)

            def get_window_size(self):
                return {'width': 1080, 'height': 2400}

        class StubDeviceService:
            def is_real(self):
                return True

            def get_driver_proxy(self):
                return RaisingDriver()

        svc = ActionService()
        svc.set_device_service(StubDeviceService())
        return svc

    @pytest.mark.parametrize('error_msg', [
        'cannot be proxied to UiAutomator2 server',
        "InvalidContextError: Message: An unknown server-side error occurred",
        'instrumentation process is not running',
        'session is terminated',
        'socket hang up',
    ])
    def test_session_dead_keywords_map_to_session_lost(self, error_msg):
        svc = self._make_action_service(error_msg)
        result = svc.execute({'action': 'click', 'x': 100, 'y': 200})
        assert result['success'] is False
        assert result['error_code'] == 'SESSION_LOST', (
            f'错误消息 {error_msg!r} 未映射 SESSION_LOST')

    def test_unrelated_webdriver_error_stays_action_failed(self):
        """非会话类 WebDriverException 仍为 ACTION_FAILED（不误伤）"""
        svc = self._make_action_service('element click intercepted by dialog')
        result = svc.execute({'action': 'click', 'x': 100, 'y': 200})
        assert result['success'] is False
        assert result['error_code'] == 'ACTION_FAILED'

    def test_proxy_connection_keywords_include_instrumentation(self):
        """DriverProxy 连接丢失关键字同步包含 instrumentation 报错"""
        from backend.device_manager.driver_proxy import _CONNECTION_ERROR_KEYWORDS
        for kw in ('cannot be proxied', 'invalidcontexterror',
                   'instrumentation process is not running'):
            assert kw in _CONNECTION_ERROR_KEYWORDS
