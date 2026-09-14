"""
设备模型
支持多设备管理
"""
from backend.database.db import db
from backend.models.base import BaseModel


class Device(BaseModel):
    __tablename__ = 'devices'

    udid = db.Column(db.String(200), nullable=False, unique=True, index=True)
    name = db.Column(db.String(200), default='')
    platform = db.Column(db.String(50), default='Android')
    platform_version = db.Column(db.String(50), default='')
    model = db.Column(db.String(200), default='')
    brand = db.Column(db.String(200), default='')
    screen_width = db.Column(db.Integer, default=0)
    screen_height = db.Column(db.Integer, default=0)
    connect_method = db.Column(db.String(20), default='usb', index=True)
    ip_port = db.Column(db.String(100), default='')
    status = db.Column(db.String(30), default='offline', index=True)
    capabilities = db.Column(db.Text, default='{}')
    last_connected_at = db.Column(db.DateTime, nullable=True)
    last_heartbeat_at = db.Column(db.DateTime, nullable=True)
    is_active = db.Column(db.Boolean, default=False)
    is_mock = db.Column(db.Boolean, default=False)

    # 关系
    snapshots = db.relationship('ElementSnapshot', backref='device', lazy='dynamic')
    appium_sessions = db.relationship('AppiumSession', backref='device', lazy='dynamic')
    executions = db.relationship('ExecutionRecord', backref='device', lazy='dynamic')
