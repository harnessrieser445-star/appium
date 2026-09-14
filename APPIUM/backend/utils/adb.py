"""
统一ADB路径管理模块
Phase 3: 解决ADB路径冲突问题（bin/adb.exe vs android-sdk/platform-tools/adb.exe）
所有模块通过此模块获取adb路径，确保使用同一版本
"""
import os
import shutil
from pathlib import Path
from typing import Optional


# 项目根目录
ROOT_DIR = Path(__file__).resolve().parent.parent.parent

# ADB候选路径（按优先级排序）
_ADB_CANDIDATES = [
    ROOT_DIR / 'bin' / 'adb.exe',                           # 1. 项目自带bin目录（最高优先级）
    ROOT_DIR / 'venv' / 'Lib' / 'site-packages' / 'adbutils' / 'binaries' / 'adb.exe',  # 2. venv adbutils
]


def _resolve_adb_path() -> str:
    """
    解析adb.exe路径，按优先级查找可用的adb

    Returns:
        adb可执行文件的绝对路径，如果找不到则返回'adb'（系统PATH）
    """
    for candidate in _ADB_CANDIDATES:
        if candidate.is_file():
            return str(candidate)

    # 回退：检查系统PATH中是否有adb
    system_adb = shutil.which('adb')
    if system_adb:
        return system_adb

    # 最终回退：返回'adb'让系统查找
    return 'adb'


# 模块加载时确定ADB路径（唯一真相源）
ADB_PATH: str = _resolve_adb_path()


def get_adb_path() -> str:
    """获取adb可执行文件路径"""
    return ADB_PATH


def get_adb_dir() -> Optional[str]:
    """获取adb所在目录（用于设置PATH环境变量）"""
    if ADB_PATH == 'adb':
        return None
    return str(Path(ADB_PATH).parent)


def is_project_adb() -> bool:
    """是否使用项目自带的bin/adb.exe"""
    return str(ROOT_DIR / 'bin' / 'adb.exe') == ADB_PATH


def get_adb_version() -> Optional[str]:
    """获取adb版本信息"""
    import subprocess
    try:
        result = subprocess.run(
            [ADB_PATH, 'version'],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            return result.stdout.strip().splitlines()[0] if result.stdout.strip() else None
    except Exception:
        pass
    return None
