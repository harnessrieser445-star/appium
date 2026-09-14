"""
执行记录和步骤执行结果模型
ExecutionRecord 1 ── N ExecutionStepResult (CASCADE)
"""
import uuid
from datetime import datetime
from backend.database.db import db
from backend.models.base import BaseModel


def generate_task_id():
    """生成异步任务UUID"""
    return uuid.uuid4().hex


class ExecutionRecord(BaseModel):
    __tablename__ = 'execution_records'

    task_id = db.Column(db.String(64), nullable=False, unique=True, index=True, default=generate_task_id)
    case_id = db.Column(db.Integer, db.ForeignKey('test_cases.id'), nullable=True, index=True)
    device_id = db.Column(db.Integer, db.ForeignKey('devices.id'), nullable=True, index=True)
    app_id = db.Column(db.Integer, db.ForeignKey('apps.id'), nullable=True)
    device_udid = db.Column(db.String(200), default='')
    status = db.Column(db.String(20), default='pending', index=True)
    total_steps = db.Column(db.Integer, default=0)
    passed_steps = db.Column(db.Integer, default=0)
    failed_steps = db.Column(db.Integer, default=0)
    skipped_steps = db.Column(db.Integer, default=0)
    error_message = db.Column(db.Text, default='')
    error_screenshot = db.Column(db.String(500), default='')
    error_page_source = db.Column(db.String(500), default='')
    continue_on_failure = db.Column(db.Boolean, default=False)
    triggered_by = db.Column(db.String(20), default='manual')
    started_at = db.Column(db.DateTime, nullable=True)
    finished_at = db.Column(db.DateTime, nullable=True)
    duration_ms = db.Column(db.Integer, default=0)
    appium_session_id = db.Column(db.String(200), default='')
    log_output = db.Column(db.Text, default='')

    # 关系
    step_results = db.relationship(
        'ExecutionStepResult',
        backref='execution',
        cascade='all, delete-orphan',
        order_by='ExecutionStepResult.step_order',
        lazy='joined'
    )

    __table_args__ = (
        db.Index('idx_exec_created', 'created_at'),
    )

    def to_dict(self):
        d = super().to_dict()
        d['step_results'] = [r.to_dict() for r in self.step_results]
        return d

    def start(self):
        """标记执行开始"""
        self.status = 'running'
        self.started_at = datetime.now()

    def finish(self, success: bool, error_msg: str = ''):
        """标记执行结束"""
        self.finished_at = datetime.now()
        if self.started_at:
            self.duration_ms = int((self.finished_at - self.started_at).total_seconds() * 1000)
        self.status = 'pass' if success else 'fail'
        if error_msg:
            self.error_message = error_msg


class ExecutionStepResult(BaseModel):
    __tablename__ = 'execution_step_results'

    execution_id = db.Column(db.Integer, db.ForeignKey('execution_records.id', ondelete='CASCADE'), nullable=False, index=True)
    step_id = db.Column(db.Integer, db.ForeignKey('test_steps.id'), nullable=True)
    step_order = db.Column(db.Integer, nullable=False)
    action = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text, default='')
    success = db.Column(db.Boolean, nullable=False)
    status = db.Column(db.String(20), default='pass')
    message = db.Column(db.Text, default='')
    screenshot_path = db.Column(db.String(500), default='')
    duration_ms = db.Column(db.Integer, default=0)
    retry_count = db.Column(db.Integer, default=0)
    elem_found = db.Column(db.Boolean, default=True)
    elem_xpath_used = db.Column(db.Text, default='')
    log_output = db.Column(db.Text, default='')
    executed_at = db.Column(db.DateTime, default=datetime.now)
