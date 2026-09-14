"""
DriverProxy模块
Phase 4: 修复属性/方法区分、重试延迟、空driver保护、安全查找方法
解决：StaleElementReferenceException、socket hang up等问题
"""
import functools
import time
from typing import Optional, Callable, Any, List

from selenium.common.exceptions import (
    StaleElementReferenceException,
    WebDriverException,
    NoSuchElementException,
    TimeoutException,
    InvalidSessionIdException,
)

from backend.utils.logger import get_logger

logger = get_logger(__name__)

# 需要重试的瞬态异常（元素状态变化、临时连接问题）
_RETRYABLE_EXCEPTIONS = (
    StaleElementReferenceException,
    ConnectionError,
    ConnectionRefusedError,
    ConnectionResetError,
    TimeoutError,
)

# 连接级错误关键词（触发连接丢失回调）
_CONNECTION_ERROR_KEYWORDS = (
    'socket hang up',
    'connection refused',
    'connection reset',
    'broken pipe',
    'session not found',
    'invalid session id',
    'session is terminated',
    'failed to connect',
    'could not proxy',
    'max retries exceeded',
    'connection aborted',
    'eof occurred',
    # 2026-09-11 真机实测补全：instrumentation 崩溃时的典型报错
    'cannot be proxied',
    'invalidcontexterror',
    'instrumentation process is not running',
)

# 重试初始延迟（秒），指数退避
_BASE_RETRY_DELAY = 0.5

# 不应该被重试的方法（查询类方法重试无意义）
_NO_RETRY_METHODS = {
    'get_screenshot_as_png', 'get_screenshot_as_file',
    'page_source', 'current_activity', 'current_package',
    'get_window_size', 'get_window_rect',
    'capabilities', 'session',
}


def _is_connection_error(e: Exception) -> bool:
    """判断是否为连接级错误"""
    msg = str(e).lower()
    return any(kw in msg for kw in _CONNECTION_ERROR_KEYWORDS)


