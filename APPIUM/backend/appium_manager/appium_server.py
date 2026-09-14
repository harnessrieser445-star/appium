"""
Appium Server生命周期管理模块
Phase 4: 修复Windows appium.cmd检测、进程stdin DEVNULL、健康检查缓存、优雅关闭
"""
import os
import time
import subprocess
import threading
import urllib.request
import urllib.error
import json
from typing import Optional, Dict, Any, Tuple

from backend.utils.logger import get_logger

logger = get_logger(__name__)


class AppiumServer:
    """管理Appium Server进程的生命周期"""

    # 健康检查缓存TTL（秒）- 避免频繁HTTP请求
    _HEALTH_CACHE_TTL = 2.0

    # Server日志滚动阈值（字节），超过则在下次启动时滚动为 .old
    _LOG_MAX_BYTES = 10 * 1024 * 1024  # 10MB

    def __init__(
        self,
        host: str = '127.0.0.1',
        port: int = 4723,
        auto_start: bool = True
    ):
        self._host = host
        self._port = port
        self._auto_start = auto_start
        self._process: Optional[subprocess.Popen] = None
        self._started_by_us = False
        self._lock = threading.Lock()

        # Server日志文件句柄（Phase 5：输出重定向到文件，替代无人消费的PIPE）
        self._log_file = None
        self._log_path = None

        # 健康检查缓存
        self._health_cache: Optional[bool] = None
        self._health_cache_time: float = 0.0

    @property
    def server_url(self) -> str:
        return f'http://{self._host}:{self._port}'

    @property
    def is_running(self) -> bool:
        """检查Appium Server是否正在运行（带缓存）"""
        return self.check_health()

    @property
    def port(self) -> int:
        return self._port

    @property
    def host(self) -> str:
        return self._host

    def check_health(self, force: bool = False) -> bool:
        """
        检测Appium Server是否可用

        Args:
            force: 是否跳过缓存强制检测
        """
        now = time.time()
        if not force and self._health_cache is not None and (now - self._health_cache_time) < self._HEALTH_CACHE_TTL:
            return self._health_cache

        result = self._check_server_health()
        self._health_cache = result
        self._health_cache_time = now
        return result

    def get_server_info(self) -> Dict[str, Any]:
        """
        获取Appium Server状态信息

        Returns:
            {'running': bool, 'url': str, 'started_by_us': bool, 'pid': Optional[int]}
        """
        running = self.check_health(force=True)
        info = {
            'running': running,
            'url': self.server_url,
            'started_by_us': self._started_by_us,
        }
        if self._process and self._process.poll() is None:
            info['pid'] = self._process.pid
        else:
            info['pid'] = None
        return info

    def ensure_running(self, timeout: float = 30) -> Dict[str, Any]:
        """
        确保Appium Server正在运行。
        如果未运行且auto_start=True，则启动Server。

        Args:
            timeout: 等待Server启动的超时秒数

        Returns:
            {success, message, already_running}
        """
        with self._lock:
            # 1. 先检查是否已在运行（强制检测）
            if self.check_health(force=True):
                return {
                    'success': True,
                    'message': f'Appium Server已在运行 {self.server_url}',
                    'already_running': True
                }

            if not self._auto_start:
                return {
                    'success': False,
                    'message': f'Appium Server未运行 {self.server_url}，且auto_start=False',
                    'already_running': False
                }

            # 2. 尝试启动Server
            return self._start_server(timeout)

    def restart(self, timeout: float = 30) -> Dict[str, Any]:
        """
        重启Appium Server

        Returns:
            {success, message}
        """
        with self._lock:
            logger.info('[AppiumServer] 正在重启Appium Server...')

            # 停止我们启动的进程
            self._stop_server_process()

            # 等待端口释放
            self._wait_port_free(max_wait=10)

            # 启动新进程
            return self._start_server(timeout)

    def stop(self):
        """停止我们启动的Appium Server进程"""
        with self._lock:
            self._stop_server_process()

    # ---------- 内部方法 ----------

    def _check_server_health(self) -> bool:
        """通过HTTP请求检测Appium Server是否可用"""
        try:
            url = f'{self.server_url}/status'
            req = urllib.request.Request(url, method='GET')
            with urllib.request.urlopen(req, timeout=3) as resp:
                if resp.status != 200:
                    return False
                # 验证响应确实是Appium（包含value.ready字段）
                data = json.loads(resp.read().decode('utf-8', errors='replace'))
                return isinstance(data, dict) and 'value' in data
        except Exception:
            return False

    def _wait_port_free(self, max_wait: float = 10):
        """等待端口释放"""
        import socket
        start = time.time()
        while time.time() - start < max_wait:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(0.5)
                    result = s.connect_ex((self._host, self._port))
                    if result != 0:  # 端口已释放
                        return
            except Exception:
                pass
            time.sleep(0.5)
        logger.warning(f'[AppiumServer] 端口{self._port}等待{max_wait}s未释放')

    def _find_appium_command(self) -> Optional[str]:
        """查找appium可执行命令"""
        import shutil

        # Windows: appium.cmd; Unix: appium
        candidates = ['appium.cmd', 'appium'] if os.name == 'nt' else ['appium']

        for cmd_name in candidates:
            path = shutil.which(cmd_name)
            if path:
                logger.debug(f'[AppiumServer] 找到appium: {path}')
                return path

        # 检查npm全局安装的node_modules/.bin
        npm_prefix = None
        try:
            npm_cmd = 'npm.cmd' if os.name == 'nt' else 'npm'
            result = subprocess.run(
                [npm_cmd, 'prefix', '-g'],
                capture_output=True, text=True, timeout=10,
                stdin=subprocess.DEVNULL
            )
            if result.returncode == 0:
                npm_prefix = result.stdout.strip()
                if os.name == 'nt':
                    candidate = os.path.join(npm_prefix, 'appium.cmd')
                else:
                    candidate = os.path.join(npm_prefix, 'bin', 'appium')
                if os.path.isfile(candidate):
                    logger.debug(f'[AppiumServer] 找到npm全局appium: {candidate}')
                    return candidate
        except Exception as e:
            logger.debug(f'[AppiumServer] npm prefix查询失败: {e}')

        # 检查项目node_modules
        try:
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            local_appium = os.path.join(project_root, 'node_modules', '.bin',
                                        'appium.cmd' if os.name == 'nt' else 'appium')
            if os.path.isfile(local_appium):
                return local_appium
        except Exception:
            pass

        return None

    def _start_server(self, timeout: float) -> Dict[str, Any]:
        """启动Appium Server进程（调用方需持有_lock）"""
        appium_cmd = self._find_appium_command()
        if not appium_cmd:
            return {
                'success': False,
                'message': '未找到appium命令，请确保已安装Appium（npm install -g appium）',
                'already_running': False
            }

        try:
            # 设置APPIUM_HOME到项目内的data目录，避免用户目录权限和文件冲突
            from backend.utils.paths import DATA_DIR
            appium_home = DATA_DIR / '.appium'
            appium_home.mkdir(parents=True, exist_ok=True)
            
            # 准备环境变量
            env = os.environ.copy()
            env['APPIUM_HOME'] = str(appium_home)
            
            # 构建启动参数
            cmd = [
                appium_cmd,
                '--address', self._host,
                '--port', str(self._port),
                '--relaxed-security',
                '--log-level', 'warn',  # 减少日志噪音
            ]
            logger.info(f'[AppiumServer] 启动命令: {" ".join(cmd)}')
            logger.info(f'[AppiumServer] APPIUM_HOME: {appium_home}')

            # Phase 5: stdout/stderr重定向到日志文件。
            # 原实现用PIPE但无人消费，Windows管道缓冲(~64KB)写满后
            # node进程阻塞在写日志上，导致Server整体假死（"时不时断连"根因）。
            log_file = self._prepare_log_file()
            self._process = subprocess.Popen(
                cmd,
                stdout=log_file,
                stderr=subprocess.STDOUT,  # 合并stderr到stdout
                stdin=subprocess.DEVNULL,
                env=env,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            self._started_by_us = True

            # 等待Server就绪
            start_time = time.time()
            last_warn_time = 0
            while time.time() - start_time < timeout:
                if self._check_server_health():
                    self._health_cache = True
                    self._health_cache_time = time.time()
                    logger.info(f'[AppiumServer] Appium Server已启动: {self.server_url} (pid={self._process.pid})')
                    return {
                        'success': True,
                        'message': f'Appium Server已启动: {self.server_url}',
                        'already_running': False,
                        'pid': self._process.pid
                    }

                # 检查进程是否意外退出
                if self._process.poll() is not None:
                    # 诊断信息改从日志文件尾部读取（输出已重定向到文件）
                    self._close_log_file()
                    err_output = self._read_log_tail(8192).strip()[:800]
                    self._process = None
                    self._started_by_us = False
                    logger.error(f'[AppiumServer] Server启动失败，进程已退出: {err_output}')
                    return {
                        'success': False,
                        'message': f'Appium Server启动失败: {err_output or "进程意外退出"}',
                        'already_running': False
                    }

                # 每5秒输出一次等待日志
                elapsed = time.time() - start_time
                if elapsed - last_warn_time >= 5:
                    logger.debug(f'[AppiumServer] 等待Server就绪... ({elapsed:.0f}s/{timeout}s)')
                    last_warn_time = elapsed

                time.sleep(1)

            # 超时
            self._stop_server_process()
            logger.error(f'[AppiumServer] Server启动超时 ({timeout}s)')
            return {
                'success': False,
                'message': f'Appium Server启动超时（{timeout}s），请检查端口{self._port}是否被占用',
                'already_running': False
            }

        except Exception as e:
            logger.error(f'[AppiumServer] 启动异常: {e}', exc_info=True)
            self._close_log_file()
            self._process = None
            self._started_by_us = False
            return {
                'success': False,
                'message': f'启动Appium Server异常: {str(e)}',
                'already_running': False
            }

    def _stop_server_process(self):
        """停止我们管理的Server进程（调用方需持有_lock）"""
        if self._process and self._started_by_us:
            pid = self._process.pid
            logger.info(f'[AppiumServer] 正在停止Appium Server进程 (pid={pid})...')
            try:
                # 先尝试terminate（SIGTERM）
                self._process.terminate()
                try:
                    self._process.wait(timeout=5)
                    logger.info(f'[AppiumServer] Server进程已终止 (pid={pid})')
                except subprocess.TimeoutExpired:
                    # 5秒未响应则kill（SIGKILL）
                    logger.warning(f'[AppiumServer] Server进程{pid}未响应terminate，强制kill')
                    self._process.kill()
                    try:
                        self._process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        logger.error(f'[AppiumServer] Server进程{pid}无法终止')
            except Exception as e:
                logger.warning(f'[AppiumServer] 停止进程异常: {e}')

            # 关闭日志文件句柄（子进程已终止，可安全关闭）
            self._close_log_file()

            self._process = None
            self._started_by_us = False
            self._health_cache = None
            self._health_cache_time = 0

    # ---------- Server日志文件管理（Phase 5） ----------

    def _get_log_path(self):
        """获取Server日志文件路径（data/logs/appium_server.log）"""
        if self._log_path is None:
            from backend.utils.paths import DATA_DIR
            log_dir = DATA_DIR / 'logs'
            log_dir.mkdir(parents=True, exist_ok=True)
            self._log_path = log_dir / 'appium_server.log'
        return self._log_path

    def _prepare_log_file(self):
        """
        打开Server日志文件供Popen使用。
        超过_LOG_MAX_BYTES时先滚动为 .old（只保留一份历史），避免无限增长。
        """
        log_path = self._get_log_path()
        try:
            if log_path.exists() and log_path.stat().st_size > self._LOG_MAX_BYTES:
                old_path = log_path.with_suffix('.log.old')
                try:
                    os.replace(str(log_path), str(old_path))
                    logger.info(f'[AppiumServer] 日志已滚动: {old_path}')
                except OSError:
                    pass  # 滚动失败则继续追加，不阻塞启动
        except Exception:
            pass

        self._close_log_file()  # 防御：确保旧句柄已关闭
        self._log_file = open(str(log_path), 'ab', buffering=0)
        return self._log_file

    def _close_log_file(self):
        """关闭日志文件句柄（幂等）"""
        if self._log_file is not None:
            try:
                self._log_file.close()
            except Exception:
                pass
            self._log_file = None

    def _read_log_tail(self, nbytes: int = 8192) -> str:
        """读取Server日志文件尾部，用于启动失败诊断"""
        try:
            log_path = self._get_log_path()
            if not log_path.exists():
                return ''
            size = log_path.stat().st_size
            with open(str(log_path), 'rb') as f:
                if size > nbytes:
                    f.seek(-nbytes, os.SEEK_END)
                return f.read().decode('utf-8', errors='replace')
        except Exception:
            return ''
