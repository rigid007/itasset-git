"""工单 SLA 实时违约检测任务

周期性扫描未关闭工单，计算 SLA 状态（monitoring / breached），
为 ITIL/ISO20000 的“服务级别管理”提供超时预警依据。
"""
from datetime import datetime

from extensions import db
from models.maintenance_models import WorkOrder


def monitor_work_order_sla(app):
    """扫描进行中的工单并更新 SLA 违约状态"""
    with app.app_context():
        try:
            open_orders = WorkOrder.query.filter(
                WorkOrder.status.in_(['open', 'assigned', 'in_progress', 'on_hold'])
            ).all()
            breached = 0
            for wo in open_orders:
                if wo.compute_sla_status() == 'breached':
                    breached += 1
            db.session.commit()
            if breached:
                app.logger.warning(f"[SLA] 检测到 {breached} 个工单 SLA 已超时")
        except Exception as e:
            app.logger.error(f"[SLA] 监控任务执行失败: {e}")
