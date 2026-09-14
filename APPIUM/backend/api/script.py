"""
脚本编排Blueprint
路由：
- POST   /api/script/elements          添加元素到编排器
- GET    /api/script/elements          获取已接收元素列表
- DELETE /api/script/elements/<id>     移除元素
- POST   /api/script/steps             新增步骤
- PUT    /api/script/steps/<id>        修改步骤
- DELETE /api/script/steps/<id>        删除步骤
- POST   /api/script/steps/reorder     调整步骤顺序
- GET    /api/script/design            获取完整设计
- POST   /api/script/clear             清空设计
- GET    /api/script/actions           获取动作类型
- POST   /api/script/save              保存用例
- GET    /api/script/load/<name>       加载用例
- GET    /api/script/cases             列出用例
- GET    /api/script/gen/preview       预览脚本代码
- POST   /api/script/gen/execute       执行脚本
- GET    /api/script/gen/status        查询执行状态
- GET    /api/script/gen/download      下载脚本

Phase 3: 统一响应格式、参数校验、修复竞态条件
"""
import os
from flask import Blueprint, request, send_file

from backend.api.service_registry import (
    require_script_service, require_script_gen_service
)
from backend.api.response import (
    success, fail, bad_request, not_found, conflict, from_service_result
)

script_bp = Blueprint('script', __name__)


# ==================== 元素管理 ====================

@script_bp.route('/api/script/elements', methods=['POST'])
def api_script_add_element():
    """添加元素到编排器"""
    script_svc = require_script_service()
    data = request.get_json(silent=True)
    if not data:
        return bad_request('请求体为空或JSON格式错误')
    result = script_svc.add_element(data)
    return from_service_result(result)


@script_bp.route('/api/script/elements', methods=['GET'])
def api_script_get_elements():
    """获取已接收的元素列表"""
    script_svc = require_script_service()
    result = script_svc.get_elements()
    return from_service_result(result)


@script_bp.route('/api/script/elements/<design_elem_id>', methods=['DELETE'])
def api_script_remove_element(design_elem_id):
    """移除元素（同时清理关联步骤）"""
    script_svc = require_script_service()
    result = script_svc.remove_element(design_elem_id)
    return from_service_result(result)


# ==================== 步骤管理 ====================

@script_bp.route('/api/script/steps', methods=['POST'])
def api_script_add_step():
    """新增测试步骤"""
    script_svc = require_script_service()
    data = request.get_json(silent=True) or {}
    element = data.get('element')
    action = data.get('action', '')
    action_params = data.get('action_params', {})
    description = data.get('description', '')

    if not action:
        return bad_request('缺少 action 参数')

    result = script_svc.add_step(element, action, action_params, description)
    return from_service_result(result)


@script_bp.route('/api/script/steps/<step_id>', methods=['PUT'])
def api_script_update_step(step_id):
    """修改测试步骤"""
    script_svc = require_script_service()
    data = request.get_json(silent=True) or {}
    result = script_svc.update_step(
        step_id,
        action=data.get('action'),
        action_params=data.get('action_params'),
        description=data.get('description'),
        element=data.get('element')
    )
    return from_service_result(result)


@script_bp.route('/api/script/steps/<step_id>', methods=['DELETE'])
def api_script_delete_step(step_id):
    """删除测试步骤"""
    script_svc = require_script_service()
    result = script_svc.delete_step(step_id)
    return from_service_result(result)


@script_bp.route('/api/script/steps/reorder', methods=['POST'])
def api_script_reorder_steps():
    """调整步骤顺序"""
    script_svc = require_script_service()
    data = request.get_json(silent=True) or {}
    step_ids = data.get('step_ids', [])
    if not isinstance(step_ids, list):
        return bad_request('step_ids 必须是列表')
    if not step_ids:
        return bad_request('step_ids 不能为空')
    result = script_svc.reorder_steps(step_ids)
    return from_service_result(result)


# ==================== 完整设计 ====================

@script_bp.route('/api/script/design', methods=['GET'])
def api_script_get_design():
    """获取完整测试设计（元素+步骤）"""
    script_svc = require_script_service()
    result = script_svc.get_design()
    return from_service_result(result)


