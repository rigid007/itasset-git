"""巡检任务监控与到期提醒。

生产环境建议每 30 分钟执行一次：
- 将超过 due_date 的待处理/进行中巡检任务标记为 overdue；
- 对尚未执行且临近到期的任务写入应用日志，便于后续接入邮件/企业微信通知。
"""
from datetime import datetime, timedelta

from extensions import db
from models.maintenance_models import InspectionTask


def monitor_inspection_tasks(app):
    """巡检任务监控入口，由 scheduler.py 调用。"""
    with app.app_context():
        now = datetime.utcnow()
        today = now.date()

        overdue = InspectionTask.query.filter(
            InspectionTask.status.in_(['pending', 'in_progress']),
            InspectionTask.due_date.isnot(None),
            InspectionTask.due_date < today,
        ).all()
        for task in overdue:
            task.status = 'overdue'
            task.updated_at = now
        if overdue:
            db.session.commit()
            app.logger.warning(f'[巡检] 已将 {len(overdue)} 个巡检任务标记为逾期')

        # 提前 reminder_days 天的任务写入日志，作为提醒扩展点
        remind_start = today
        remind_end = today + timedelta(days=7)
        reminders = InspectionTask.query.filter(
            InspectionTask.status == 'pending',
            InspectionTask.due_date.between(remind_start, remind_end),
            InspectionTask.reminder_days > 0,
        ).all()
        for task in reminders:
            days_left = (task.due_date - today).days
            app.logger.info(
                f'[巡检提醒] 任务 {task.task_number}「{task.title}」'
                f'负责人 {task.assigned_to_name or "未分配"}，'
                f'剩余 {days_left} 天到期'
            )
        return len(overdue), len(reminders)
