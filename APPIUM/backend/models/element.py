"""
元素模型
每次快照中抓取的单个元素
"""
from backend.database.db import db
from backend.models.base import BaseModel


class Element(BaseModel):
    __tablename__ = 'elements'

    snapshot_id = db.Column(db.Integer, db.ForeignKey('element_snapshots.id', ondelete='CASCADE'), nullable=False, index=True)
    tag = db.Column(db.String(200), nullable=False)
    text = db.Column(db.Text, default='')
    content_desc = db.Column(db.Text, default='')
    resource_id = db.Column(db.String(300), default='', index=True)
    xpath = db.Column(db.Text, nullable=False)
    x1 = db.Column(db.Integer, default=0)
    y1 = db.Column(db.Integer, default=0)
    x2 = db.Column(db.Integer, default=0)
    y2 = db.Column(db.Integer, default=0)
    class_name = db.Column(db.String(300), default='')
    package_name = db.Column(db.String(200), default='')
    clickable = db.Column(db.Boolean, default=False)
    enabled = db.Column(db.Boolean, default=True)
    focusable = db.Column(db.Boolean, default=False)
    scrollable = db.Column(db.Boolean, default=False)
    checked = db.Column(db.Boolean, default=False)
    bounds_hash = db.Column(db.String(64), default='')
