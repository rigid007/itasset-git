"""事件归一化 / 关联规则引擎

纯函数实现，接收 SQLAlchemy session 与一个 AlertEvent 行对象，按启用的
EventCorrelationRule (按 priority_order 升序) 处理：
  - 归一化标题 (normalize_template)
  - suppress : 若抑制窗口内存在同 correlation_group 的活跃告警，则抑制当前告警
               (suppressed=True, occurrence_count 累加到已有告警)，返回已存在告警
  - group    : 同 suppress 但设置 correlation_group，便于后续按组生成事件工单
  - raise_severity / set_priority : 改写告警的 severity / 工单优先级
"""
from datetime import datetime, timedelta
import re


def _match(rule, alert):
    """判断告警是否命中规则的匹配条件"""
    scope_val = {
        'title': alert.title or '',
        'message': alert.message or '',
        'severity': alert.severity or '',
        'source': (alert.device.name if alert.device else '') or '',
    }.get(rule.match_scope, '')
    target = rule.match_value or ''
    op_ = rule.match_operator or 'contains'
    if op_ == 'equals':
        return scope_val == target
    if op_ == 'not_contains':
        return target not in scope_val
    if op_ == 'regex':
        try:
            return re.search(target, scope_val) is not None
        except re.error:
            return False
    # 默认 contains
    return target in scope_val


def _normalize_title(rule, alert):
    tpl = rule.normalize_template or ''
    if not tpl:
        return None
    host = alert.device.name if alert.device else ''
    ip = alert.device.ip_address if alert.device else ''
    return tpl.replace('{host}', host).replace('{ip}', ip or '')


def _group_key(rule, alert):
    if rule.group_by == 'device_id':
        return f'dev:{alert.device_id}'
    return f'rule:{rule.id}'


def ensure_group_ticket(session, alert, rule):
    """按 correlation_group 自动生成/复用单一事件工单并关联同组告警。

    同一 correlation_group 在全生命周期内仅保留一张未关闭的自动工单。
    """
    from models.maintenance_models import WorkOrder
    group = alert.correlation_group
    if not group:
        return None
    existing_wo = WorkOrder.query.filter_by(correlation_group=group, auto_created=True).filter(
        WorkOrder.status.in_(['open', 'assigned', 'in_progress', 'on_hold'])
    ).first()
    if existing_wo:
        if not alert.work_order_id:
            alert.work_order_id = existing_wo.id
        return existing_wo
    wo = WorkOrder(
        title=f'[自动] {alert.title}',
        description=alert.message or alert.title,
        work_order_type='incident',
        category='auto_correlation',
        priority=alert.severity or 'medium',
        impact='medium',
        urgency='medium',
        device_id=alert.device_id,
        status='open',
        correlation_group=group,
        auto_created=True,
        requester_name='事件关联引擎',
    )
    session.add(wo)
    session.flush()
    wo.generate_work_order_number()
    alert.work_order_id = wo.id
    return wo


def process_alert_correlation(session, alert):
    """对单个告警应用关联规则。返回 (处理动作描述, 被关联/抑制的已存在告警或None)。

    注意：调用方负责在 session 内并已 flush 后提交。
    """
    from models.models import AlertEvent
    from models.maintenance_models import EventCorrelationRule

    rules = EventCorrelationRule.query.filter_by(enabled=True) \
        .order_by(EventCorrelationRule.priority_order.asc()).all()
    if not rules:
        return ('no_rules', None)

    result_action = 'none'
    suppressed_into = None

    for rule in rules:
        if not _match(rule, alert):
            continue

        # 归一化标题
        norm = _normalize_title(rule, alert)
        if norm:
            alert.title = norm

        # 设置分组键
        if rule.group_by and rule.group_by != 'none':
            alert.correlation_group = _group_key(rule, alert)

        # 改写级别/优先级
        if rule.action == 'raise_severity' and rule.new_severity:
            order = {'low': 1, 'medium': 2, 'high': 3, 'critical': 4}
            if order.get(rule.new_severity, 0) > order.get(alert.severity, 0):
                alert.severity = rule.new_severity
        elif rule.action == 'set_priority' and rule.new_priority:
            alert.severity = rule.new_priority  # 告警优先级以 severity 承载

        # 抑制 / 分组：查找窗口内同组活跃告警
        if rule.action in ('suppress', 'group'):
            window = rule.suppression_window_min or 60
            since = datetime.utcnow() - timedelta(minutes=window)
            existing = AlertEvent.query.filter(
                AlertEvent.device_id == alert.device_id,
                AlertEvent.status == 'active',
                AlertEvent.suppressed.is_(False),
                AlertEvent.last_occurred >= since,
            )
            if alert.correlation_group:
                existing = existing.filter(AlertEvent.correlation_group == alert.correlation_group)
            else:
                existing = existing.filter(AlertEvent.title == alert.title)
            existing = existing.order_by(AlertEvent.last_occurred.desc()).first()
            if existing and existing.id != alert.id:
                existing.occurrence_count = (existing.occurrence_count or 1) + 1
                existing.last_occurred = datetime.utcnow()
                if alert.message:
                    existing.message = alert.message
                alert.suppressed = True
                alert.status = 'suppressed'
                suppressed_into = existing
                result_action = rule.action
                # 自动生成/复用按组单一事件工单
                if rule.auto_ticket:
                    ticket = ensure_group_ticket(session, existing, rule)
                    if ticket and not alert.work_order_id:
                        alert.work_order_id = ticket.id
                return (rule.action, existing)
            else:
                # 无可抑制的同组活跃告警：本告警成为「代表」，保留活跃等待归并
                if rule.auto_ticket:
                    ensure_group_ticket(session, alert, rule)
                result_action = rule.action
                break  # 代表告警保留活跃，后续同组告警将归并到同一工单

        result_action = rule.action
        break  # 命中一条「改写类」规则即停止

    return (result_action, suppressed_into)


def run_correlation_on_existing(session, limit=500):
    """对库中仍活跃的未抑制告警批量执行关联（去重/归一化）。返回处理计数。"""
    from models.models import AlertEvent
    from models.maintenance_models import EventCorrelationRule

    if not EventCorrelationRule.query.filter_by(enabled=True).count():
        return {'checked': 0, 'suppressed': 0, 'normalized': 0}

    alerts = AlertEvent.query.filter(
        AlertEvent.status == 'active',
        AlertEvent.suppressed.is_(False)
    ).order_by(AlertEvent.last_occurred.asc()).limit(limit).all()

    suppressed = 0
    normalized = 0
    for alert in alerts:
        action, _ = process_alert_correlation(session, alert)
        if action == 'suppress':
            suppressed += 1
        elif action in ('group', 'raise_severity', 'set_priority'):
            normalized += 1
    return {'checked': len(alerts), 'suppressed': suppressed, 'normalized': normalized}
