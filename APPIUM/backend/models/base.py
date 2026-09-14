"""
Model基类
所有Model继承此类，自动包含公共字段 id / created_at / updated_at
"""
from datetime import datetime
from backend.database.db import db


class BaseModel(db.Model):
    """抽象基类，不创建独立表"""
    __abstract__ = True

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    def to_dict(self):
        """转为字典，子类可覆盖以处理JSON字段等"""
        result = {}
        for c in self.__table__.columns:
            val = getattr(self, c.name)
            if isinstance(val, datetime):
                val = val.strftime('%Y-%m-%d %H:%M:%S') if val else None
            result[c.name] = val
        return result
