"""
数据库初始化模块
Phase 1: 完整实现，包括建表、种子数据、JSON迁移
"""
import logging
from flask_sqlalchemy import SQLAlchemy


# SQLAlchemy全局单例实例
db = SQLAlchemy()

logger = logging.getLogger(__name__)


def _seed_default_data(config: dict = None):
    """插入默认种子数据"""
    from backend.models.app import App
    from backend.models.system_config import SystemConfig

    # 默认APP
    if not App.query.filter_by(package_name='default').first():
        default_app = App(
            package_name='default',
            app_name='默认应用',
            is_active=True
        )
        db.session.add(default_app)

    # 从config读取database.enabled
    db_enabled = 'true'
    if config and config.get('database', {}).get('enabled', True):
        db_enabled = 'true'

    # 默认系统配置
    defaults = [
        ('database.enabled', db_enabled, 'bool', '是否启用数据库持久化'),
        ('database.schema_version', '1', 'int', '数据库Schema版本'),
        ('device.mock_enabled', 'true', 'bool', '是否允许模拟设备'),
        ('element.auto_capture', 'true', 'bool', '是否自动抓取元素'),
        ('execution.screenshot_on_fail', 'true', 'bool', '执行失败时自动截图'),
        ('execution.default_timeout', '30', 'int', '步骤默认超时时间(秒)'),
    ]
    for key, value, vtype, desc in defaults:
        existing = db.session.get(SystemConfig, key)
        if existing:
            # 更新已有配置的value（特别是database.enabled跟随config.yaml）
            if key == 'database.enabled':
                existing.value = value
        else:
            db.session.add(SystemConfig(key=key, value=value, value_type=vtype, description=desc))

    db.session.commit()


def _run_migration():
    """执行数据迁移（JSON用例→DB）"""
    from backend.utils.paths import TEST_CASES_DIR, OLD_TEST_CASES_DIR, BACKUPS_DIR
    from backend.database.migrate_json_cases import migrate_json_cases

    # 优先从旧目录（根目录test_cases/）迁移，新目录也检查
    source_dir = OLD_TEST_CASES_DIR if OLD_TEST_CASES_DIR.exists() and any(OLD_TEST_CASES_DIR.glob('*.json')) else TEST_CASES_DIR

    try:
        result = migrate_json_cases(db, source_dir, BACKUPS_DIR)
        if result['migrated'] > 0 or result['skipped'] > 0 or result['failed'] > 0:
            logger.info(
                f'[DB迁移] 完成: 迁移{result["migrated"]}个, '
                f'跳过{result["skipped"]}个(已存在), '
                f'失败{result["failed"]}个'
            )
            if result.get('backup_dir'):
                logger.info(f'[DB迁移] JSON备份位置: {result["backup_dir"]}')
            for err in result.get('errors', []):
                logger.warning(f'[DB迁移] 错误: {err}')
    except Exception as e:
        logger.error(f'[DB迁移] 迁移过程异常: {e}', exc_info=True)


def init_db(app, config: dict = None):
    """
    初始化数据库，在Flask app创建后调用。

    Args:
        app: Flask应用实例
        config: 应用配置字典（用于同步database.enabled到SystemConfig）
    """
    from backend.utils.paths import DATA_DIR

    # 确保data目录存在
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # SQLite数据库文件路径
    db_path = DATA_DIR / 'appium_test.db'

    # 配置Flask-SQLAlchemy
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path.as_posix()}'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'connect_args': {
            'check_same_thread': False,
            'timeout': 30
        }
    }

    # 绑定SQLAlchemy实例到Flask app
    db.init_app(app)

    with app.app_context():
        # 导入所有Model确保注册到metadata
        import backend.models  # noqa: F401

        # 创建所有表（IF NOT EXISTS，已存在的表不会被修改）
        db.create_all()

        # 插入默认种子数据
        _seed_default_data(config)

        # 执行JSON用例迁移（幂等）
        _run_migration()

    logger.info(f'[DB] 数据库初始化完成: {db_path}')
