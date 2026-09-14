"""
统一配置加载模块
Phase 0: 提供配置单例，读取 config.yaml，支持环境变量覆盖
后续 Phase: 被其他模块引用，替代分散的 yaml.safe_load
"""
import os
from pathlib import Path
from typing import Any, Optional

import yaml


class Config:
    """配置单例类"""

    _instance: Optional['Config'] = None
    _initialized: bool = False

    def __new__(cls) -> 'Config':
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._config: dict = {}
        self._config_path: Optional[Path] = None
        self._load_config()
        Config._initialized = True

    def _load_config(self):
        """加载配置文件"""
        # 项目根目录（backend/utils/config.py 的祖父目录）
        root_dir = Path(__file__).resolve().parent.parent.parent
        self._root_dir = root_dir
        config_path = root_dir / 'config.yaml'
        self._config_path = config_path

        if config_path.exists():
            with open(config_path, 'r', encoding='utf-8') as f:
                self._config = yaml.safe_load(f) or {}
        else:
            self._config = {}

        # 环境变量覆盖（格式：APPIUM_CONFIG_KEY__SUBKEY = value）
        self._apply_env_overrides()

    def _apply_env_overrides(self):
        """应用环境变量覆盖配置
        环境变量命名规则：APPIUM_ + 大写配置路径，双下划线分隔层级
        例如：APPIUM_APP_PORT 覆盖 app.port
              APPIUM_APPIUM_SERVER_URL 覆盖 appium.server_url
        """
        prefix = 'APPIUM_'
        for key, value in os.environ.items():
            if not key.startswith(prefix):
                continue
            config_key = key[len(prefix):].lower().replace('__', '.')
            self._set_nested(config_key, value)

    def _set_nested(self, key_path: str, value: str):
        """按点分隔路径设置嵌套配置值（简单类型转换）"""
        keys = key_path.split('.')
        node = self._config
        for k in keys[:-1]:
            if k not in node or not isinstance(node[k], dict):
                node[k] = {}
            node = node[k]
        # 尝试类型转换
        final_key = keys[-1]
        if value.lower() in ('true', 'yes', '1'):
            node[final_key] = True
        elif value.lower() in ('false', 'no', '0'):
            node[final_key] = False
        elif value.isdigit():
            node[final_key] = int(value)
        else:
            try:
                node[final_key] = float(value)
            except ValueError:
                node[final_key] = value

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置值，支持点分隔路径
        例如：config.get('app.port') 或 config.get('appium.server_url')
        """
        keys = key.split('.')
        node = self._config
        for k in keys:
            if isinstance(node, dict) and k in node:
                node = node[k]
            else:
                return default
        return node

    def get_root_dir(self) -> Path:
        """获取项目根目录"""
        return self._root_dir

    def reload(self):
        """重新加载配置（用于配置文件修改后）"""
        self._initialized = False
        self._config = {}
        self._load_config()
        self._initialized = True


# 全局单例实例
config = Config()
