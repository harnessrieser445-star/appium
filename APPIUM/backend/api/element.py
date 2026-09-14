"""
截图与元素Blueprint
路由：
- GET  /api/screenshot
- POST /api/screenshot/highlight
- POST /api/elements/refresh
- GET  /api/elements/<elem_id>
- POST /api/elements/locate

Phase 3: 统一响应格式、参数校验、错误处理
Phase 5: 截图改为内存直传（BytesIO），消除 current.png 读写竞态；
         落盘仅为高亮功能副产物（原子写）；截图失败回退上一帧
"""
import base64
import io
import os
from flask import Blueprint, request, jsonify, send_file

from backend.api.service_registry import (
    require_device_service, require_element_service, require_screenshot_service
)
from backend.api.response import success, fail, bad_request, not_found, from_service_result
from backend.utils.logger import get_logger

logger = get_logger(__name__)

element_bp = Blueprint('element', __name__)


@element_bp.route('/api/screenshot', methods=['GET'])
def api_screenshot():
    """获取截图（真实设备优先，模拟模式生成模拟截图）

    Phase 5: 真实截图直接以字节流返回，不经过 current.png 中转，
    避免并发写文件与 send_file 读文件产生撕裂图；
    current.png 仍以原子方式落盘（供高亮功能使用）；
    截图失败时回退上一帧，保证前端画面连续。
    """
    device_svc = require_device_service()
    screenshot_svc = require_screenshot_service()
    path = screenshot_svc.get_current_screenshot_path()

    # 真实Appium已连接，优先获取真实截图（内存直传）
    if device_svc.is_real():
        png = device_svc.get_screenshot_bytes()
        if png:
            # 副产物：原子落盘供 highlight 使用（失败不影响本次响应）
            screenshot_svc.save_screenshot(png)
            return send_file(io.BytesIO(png), mimetype='image/png')

        # 截图失败：回退上一帧，避免前端画面中断
        logger.warning('[API] 实时截图失败，回退到缓存截图')
        if os.path.exists(path):
            with open(path, 'rb') as f:
                return send_file(io.BytesIO(f.read()), mimetype='image/png')
        return fail('真实截图获取失败', status_code=500, error_code='SCREENSHOT_FAILED')

    # 模拟模式生成模拟截图
    elif device_svc.is_mock():
        try:
            from generate_mock_screenshot import generate
            generate(path)
        except Exception as e:
            return fail(f'模拟截图生成失败: {str(e)}', status_code=500, error_code='MOCK_SCREENSHOT_FAILED')

    # 无设备也无模拟模式
    else:
        return fail('未连接设备，请先连接设备或启用模拟模式', status_code=400, error_code='NO_DEVICE')

    if os.path.exists(path):
        return send_file(path, mimetype='image/png')
    return not_found('截图不存在')


@element_bp.route('/api/snapshot', methods=['GET'])
def api_snapshot():
    """同源快照：一次请求返回同一帧页面的元素树 + 截图（base64）

    Phase 5: 解决旧方案中 /api/screenshot 与 /api/elements/refresh
    分两次请求、两帧画面不同时刻导致的坐标/高亮错位问题。
    顺序：先取 page_source，紧跟截图，将两命令间屏幕变化窗口压到最小
    （Appium 无事务能力，无法做到绝对原子，动画场景仍可能有微小偏差）。

    响应: {success, data: {elements, count, mode, screenshot(base64 png), message}}
    """
    device_svc = require_device_service()
    element_svc = require_element_service()
    screenshot_svc = require_screenshot_service()
    path = screenshot_svc.get_current_screenshot_path()

    if device_svc.is_real():
        # 会话不可用前置判断：禁止在会话死亡时走后续流程（信任链：报告有数据=数据是活的）
        if not device_svc.is_session_usable():
            return fail('会话已断开，请重新连接设备',
                        status_code=503, error_code='SESSION_LOST')
        # 1. 先取页面源码
        page_source = device_svc.get_page_source()
        if not page_source:
            # page_source 失败二次确认：会话死映射 SESSION_LOST，否则保持原错误码
            if not device_svc.is_session_usable():
                return fail('会话已断开，请重新连接设备',
                            status_code=503, error_code='SESSION_LOST')
            return fail('无法获取 page_source：会话繁忙或 UiAutomator2 暂不可用',
                        status_code=500, error_code='PAGE_SOURCE_FAILED')
        # 2. 紧跟截图，最小化两帧时间差
        png = device_svc.get_screenshot_bytes()
        if not png:
            return fail('截图获取失败', status_code=500, error_code='SCREENSHOT_FAILED')

        # 3. 用同一份 source 刷新元素（保证 locate/detail 接口与本次返回一致）
        result = element_svc.refresh_from_page_source(page_source)
        if not result.get('success'):
            return fail(result.get('message', '元素解析失败'),
                        status_code=500, error_code='PARSE_FAILED')

        # 4. 副产物：原子落盘供 highlight 使用
        screenshot_svc.save_screenshot(png)

        # base64 已在文件头部导入
        return success(data={
            'elements': result['elements'],
            'count': result['count'],
            'tree': result.get('tree', []),
            'mode': 'real',
            'message': result['message'],
            'screenshot': base64.b64encode(png).decode('ascii'),
        })

    if device_svc.is_mock():
        result = element_svc.refresh_elements()
        try:
            from generate_mock_screenshot import generate
            generate(path)
            with open(path, 'rb') as f:
                png = f.read()
        except Exception as e:
            return fail(f'模拟截图生成失败: {str(e)}', status_code=500,
                        error_code='MOCK_SCREENSHOT_FAILED')
        # base64 已在文件头部导入
        return success(data={
            'elements': result.get('elements', []),
            'count': result.get('count', 0),
            'tree': result.get('tree', []),
            'mode': 'mock',
            'message': result.get('message', ''),
            'screenshot': base64.b64encode(png).decode('ascii'),
        })

    return fail('未连接设备，请先连接设备或启用模拟模式', status_code=400, error_code='NO_DEVICE')


