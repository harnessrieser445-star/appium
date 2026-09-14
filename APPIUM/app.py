"""
Appium自动化测试平台 - Flask应用入口
Phase 3修复：API层规范统一与错误处理
"""
import os
import atexit

import yaml
from flask import Flask, render_template

# 先初始化Logger（在所有模块导入前）
from backend.utils.logger import setup_logger, get_logger
from backend.utils.paths import (
    ensure_dirs, SCREENSHOTS_DIR, TEST_SCREENSHOTS_DIR,
    GENERATED_SCRIPTS_DIR, TEST_CASES_DIR, OLD_TEST_CASES_DIR
)

logger = setup_logger(level='INFO')

# 核心Service单例
from services.device_service import device_service
from services.element_service import element_service
from services.script_design_service import script_design_service
from services.script_gen_service import script_gen_service
from services.action_service import action_service

# ScreenshotService
from backend.services.screenshot_service import screenshot_service

# Blueprint API层
from backend.api.health import health_bp
from backend.api.device import device_bp
from backend.api.element import element_bp
from backend.api.script import script_bp
from backend.api.action import action_bp

# 服务注册表
from backend.api.service_registry import register_services

# API层中间件
from backend.api.errors import register_error_handlers
from backend.api.cors import setup_cors

# 数据库初始化
from backend.database.db import init_db, db


def create_app():
    """应用工厂函数"""
    app = Flask(__name__,
                template_folder=os.path.join(os.path.dirname(__file__), 'templates'),
                static_folder=os.path.join(os.path.dirname(__file__), 'static'))

    # 加载配置
    config_path = os.path.join(os.path.dirname(__file__), 'config.yaml')
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    app.config['APP_CONFIG'] = config

    # 确保必要目录存在
    ensure_dirs()
    os.makedirs(str(TEST_CASES_DIR), exist_ok=True)
    os.makedirs(str(OLD_TEST_CASES_DIR), exist_ok=True)
    os.makedirs(str(TEST_SCREENSHOTS_DIR), exist_ok=True)
    os.makedirs(str(GENERATED_SCRIPTS_DIR), exist_ok=True)

    logger.info('[App] 配置加载完成，目录已创建')

    # ---------- 数据库初始化 ----------
    db_enabled = config.get('database', {}).get('enabled', False)
    if db_enabled:
        try:
            init_db(app, config)
            logger.info('[App] 数据库初始化成功')
        except Exception as e:
            logger.error(f'[App] 数据库初始化失败（不影响旧功能）: {e}', exc_info=True)
            db_enabled = False

    # ---------- 依赖注入 ----------
    # element_service 依赖 device_service
    element_service.set_device_service(device_service)

    # script_gen_service 依赖 script_design_service 和 device_service
    script_gen_service.set_design_service(script_design_service)
    script_gen_service.set_device_service(device_service)

    # action_service 依赖 device_service 和 element_service（单动作直执行，不写用例）
    action_service.set_device_service(device_service)
    action_service.set_element_service(element_service)

    # Repository注入：当database.enabled=true时启用DB持久化
    if db_enabled:
        try:
            from backend.repositories.test_case_repository import TestCaseRepository
            from backend.repositories.device_repository import DeviceRepository
            from backend.repositories.element_repository import ElementRepository

            # DB模式：Repository优先DB持久化，JSON目录用新目录（迁移备份用）
            case_repo = TestCaseRepository(test_cases_dir=str(TEST_CASES_DIR), db=db)
            device_repo = DeviceRepository(db=db)
            element_repo = ElementRepository(db=db)

            # 注入到Service
            script_design_service.set_case_repository(case_repo)
            element_service.set_element_repository(element_repo)

            # 将Repository保存到app.config供后续使用
            app.config['CASE_REPO'] = case_repo
            app.config['DEVICE_REPO'] = device_repo
            app.config['ELEMENT_REPO'] = element_repo

            logger.info('[App] Repository注入完成（DB模式）')
        except Exception as e:
            logger.error(f'[App] Repository初始化失败，回退到JSON模式: {e}', exc_info=True)
            db_enabled = False
            # 回退：使用旧JSON目录保持向后兼容
            from backend.repositories.test_case_repository import TestCaseRepository
            case_repo = TestCaseRepository(test_cases_dir=str(OLD_TEST_CASES_DIR), db=None)
            script_design_service.set_case_repository(case_repo)
    else:
        # 无DB模式：仅JSON，使用旧目录保持向后兼容
        from backend.repositories.test_case_repository import TestCaseRepository
        case_repo = TestCaseRepository(test_cases_dir=str(OLD_TEST_CASES_DIR), db=None)
        script_design_service.set_case_repository(case_repo)
        logger.info('[App] Repository初始化完成（JSON模式）')

    # ---------- 注册服务到注册表（供Blueprint使用） ----------
    register_services(
        device_svc=device_service,
        element_svc=element_service,
        script_design_svc=script_design_service,
        script_gen_svc=script_gen_service,
        screenshot_svc=screenshot_service,
        action_svc=action_service,
    )

    # ---------- 注册Blueprint ----------
    app.register_blueprint(health_bp)
    app.register_blueprint(device_bp)
    app.register_blueprint(element_bp)
    app.register_blueprint(script_bp)
    app.register_blueprint(action_bp)

    # ---------- 注册CORS和全局错误处理（必须在Blueprint之后） ----------
    cors_origins = config.get('app', {}).get('cors_origins', '*')
    setup_cors(app, origins=cors_origins)
    register_error_handlers(app)

    logger.info(f'[App] 应用创建完成 (DB={"enabled" if db_enabled else "disabled"})')
    return app, config


# 创建应用实例
app, config = create_app()


# ---------- 应用退出清理 ----------
import logging as _logging

def _cleanup_on_exit():
    """应用退出时清理资源：断开Appium会话、停止心跳线程、停止自启动的Appium Server"""
    # 防止atexit在日志流关闭后调用导致ValueError
    try:
        if not _logging.root.handlers:
            return
        logger.info('[Shutdown] 正在清理资源...')
        try:
            device_service.disconnect()
        except Exception as e:
            logger.error(f'[Shutdown] 断开设备异常: {e}')
        try:
            mgr = getattr(device_service, 'device_manager', None)
            if mgr and hasattr(mgr, 'server'):
                mgr.server.stop()
        except Exception as e:
            logger.error(f'[Shutdown] 停止Appium Server异常: {e}')
        logger.info('[Shutdown] 资源清理完成')
    except (ValueError, OSError):
        # 日志流已关闭，静默退出
        pass


atexit.register(_cleanup_on_exit)


if __name__ == '__main__':
    app_cfg = config.get('app', {})
    _host = app_cfg.get('host', '127.0.0.1')
    _port = app_cfg.get('port', 5001)

    # 单实例检查：端口已被占用说明已有实例在运行，直接报错退出
    import socket as _socket
    with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as _s:
        _s.settimeout(1)
        if _s.connect_ex((_host, int(_port))) == 0:
            logger.error(f'[App] 端口 {_port} 已被占用：可能已有实例在运行，拒绝重复启动')
            raise SystemExit(1)

    logger.info(f'[App] 启动Flask服务 on {_host}:{_port}')
    app.run(
        host=_host,
        port=int(_port),
        debug=app_cfg.get('debug', False),
        use_reloader=False,
        threaded=True  # 多线程：避免单个慢请求（如page_source）阻塞所有轮询请求
    )
