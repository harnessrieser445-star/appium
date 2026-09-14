"""
Appium会话追踪模型
"""
from datetime import datetime
from backend.database.db import db
from backend.models.base import BaseModel


class AppiumSession(BaseModel):
    __tablename__ = 'appium_sessions'

    device_id = db.Column(db.Integer, db.ForeignKey('devices.id'), nullable=True, index=True)
    session_id = db.Column(db.String(200), nullable=False, index=True)
    appium_server_url = db.Column(db.String(300), default='')
    capabilities_used = db.Column(db.Text, default='{}')
    status = db.Column(db.String(20), default='active')
    last_heartbeat_at = db.Column(db.DateTime, nullable=True)
    closed_at = db.Column(db.DateTime, nullable=True)
    close_reason = db.Column(db.String(100), default='')

    def close(self, reason: str = 'normal'):
        """关闭会话"""
        self.status = 'closed'
        self.closed_at = datetime.now()
        self.close_reason = reason
