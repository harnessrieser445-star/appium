"""
统一路径管理模块
Phase 0: 定义所有数据目录路径常量，自动创建目录
后续 Phase: 所有文件操作通过此模块获取路径，避免硬编码
"""
from pathlib import Path
from typing import Optional


# 项目根目录（backend/utils/paths.py 的祖父目录）
ROOT_DIR: Path = Path(__file__).resolve().parent.parent.parent

# ============ 数据目录 ============
DATA_DIR: Path = ROOT_DIR / 'data'
SCREENSHOTS_DIR: Path = DATA_DIR / 'screenshots'
TEST_SCREENSHOTS_DIR: Path = DATA_DIR / 'test_screenshots'
GENERATED_SCRIPTS_DIR: Path = DATA_DIR / 'generated_scripts'
LOGS_DIR: Path = DATA_DIR / 'logs'
BACKUPS_DIR: Path = DATA_DIR / 'backups'
EXPORTS_DIR: Path = DATA_DIR / 'exports'
TEST_CASES_DIR: Path = DATA_DIR / 'test_cases'  # JSON用例目录（DB启用后仅作迁移备份）

# ============ 旧目录（兼容期保留） ============
OLD_UPLOADS_DIR: Path = ROOT_DIR / 'uploads'
OLD_SCREENSHOTS_DIR: Path = OLD_UPLOADS_DIR / 'screenshots'
OLD_TEST_SCREENSHOTS_DIR: Path = OLD_UPLOADS_DIR / 'test_screenshots'
OLD_GENERATED_SCRIPTS_DIR: Path = ROOT_DIR / 'generated_scripts'
OLD_TEST_CASES_DIR: Path = ROOT_DIR / 'test_cases'  # 旧版JSON用例目录

# ============ 工具/资源目录 ============
BIN_DIR: Path = ROOT_DIR / 'bin'
ADB_PATH: Path = BIN_DIR / 'adb.exe'
ANDROID_SDK_DIR: Path = ROOT_DIR / 'android-sdk'
TEMPLATES_DIR: Path = ROOT_DIR / 'templates'
STATIC_DIR: Path = ROOT_DIR / 'static'

# ============ 配置/入口文件 ============
CONFIG_FILE: Path = ROOT_DIR / 'config.yaml'
APP_FILE: Path = ROOT_DIR / 'app.py'


def ensure_dirs(dirs: Optional[list[Path]] = None):
    """确保所有必要目录存在，自动创建不存在的目录

    Args:
        dirs: 要创建的目录列表，为None时创建所有默认目录
    """
    if dirs is None:
        dirs = [
            DATA_DIR,
            SCREENSHOTS_DIR,
            TEST_SCREENSHOTS_DIR,
            GENERATED_SCRIPTS_DIR,
            LOGS_DIR,
            BACKUPS_DIR,
            EXPORTS_DIR,
            TEST_CASES_DIR,
        ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)


def get_screenshot_path(filename: str = 'current.png') -> Path:
    """获取截图文件路径"""
    return SCREENSHOTS_DIR / filename


def get_test_screenshot_path(filename: str) -> Path:
    """获取测试失败截图路径"""
    return TEST_SCREENSHOTS_DIR / filename


def get_generated_script_path(filename: str) -> Path:
    """获取生成脚本路径"""
    return GENERATED_SCRIPTS_DIR / filename


def get_log_path(filename: str = 'app.log') -> Path:
    """获取日志文件路径"""
    return LOGS_DIR / filename


def get_backup_path(name: str) -> Path:
    """获取备份文件路径"""
    return BACKUPS_DIR / name


# 模块加载时自动创建目录
ensure_dirs()
