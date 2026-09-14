"""
APP信息模型
支持多APP管理
"""
from backend.database.db import db
from backend.models.base import BaseModel


class App(BaseModel):
    __tablename__ = 'apps'

    package_name = db.Column(db.String(200), nullable=False, unique=True, index=True)
    app_name = db.Column(db.String(200), nullable=False)
    main_activity = db.Column(db.String(300), default='')
    version_name = db.Column(db.String(50), default='')
    version_code = db.Column(db.Integer, default=0)
    default_capabilities = db.Column(db.Text, default='{}')
    icon_path = db.Column(db.String(500), default='')
    notes = db.Column(db.Text, default='')
    is_active = db.Column(db.Boolean, default=False)

    # 关系
    test_cases = db.relationship('TestCase', backref='app', lazy='dynamic')
    element_maps = db.relationship('ElementMap', backref='app', lazy='dynamic')
    snapshots = db.relationship('ElementSnapshot', backref='app', lazy='dynamic')
    executions = db.relationship('ExecutionRecord', backref='app', lazy='dynamic')
