"""
元素快照批次模型
每次"获取元素数据"产生一条快照记录
"""
from backend.database.db import db
from backend.models.base import BaseModel


class ElementSnapshot(BaseModel):
    __tablename__ = 'element_snapshots'

    device_id = db.Column(db.Integer, db.ForeignKey('devices.id'), nullable=True, index=True)
    app_id = db.Column(db.Integer, db.ForeignKey('apps.id'), nullable=True)
    page_name = db.Column(db.String(200), default='current')
    package_name = db.Column(db.String(200), default='')
    activity_name = db.Column(db.String(300), default='')
    screenshot_path = db.Column(db.String(500), default='')
    page_source_path = db.Column(db.String(500), default='')
    element_count = db.Column(db.Integer, default=0)
    screen_width = db.Column(db.Integer, default=0)
    screen_height = db.Column(db.Integer, default=0)

    # 关系
    elements = db.relationship('Element', backref='snapshot', cascade='all, delete-orphan', lazy='dynamic')

    __table_args__ = (
        db.Index('idx_snapshots_created', 'created_at'),
    )
