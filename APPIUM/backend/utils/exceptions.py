"""
自定义异常类体系
Phase 0: 定义基础异常类
后续 Phase: 各模块可扩展自己的异常类
"""


class AppiumTestError(Exception):
    """基础异常类，所有自定义异常继承自此类"""
    pass


# ============ 设备相关异常 ============
class DeviceError(AppiumTestError):
    """设备相关异常基类"""
    pass


class DeviceNotConnectedError(DeviceError):
    """设备未连接异常"""
    pass


class DeviceConnectionError(DeviceError):
    """设备连接失败异常"""
    def __init__(self, message: str = '设备连接失败', udid: str = None):
        self.udid = udid
        super().__init__(message)


class DeviceNotFoundError(DeviceError):
    """设备未找到异常"""
    pass


class ADBError(DeviceError):
    """ADB命令执行异常"""
    def __init__(self, message: str = 'ADB命令执行失败', cmd: str = None, returncode: int = None):
        self.cmd = cmd
        self.returncode = returncode
        super().__init__(message)


# ============ Appium相关异常 ============
class AppiumError(AppiumTestError):
    """Appium相关异常基类"""
    pass


class AppiumSessionError(AppiumError):
    """Appium Session异常"""
    pass


class AppiumSessionExpiredError(AppiumSessionError):
    """Appium Session过期/失效异常"""
    pass


class AppiumConnectionError(AppiumError):
    """Appium Server连接异常"""
    pass


class AppiumDriverError(AppiumError):
    """Appium Driver操作异常"""
    pass


# ============ 元素相关异常 ============
class ElementError(AppiumTestError):
    """元素相关异常基类"""
    pass


class ElementNotFoundError(ElementError):
    """元素未找到异常"""
    def __init__(self, message: str = '元素未找到', xpath: str = None):
        self.xpath = xpath
        super().__init__(message)


class ElementStaleError(ElementError):
    """元素引用过期异常（页面刷新导致）"""
    pass


# ============ 执行相关异常 ============
class ExecutionError(AppiumTestError):
    """测试执行异常基类"""
    pass


class ExecutionTimeoutError(ExecutionError):
    """执行超时异常"""
    def __init__(self, message: str = '执行超时', timeout: int = None, step_order: int = None):
        self.timeout = timeout
        self.step_order = step_order
        super().__init__(message)


class ExecutionAbortedError(ExecutionError):
    """执行被中止异常"""
    pass


class ActionNotSupportedError(ExecutionError):
    """不支持的动作类型异常"""
    def __init__(self, action: str = None):
        self.action = action
        super().__init__(f'不支持的动作类型: {action}')


# ============ 安全相关异常 ============
class SecurityError(AppiumTestError):
    """安全相关异常基类"""
    pass


class AuthenticationError(SecurityError):
    """认证失败异常"""
    pass


class AuthorizationError(SecurityError):
    """授权失败异常"""
    pass


class PathTraversalError(SecurityError):
    """路径遍历攻击异常"""
    pass


class ValidationError(AppiumTestError):
    """输入校验失败异常"""
    def __init__(self, message: str = '输入校验失败', field: str = None, value=None):
        self.field = field
        self.value = value
        super().__init__(message)


# ============ 配置相关异常 ============
class ConfigError(AppiumTestError):
    """配置相关异常"""
    pass
