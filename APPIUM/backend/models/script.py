"""
生成脚本记录模型
"""
from backend.database.db import db
from backend.models.base import BaseModel


class Script(BaseModel):
    __tablename__ = 'scripts'

    case_id = db.Column(db.Integer, db.ForeignKey('test_cases.id'), nullable=True, index=True)
    name = db.Column(db.String(200), nullable=False)
    filename = db.Column(db.String(300), nullable=False)
    filepath = db.Column(db.String(500), nullable=False)
    code = db.Column(db.Text, nullable=False)
    step_count = db.Column(db.Integer, default=0)
    device_udid = db.Column(db.String(200), default='')
    app_package = db.Column(db.String(200), default='')
