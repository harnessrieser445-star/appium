"""
单动作直执行Blueprint（面向AI助理的机器调用）
路由：
- POST /api/action    执行单个动作（不写入用例步骤列表）

响应统一携带 elapsed_ms；错误带 error_code 供AI自动决策：
  SESSION_LOST / ELEMENT_NOT_FOUND / TIMEOUT / BAD_REQUEST /
  ACTION_FAILED / NO_DEVICE
"""
from flask import Blueprint, request

from backend.api.service_registry import require_action_service
from backend.api.response import success, fail, bad_request

action_bp = Blueprint('action', __name__)

# error_code → HTTP状态码
_ERROR_STATUS = {
    'BAD_REQUEST': 400,
    'NO_DEVICE': 400,
    'ELEMENT_NOT_FOUND': 404,
    'TIMEOUT': 408,
    'SESSION_LOST': 503,
    'ACTION_FAILED': 500,
}


@action_bp.route('/api/action', methods=['POST'])
def api_action():
    """执行单个动作

    body: {
      action: 'click'|'input'|'wait'|'screenshot'|'wait_until'|'back'|
              'long_press'|'double_click'|'swipe_xy'|'clear_input'|'press_hold',
      element: {resource_id?|xpath?|content_desc?|text?, bounds?},   # 可选
      bounds: [x1,y1,x2,y2],                                          # 可选
      x: int, y: int,                                                 # 可选（纯坐标）
      target: {...},        # wait_until 专用（缺省回退element）
      params: {...}         # 动作参数
    }
    """
    action_svc = require_action_service()
    data = request.get_json(silent=True)
    if not data or 'action' not in data:
        return bad_request('缺少 action 参数')

    result = action_svc.execute(data)

    if result.get('success'):
        return success(data=result)

    error_code = result.get('error_code', 'ACTION_FAILED')
    status = _ERROR_STATUS.get(error_code, 500)
    resp = {'success': False, 'message': result.get('message', ''), 'error_code': error_code,
            'action': result.get('action'), 'elapsed_ms': result.get('elapsed_ms')}
    if result.get('page_digest'):
        resp['page_digest'] = result['page_digest']
    return fail(resp['message'], status_code=status, error_code=error_code,
                action=resp['action'], elapsed_ms=resp['elapsed_ms'],
                **({'page_digest': resp['page_digest']} if result.get('page_digest') else {}))
