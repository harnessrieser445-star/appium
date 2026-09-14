"""
Capabilities构建模块
Phase 3: 统一UiAutomator2Options构建逻辑，合并config.yaml配置和代码默认值
解决：config.yaml中default_capabilities未被使用的问题
"""
from typing import Optional, Dict, Any

from appium.options.android import UiAutomator2Options


# 代码级默认Capabilities（安全基线）
_DEFAULT_CAPS = {
    'platformName': 'Android',
    'automationName': 'UiAutomator2',
    'noReset': True,
    'newCommandTimeout': 300,
    'appium:ignoreHiddenApiPolicyError': True,
    'appium:skipServerInstallation': True,
    'appium:skipServerStartup': False,
    # UiAutomator2 server启动超时（解决instrumentation 30s超时问题）
    'appium:uiautomator2ServerLaunchTimeout': 60000,
    # 安装超时（解决MIUI安装限制问题）
    'appium:adbExecTimeout': 20000,
}


def build_capabilities(
    adb_path: str,
    udid: Optional[str] = None,
    config_overrides: Optional[Dict[str, Any]] = None,
    extra_caps: Optional[Dict[str, Any]] = None
) -> UiAutomator2Options:
    """
    构建UiAutomator2Options

    Args:
        adb_path: adb.exe路径（通过backend.utils.adb获取）
        udid: 目标设备UDID
        config_overrides: 来自config.yaml的default_capabilities覆盖
        extra_caps: 额外的capability（如appium:appPackage等）

    Returns:
        配置完成的UiAutomator2Options实例
    """
    options = UiAutomator2Options()

    # 1. 应用代码级默认值
    caps = dict(_DEFAULT_CAPS)

    # 2. 应用config.yaml中的覆盖配置
    if config_overrides:
        for key, value in config_overrides.items():
            caps[key] = value

    # 3. 应用调用方传入的额外capabilities
    if extra_caps:
        for key, value in extra_caps.items():
            caps[key] = value

    # 4. 设置核心属性
    options.platform_name = caps.get('platformName', 'Android')
    options.automation_name = caps.get('automationName', 'UiAutomator2')
    options.no_reset = caps.get('noReset', True)
    options.new_command_timeout = caps.get('newCommandTimeout', 300)

    # 设置UDID
    if udid:
        options.udid = udid

    # 5. 设置扩展capabilities
    for key, value in caps.items():
        if key in ('platformName', 'automationName', 'noReset', 'newCommandTimeout', 'udid'):
            continue
        # appium: 前缀的capability直接set_capability
        options.set_capability(key, value)

    # 6. 指定ADB路径（关键：确保Appium使用项目自带adb）
    if adb_path and adb_path != 'adb':
        options.set_capability('adbExecPath', adb_path)

    return options


def get_default_caps_dict() -> Dict[str, Any]:
    """获取默认capabilities字典（用于生成独立脚本）"""
    return dict(_DEFAULT_CAPS)
