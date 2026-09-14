# backend.models 包
# SQLAlchemy ORM 模型集合
# 注意：导入顺序很重要，被依赖的模型先导入

from backend.models.base import BaseModel
from backend.models.app import App
from backend.models.device import Device
from backend.models.element_snapshot import ElementSnapshot
from backend.models.element import Element
from backend.models.element_map import ElementMap
from backend.models.test_case import TestCase, TestStep
from backend.models.script import Script
from backend.models.execution_record import ExecutionRecord, ExecutionStepResult
from backend.models.appium_session import AppiumSession
from backend.models.system_config import SystemConfig

__all__ = [
    'BaseModel',
    'App',
    'Device',
    'ElementSnapshot',
    'Element',
    'ElementMap',
    'TestCase',
    'TestStep',
    'Script',
    'ExecutionRecord',
    'ExecutionStepResult',
    'AppiumSession',
    'SystemConfig',
]
