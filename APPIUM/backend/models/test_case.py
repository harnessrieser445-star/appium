"""
测试用例和测试步骤模型
TestCase 1 ── N TestStep (CASCADE)
"""
from backend.database.db import db
from backend.models.base import BaseModel


class TestCase(BaseModel):
    __tablename__ = 'test_cases'

    app_id = db.Column(db.Integer, db.ForeignKey('apps.id'), nullable=True, index=True)
    name = db.Column(db.String(200), nullable=False, unique=True, index=True)
    description = db.Column(db.Text, default='')
    tags = db.Column(db.Text, default='[]')
    step_count = db.Column(db.Integer, default=0)
    priority = db.Column(db.String(10), default='P1')
    timeout = db.Column(db.Integer, default=300)
    continue_on_failure = db.Column(db.Boolean, default=False)
    last_run_at = db.Column(db.DateTime, nullable=True)
    last_run_status = db.Column(db.String(20), nullable=True)
    last_run_duration_ms = db.Column(db.Integer, nullable=True)
    run_count = db.Column(db.Integer, default=0)
    pass_count = db.Column(db.Integer, default=0)

    # 关系
    steps = db.relationship(
        'TestStep',
        backref='case',
        cascade='all, delete-orphan',
        order_by='TestStep.step_order',
        lazy='joined'
    )
    scripts = db.relationship('Script', backref='case', lazy='dynamic')
    executions = db.relationship('ExecutionRecord', backref='case', lazy='dynamic')

    def to_dict(self):
        d = super().to_dict()
        d['steps'] = [s.to_dict() for s in self.steps]
        return d


class TestStep(BaseModel):
    __tablename__ = 'test_steps'

    case_id = db.Column(db.Integer, db.ForeignKey('test_cases.id', ondelete='CASCADE'), nullable=False, index=True)
    step_order = db.Column(db.Integer, nullable=False)
    action = db.Column(db.String(50), nullable=False)
    action_params = db.Column(db.Text, default='{}')
    description = db.Column(db.Text, default='')
    element_map_id = db.Column(db.Integer, db.ForeignKey('element_maps.id'), nullable=True)
    elem_snapshot_data = db.Column(db.Text, nullable=True)
    timeout = db.Column(db.Integer, default=30)
    retry_count = db.Column(db.Integer, default=1)
    is_enabled = db.Column(db.Boolean, default=True)

    __table_args__ = (
        db.Index('idx_steps_case_order', 'case_id', 'step_order'),
    )
