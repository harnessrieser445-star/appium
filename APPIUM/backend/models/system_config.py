"""
系统配置KV模型
"""
from datetime import datetime
from backend.database.db import db


class SystemConfig(db.Model):
    """系统配置表，不继承BaseModel（使用key作为主键）"""
    __tablename__ = 'system_config'

    key = db.Column(db.String(200), primary_key=True)
    value = db.Column(db.Text, default='')
    value_type = db.Column(db.String(20), default='string')
    description = db.Column(db.Text, default='')
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    def to_dict(self):
        return {
            'key': self.key,
            'value': self.typed_value,
            'value_type': self.value_type,
            'description': self.description,
            'updated_at': self.updated_at.strftime('%Y-%m-%d %H:%M:%S') if self.updated_at else None
        }

    @property
    def typed_value(self):
        """根据value_type返回转换后的值"""
        v = self.value
        t = self.value_type
        if t == 'bool':
            return str(v).lower() in ('true', '1', 'yes', 'on')
        elif t == 'int':
            try:
                return int(v)
            except (ValueError, TypeError):
                return 0
        elif t == 'float':
            try:
                return float(v)
            except (ValueError, TypeError):
                return 0.0
        elif t == 'json':
            import json
            try:
                return json.loads(v) if v else {}
            except (json.JSONDecodeError, TypeError):
                return {}
        return v  # string
