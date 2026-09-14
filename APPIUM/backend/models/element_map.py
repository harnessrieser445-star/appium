"""
元素地图模型
用户命名保存的元素（可复用的定位器）
"""
from backend.database.db import db
from backend.models.base import BaseModel


class ElementMap(BaseModel):
    __tablename__ = 'element_maps'

    app_id = db.Column(db.Integer, db.ForeignKey('apps.id'), nullable=True, index=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, default='')
    tag = db.Column(db.String(200), default='')
    resource_id = db.Column(db.String(300), default='')
    xpath = db.Column(db.Text, nullable=False)
    content_desc = db.Column(db.Text, default='')
    text_contains = db.Column(db.Text, default='')
    page_name = db.Column(db.String(200), default='')
    screenshot_x = db.Column(db.Integer, default=0)
    screenshot_y = db.Column(db.Integer, default=0)
    locator_strategy = db.Column(db.String(30), default='xpath')
    is_active = db.Column(db.Boolean, default=True)

    # 关系
    test_steps = db.relationship('TestStep', backref='element_map', lazy='dynamic')