@element_bp.route('/api/elements/scrollables', methods=['GET'])
def api_elements_scrollables():
    """查询当前页面所有可滚动容器（供AI选择滑动目标）

    真实设备下先实时刷新元素再查询——AI 调用方不保证先调过
    refresh/snapshot，直接读缓存会拿到空列表或过期数据。
    刷新失败时回退现有缓存。
    """
    device_svc = require_device_service()
    element_svc = require_element_service()

    if device_svc.is_real():
        try:
            page_source = device_svc.get_page_source()
            if page_source:
                element_svc.refresh_from_page_source(page_source)
        except Exception as e:
            logger.warning(f'[API] scrollables实时刷新失败，回退缓存: {e}')

    containers = element_svc.get_scrollable_containers()
    return success(data={'containers': containers, 'count': len(containers)})


@element_bp.route('/api/screenshot/highlight', methods=['POST'])
def api_screenshot_highlight():
    """在截图上为指定元素绘制红色高亮框"""
    screenshot_svc = require_screenshot_service()
    data = request.get_json(silent=True) or {}
    bounds = data.get('bounds')

    if bounds is None:
        return bad_request('缺少 bounds 参数')

    success_flag, result, error = screenshot_svc.highlight_element(bounds)
    if not success_flag:
        return bad_request(error or '高亮失败')

    return send_file(result, mimetype='image/png')


@element_bp.route('/api/elements/refresh', methods=['POST'])
def api_elements_refresh():
    """刷新页面元素列表（会话死亡时返回 503 + SESSION_LOST，不返回缓存元素）"""
    device_svc = require_device_service()
    if device_svc.is_real() and not device_svc.is_session_usable():
        return fail('会话已断开，请重新连接设备',
                    status_code=503, error_code='SESSION_LOST')
    element_svc = require_element_service()
    result = element_svc.refresh_elements()
    # page_source 获取失败且确认会话死亡 → 错误码升级为 SESSION_LOST
    if (not result.get('success') and device_svc.is_real()
            and not device_svc.is_session_usable()):
        return fail('会话已断开，请重新连接设备',
                    status_code=503, error_code='SESSION_LOST')
    return from_service_result(result)


@element_bp.route('/api/elements/<elem_id>', methods=['GET'])
def api_element_detail(elem_id):
    """获取元素详情"""
    element_svc = require_element_service()
    elem = element_svc.get_element_by_id(elem_id)
    if elem:
        return success(data={'element': elem})
    return not_found(f'元素不存在: {elem_id}')


@element_bp.route('/api/elements/locate', methods=['POST'])
def api_elements_locate():
    """坐标反查元素"""
    element_svc = require_element_service()
    data = request.get_json(silent=True) or {}
    x = data.get('x')
    y = data.get('y')

    if x is None or y is None:
        return bad_request('需要 x 和 y 坐标参数')

    try:
        x = int(x)
        y = int(y)
    except (ValueError, TypeError):
        return bad_request('坐标参数必须为整数')

    if x < 0 or y < 0:
        return bad_request('坐标不能为负数')

    elem = element_svc.locate_by_coordinate(x, y)
    if elem:
        return success(data={'element': elem})
    return not_found(f'坐标 ({x}, {y}) 未匹配到任何元素')