class DriverProxy:
    """
    WebDriver代理类

    通过__getattr__代理原始driver的所有方法和属性，
    并对常见操作添加重试逻辑。

    Phase 4修复：
    - 正确区分方法（包装重试）和属性（直接访问）
    - 添加重试延迟避免级联故障
    - __setattr__空driver保护
    - 安全查找方法find_element_safe/find_elements_safe
    - 连接丢失回调只触发一次
    """

    def __init__(self, driver, max_retries: int = 2,
                 retry_delay: float = _BASE_RETRY_DELAY,
                 on_connection_lost: Optional[Callable] = None):
        """
        Args:
            driver: 原始Appium WebDriver实例（可以为None）
            max_retries: 最大重试次数
            retry_delay: 初始重试延迟（秒，指数退避）
            on_connection_lost: 连接丢失时的回调函数
        """
        object.__setattr__(self, '_driver', driver)
        object.__setattr__(self, '_max_retries', max_retries)
        object.__setattr__(self, '_retry_delay', retry_delay)
        object.__setattr__(self, '_on_connection_lost', on_connection_lost)
        object.__setattr__(self, '_connection_lost', False)
        object.__setattr__(self, '_connection_callback_fired', False)

    @property
    def raw_driver(self):
        """获取原始driver（谨慎使用）"""
        return object.__getattribute__(self, '_driver')

    @property
    def is_connection_lost(self) -> bool:
        return object.__getattribute__(self, '_connection_lost')

    @property
    def is_available(self) -> bool:
        """driver是否可用（非None且未标记连接丢失）"""
        d = object.__getattribute__(self, '_driver')
        lost = object.__getattribute__(self, '_connection_lost')
        return d is not None and not lost

    def mark_connection_lost(self):
        """标记连接已丢失"""
        object.__setattr__(self, '_connection_lost', True)

    def replace_driver(self, new_driver):
        """替换底层driver（重连后调用）"""
        object.__setattr__(self, '_driver', new_driver)
        object.__setattr__(self, '_connection_lost', False)
        object.__setattr__(self, '_connection_callback_fired', False)
        logger.info('[DriverProxy] Driver已替换，连接状态重置')

    def _fire_connection_lost(self, error: Exception):
        """触发连接丢失回调（只触发一次）"""
        fired = object.__getattribute__(self, '_connection_callback_fired')
        if fired:
            return
        object.__setattr__(self, '_connection_callback_fired', True)
        object.__setattr__(self, '_connection_lost', True)

        cb = object.__getattribute__(self, '_on_connection_lost')
        if cb:
            try:
                cb(error)
            except Exception as cb_err:
                logger.warning(f'[DriverProxy] 连接丢失回调异常: {cb_err}')

    def _wrap_method(self, name: str):
        """包装driver方法，添加重试逻辑"""
        max_retries = object.__getattribute__(self, '_max_retries')
        base_delay = object.__getattribute__(self, '_retry_delay')

        # 某些方法不需要重试
        if name in _NO_RETRY_METHODS:
            effective_retries = 0
        else:
            effective_retries = max_retries

        @functools.wraps(lambda *a, **kw: None)  # 占位wrapper
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(effective_retries + 1):
                # 检查driver可用性
                current_driver = object.__getattribute__(self, '_driver')
                if current_driver is None:
                    raise RuntimeError(f'Driver不可用（未初始化或已断开）: {name}')
                if object.__getattribute__(self, '_connection_lost'):
                    raise ConnectionError(f'连接已丢失，无法执行: {name}')

                try:
                    current_method = getattr(current_driver, name)
                    return current_method(*args, **kwargs)

                except _RETRYABLE_EXCEPTIONS as e:
                    last_exception = e
                    if attempt < effective_retries:
                        delay = base_delay * (2 ** attempt)  # 指数退避
                        logger.warning(
                            f'[DriverProxy] {name} 异常({type(e).__name__})，'
                            f'{delay:.1f}s后重试 {attempt + 1}/{effective_retries}'
                        )
                        time.sleep(delay)
                        continue
                    raise

                except InvalidSessionIdException as e:
                    # Session失效直接标记连接丢失
                    self._fire_connection_lost(e)
                    raise

                except WebDriverException as e:
                    if _is_connection_error(e):
                        logger.error(f'[DriverProxy] {name} 连接错误: {e}')
                        self._fire_connection_lost(e)
                        raise
                    # 其他WebDriver异常（如NoSuchElementException是其子类）不重试
                    raise

            if last_exception:
                raise last_exception

        return wrapper

    def __getattr__(self, name: str):
        """代理所有未定义的属性/方法到底层driver"""
        current_driver = object.__getattribute__(self, '_driver')

        # 处理特殊属性
        if name == '_driver':
            return current_driver

        if current_driver is None:
            # driver为None时，方法调用抛出友好错误
            def _raise_no_driver(*args, **kwargs):
                raise RuntimeError(f'Driver未初始化，无法调用 {name}')
            # 尝试检测是否为方法名（通常callable属性），对于已知方法名返回raiser
            return _raise_no_driver

        value = getattr(current_driver, name)

        # 如果是可调用的（方法/函数），包装重试逻辑
        # 注意：property描述符在通过getattr访问时已经求值，所以这里拿到的是值
        # callable(value)能正确区分方法（函数）和属性值
        if callable(value):
            return self._wrap_method(name)

        # 非callable属性直接返回（不包装重试）
        return value

    def __setattr__(self, name: str, value: Any):
        """设置属性时同步到底层driver（driver为None时只设置自身属性）"""
        try:
            current_driver = object.__getattribute__(self, '_driver')
        except AttributeError:
            current_driver = None

        if current_driver is not None and hasattr(current_driver, name):
            try:
                setattr(current_driver, name, value)
                return
            except Exception:
                pass
        object.__setattr__(self, name, value)

    # ---------- 常用操作的显式封装 ----------

    def is_session_alive(self) -> bool:
        """轻量级session存活检测（真实命令探针）

        探针命令选型（2026-09-11 真机两轮实测结论）：
        - 不能用 driver.session / session_id：属性不存在或本地值（0请求），永远失真；
        - 不能用 current_package：不走 UiAutomator2 instrumentation，
          instrumentation 崩了它仍可能成功返回 → 判不死（实测复现）；
        - get_window_size()：轻量、走 instrumentation（与 screenshot 同路径），
          screenshot 能正确失败它也能 → 选中。
        """
        try:
            current_driver = object.__getattribute__(self, '_driver')
            if current_driver is None:
                return False
            _ = current_driver.get_window_size()
            return True
        except Exception:
            return False

    def get_page_source_safe(self) -> Optional[str]:
        """安全获取页面源码，失败返回None"""
        try:
            current_driver = object.__getattribute__(self, '_driver')
            if current_driver is None:
                return None
            # Appium/Selenium Python Client 中 page_source 是属性，不是 get_page_source() 方法。
            return current_driver.page_source
        except Exception as e:
            logger.warning(f'[DriverProxy] get_page_source失败: {e}')
            return None

    def get_screenshot_bytes_safe(self) -> Optional[bytes]:
        """安全获取截图PNG字节流，失败返回None（不落盘，供内存直传）"""
        try:
            current_driver = object.__getattribute__(self, '_driver')
            if current_driver is None:
                return None
            return current_driver.get_screenshot_as_png()
        except Exception as e:
            logger.warning(f'[DriverProxy] 获取截图字节流失败: {e}')
            return None

    def take_screenshot_safe(self, filename: str) -> bool:
        """安全截图，失败返回False"""
        try:
            current_driver = object.__getattribute__(self, '_driver')
            if current_driver is None:
                return False
            if hasattr(current_driver, 'get_screenshot_as_file'):
                return bool(current_driver.get_screenshot_as_file(filename))
            if hasattr(current_driver, 'save_screenshot'):
                return bool(current_driver.save_screenshot(filename))
            logger.warning('[DriverProxy] 当前driver不支持截图方法')
            return False
        except Exception as e:
            logger.warning(f'[DriverProxy] 截图失败: {e}')
            return False

    def find_element_safe(self, by: str, value: str, timeout: float = 0) -> Optional[Any]:
        """
        安全查找单个元素，找不到返回None

        Args:
            by: 定位方式（如AppiumBy.ID）
            value: 定位值
            timeout: 隐式等待超时（秒），0表示不等待
        """
        try:
            if timeout > 0:
                # 使用WebDriverWait
                from selenium.webdriver.support.ui import WebDriverWait
                from selenium.webdriver.support import expected_conditions as EC
                return WebDriverWait(object.__getattribute__(self, '_driver'), timeout).until(
                    EC.presence_of_element_located((by, value))
                )
            return self.find_element(by, value)
        except NoSuchElementException:
            return None
        except Exception as e:
            logger.debug(f'[DriverProxy] find_element({by}={value})失败: {e}')
            return None

    def find_elements_safe(self, by: str, value: str) -> List[Any]:
        """安全查找多个元素，失败返回空列表"""
        try:
            return self.find_elements(by, value)
        except Exception as e:
            logger.debug(f'[DriverProxy] find_elements({by}={value})失败: {e}')
            return []
