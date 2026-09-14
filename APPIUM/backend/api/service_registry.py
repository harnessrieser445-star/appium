"""
服务注册表
在Flask app初始化时注册Service实例，Blueprint路由通过此模块获取Service
避免循环import问题。

Phase 3: 新增require_*方法，在Service未注册时返回标准错误响应而非抛出AttributeError。
"""

# Service实例在app.py中注册
_services = {}


def register_services(device_svc=None, element_svc=None, script_design_svc=None,
                      script_gen_svc=None, screenshot_svc=None, action_svc=None):
    """注册Service实例（在app.py创建后调用）"""
    if device_svc is not None:
        _services['device'] = device_svc
    if element_svc is not None:
        _services['element'] = element_svc
    if script_design_svc is not None:
        _services['script'] = script_design_svc
    if script_gen_svc is not None:
        _services['script_gen'] = script_gen_svc
    if screenshot_svc is not None:
        _services['screenshot'] = screenshot_svc
    if action_svc is not None:
        _services['action'] = action_svc


def _require(service_key: str, service_name: str):
    """获取Service实例，未注册时抛出RuntimeError（由全局error handler转为503 JSON）"""
    svc = _services.get(service_key)
    if svc is None:
        raise RuntimeError(f'{service_name}未初始化，请检查应用启动流程')
    return svc


def get_device_service():
    return _services.get('device')


def require_device_service():
    return _require('device', '设备服务')


def get_element_service():
    return _services.get('element')


def require_element_service():
    return _require('element', '元素服务')


def get_script_service():
    """获取脚本编排服务(script_design_service)"""
    return _services.get('script')


def require_script_service():
    return _require('script', '脚本编排服务')


def get_script_gen_service():
    """获取脚本生成执行服务(script_gen_service)"""
    return _services.get('script_gen')


def require_script_gen_service():
    return _require('script_gen', '脚本执行服务')


def get_screenshot_service():
    return _services.get('screenshot')


def require_screenshot_service():
    return _require('screenshot', '截图服务')


def get_action_service():
    return _services.get('action')


def require_action_service():
    return _require('action', '动作执行服务')