@script_bp.route('/api/script/clear', methods=['POST'])
def api_script_clear():
    """清空所有设计数据"""
    script_svc = require_script_service()
    result = script_svc.clear()
    return from_service_result(result)


# ==================== 动作类型 ====================

@script_bp.route('/api/script/actions', methods=['GET'])
def api_script_actions():
    """获取支持的动作类型列表"""
    script_svc = require_script_service()
    result = script_svc.get_supported_actions()
    return from_service_result(result)


# ==================== 用例持久化 ====================

@script_bp.route('/api/script/save', methods=['POST'])
def api_script_save_case():
    """保存测试用例"""
    script_svc = require_script_service()
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    if not name:
        return bad_request('用例名称不能为空')
    # 名称合法性校验（防止路径穿越）
    if any(c in name for c in ('/', '\\', '..', '\x00')):
        return bad_request('用例名称包含非法字符')
    result = script_svc.save_case(name)
    return from_service_result(result)


@script_bp.route('/api/script/load/<name>', methods=['GET'])
def api_script_load_case(name):
    """加载测试用例"""
    script_svc = require_script_service()
    if not name or any(c in name for c in ('/', '\\', '..', '\x00')):
        return bad_request('非法的用例名称')
    result = script_svc.load_case(name)
    return from_service_result(result)


@script_bp.route('/api/script/cases', methods=['GET'])
def api_script_list_cases():
    """列出所有已保存的测试用例"""
    script_svc = require_script_service()
    result = script_svc.list_cases()
    return from_service_result(result)


@script_bp.route('/api/script/cases/<name>', methods=['DELETE'])
def api_script_delete_case(name):
    """删除测试用例（SQLite + JSON 双删）"""
    script_svc = require_script_service()
    # 名称合法性校验（防止路径穿越，与 load/<name> 同风格）
    if not name or any(c in name for c in ('/', '\\', '..', '\x00')):
        return bad_request('非法的用例名称')
    result = script_svc.delete_case(name)
    return from_service_result(result)


# ==================== 脚本生成与执行 ====================

@script_bp.route('/api/script/gen/preview', methods=['GET'])
def api_script_gen_preview():
    """生成并返回完整Python脚本代码（不保存文件）"""
    gen_svc = require_script_gen_service()
    case_name = request.args.get('name', 'generated_test').strip()
    result = gen_svc.generate_script(case_name, save=False)
    return from_service_result(result)


@script_bp.route('/api/script/gen/execute', methods=['POST'])
def api_script_gen_execute():
    """在当前设备上直接执行测试步骤（竞态条件由Service内部锁保护）"""
    gen_svc = require_script_gen_service()
    data = request.get_json(silent=True) or {}
    continue_on_failure = bool(data.get('continue_on_failure', False))
    # Service内部通过锁和_is_executing状态做原子检查，消除TOCTOU竞态
    result = gen_svc.execute_inline(continue_on_failure=continue_on_failure)
    # 如果返回"正在执行"消息，映射为409 Conflict
    if not result.get('success') and ('执行中' in result.get('message', '') or '正在执行' in result.get('message', '')):
        return conflict(result.get('message', '已有测试正在执行中'))
    return from_service_result(result)


@script_bp.route('/api/script/gen/status', methods=['GET'])
def api_script_gen_status():
    """查询最近一次执行结果"""
    gen_svc = require_script_gen_service()
    result = gen_svc.get_execution_status()
    return success(data=result)


@script_bp.route('/api/script/gen/download', methods=['GET'])
def api_script_gen_download():
    """下载生成的脚本文件"""
    gen_svc = require_script_gen_service()
    case_name = request.args.get('name', 'generated_test').strip()
    result = gen_svc.generate_script(case_name, save=True)
    if not result.get('success'):
        return from_service_result(result)

    filepath = result['filepath']
    if not os.path.exists(filepath):
        return not_found('脚本文件不存在')

    return send_file(
        filepath,
        as_attachment=True,
        download_name=result['filename']
    )
