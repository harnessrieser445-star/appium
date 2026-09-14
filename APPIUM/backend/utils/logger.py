"""
统一日志模块
Phase 0: 提供日志配置，支持控制台输出 + 文件输出
后续 Phase: 替换所有 print 为 logger.xxx
"""
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional


_logger: Optional[logging.Logger] = None
_configured: bool = False


def _get_log_dir() -> Path:
    """获取日志目录"""
    root_dir = Path(__file__).resolve().parent.parent.parent
    log_dir = root_dir / 'data' / 'logs'
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def setup_logger(
    name: str = 'appium_test',
    level: str = 'INFO',
    log_file: Optional[str] = None,
    max_bytes: int = 10 * 1024 * 1024,  # 10MB
    backup_count: int = 5,
) -> logging.Logger:
    """配置并返回全局 logger 实例

    Args:
        name: logger名称
        level: 日志级别 DEBUG/INFO/WARNING/ERROR/CRITICAL
        log_file: 日志文件名，默认 app.log
        max_bytes: 单个日志文件最大字节数
        backup_count: 保留的日志文件数量

    Returns:
        配置好的 logger 实例
    """
    global _logger, _configured

    if _configured and _logger is not None:
        return _logger

    if log_file is None:
        log_file = 'app.log'

    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.propagate = False

    # 清除已有handler（避免重复）
    logger.handlers.clear()

    # 日志格式
    fmt = logging.Formatter(
        '[%(asctime)s] %(levelname)-8s [%(filename)s:%(lineno)d] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # 控制台输出
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(fmt)
    console_handler.setLevel(logging.DEBUG)  # 控制台显示所有级别
    logger.addHandler(console_handler)

    # 文件输出
    try:
        log_dir = _get_log_dir()
        file_path = log_dir / log_file
        file_handler = RotatingFileHandler(
            str(file_path),
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding='utf-8'
        )
        file_handler.setFormatter(fmt)
        file_handler.setLevel(logging.DEBUG)
        logger.addHandler(file_handler)
    except Exception as e:
        # 日志文件初始化失败不影响系统运行
        console_handler.setLevel(logging.DEBUG)
        logger.warning(f'日志文件初始化失败，仅输出到控制台: {e}')

    _logger = logger
    _configured = True
    return logger


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """获取logger实例，如果未配置则使用默认配置初始化"""
    global _logger
    if _logger is None:
        _logger = setup_logger()
    if name:
        # 返回子logger，继承根logger的配置
        return _logger.getChild(name)
    return _logger
