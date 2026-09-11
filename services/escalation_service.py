# services/escalation_service.py
"""告警升级联动引擎（SEL / 通用告警）。

对持续未确认(escalate_if_unacknowledged)达到 escalate_after 秒的活跃告警：
  - 提升 severity 到 target_severity
  - 按 target_users / target_actions 加频推送通知
    （重复升级按 repeat_interval 间隔、max_escalations 封顶）
  - 写入 alert_escalation_logs 历史，policy.escalation_count 累计

适用范围通过 AlertEscalation.metric_type 限定：空/all=全部告警，
bmc_sel=仅 iDRAC 带外 SEL 告警（metric_type='bmc_sel'）。
"""
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def _now():
    return datetime.utcnow()


def _device_label(ev):
    try:
        dev = ev.device
    except Exception:
        dev = None
    if dev is None:
        return ''
    return getattr(dev, 'name', '') or ''


_DEFAULT_TEMPLATE = (
    "【告警升级】{title}\n"
    "设备：{device}\n"
    "级别：{severity} -> {to_severity}（升级 {level} 级）\n"
    "首次发生：{first_occurred}\n"
    "详情：{message}"
)


def _render_message(template, ev, policy, level, from_sev, to_sev):
    if not template:
        template = _DEFAULT_TEMPLATE
    values = {
        'title': ev.title or '',
        'message': ev.message or '',
        'severity': from_sev or ev.severity or '',
        'from_severity': from_sev or '',
        'to_severity': to_sev or '',
        'level': level,
        'metric_type': ev.metric_type or '',
        'alert_id': ev.id or '',
        'device': _device_label(ev),
        'first_occurred': ev.first_occurred.isoformat() if ev.first_occurred else '',
        'policy': policy.name or '',
    }
    out = template
    for k, v in values.items():
        out = out.replace('{%s}' % k, str(v))
    return out


def _send_channel(channel, users, title, content):
    """Send an escalation notification through a named channel."""
    from services import notification_service as ns
    users = users or []
    channel = (channel or 'email').lower()
    try:
        if channel == 'email':
            return ns.send_email(users, title, content)
        if channel == 'wechat':
            return ns.send_wechat(users, title, content)
        if channel == 'webhook':
            return ns.send_webhook(users, content)
        if channel == 'dingtalk':
            return ns.send_dingtalk(users, title, content)
        if channel == 'feishu':
            return ns.send_feishu(users, title, content)
        if channel == 'slack':
            return ns.send_slack(users, None, content)
        return False, 'unknown channel: %s' % channel
    except Exception as e:
        logger.exception('escalation send failed on %s: %s', channel, e)
        return False, str(e)


def _policy_logs(session, ev, policy):
    from models.models import AlertEscalationLog
    return (session.query(AlertEscalationLog)
            .filter_by(alert_id=ev.id, policy_id=policy.id)
            .order_by(AlertEscalationLog.escalated_at.desc()).all())


def _find_policy_alerts(session, policy):
    """Active (non-suppressed) alerts matching the policy's scope + ack rule.

    Severity matching is intentionally left to the caller (against the
    severity snapshot taken at run start) so that:
      * an alert already escalated by this policy stays a candidate for
        repeat escalation even after its severity was raised;
      * several overlapping policies can each fire on the same alert within
        one run before any of them mutates its severity.
    """
    from models.models import AlertEvent
    q = (session.query(AlertEvent)
         .filter(AlertEvent.status == 'active',
                 AlertEvent.suppressed.isnot(True)))
    mt = (policy.metric_type or '').strip().lower()
    if mt and mt != 'all':
        q = q.filter(AlertEvent.metric_type == policy.metric_type)
    if policy.escalate_if_unacknowledged:
        q = q.filter(AlertEvent.acknowledged_at.is_(None))
    return q.all()


def _escalation_due(session, ev, policy, now, logs):
    """Return (level, due) for a candidate alert under a policy."""
    level = len(logs)
    max_esc = int(policy.max_escalations or 3)
    if level >= max_esc:
        return level, False
    if not logs:
        anchor = ev.first_occurred or ev.created_at or now
        delay = int(policy.escalate_after or 300)
        return level, (now - anchor).total_seconds() >= delay
    interval = int(policy.repeat_interval or 0)
    if interval <= 0:
        return level, False
    last = logs[0].escalated_at or now
    return level, (now - last).total_seconds() >= interval


def create_work_order_from_alert(session, alert, source='escalation',
                                 requester_name='告警升级引擎'):
    """由告警自动生成/复用一张事件工单并回链（幂等）。

    - 告警已有工单 -> 直接返回已有工单
    - 告警有 correlation_group -> 复用组级未关闭自动工单（避免同组多张）
    - 否则 -> 生成单张 incident 工单并回链 alert.work_order_id

    Returns:
        (WorkOrder|None, created: bool)
    """
    from models.maintenance_models import WorkOrder
    if alert.work_order_id:
        wo = session.get(WorkOrder, alert.work_order_id)
        if wo:
            return wo, False
    group = getattr(alert, 'correlation_group', None)
    if group:
        existing_wo = (session.query(WorkOrder)
                       .filter(WorkOrder.correlation_group == group,
                               WorkOrder.auto_created.is_(True),
                               WorkOrder.status.in_(['open', 'assigned',
                                                     'in_progress', 'on_hold']))
                       .first())
        if existing_wo:
            alert.work_order_id = existing_wo.id
            return existing_wo, False
    device = None
    try:
        device = alert.device
    except Exception:
        device = None
    priority = ('critical' if alert.severity in ('critical', 'error')
                else 'high' if alert.severity == 'warning' else 'medium')
    wo = WorkOrder(
        title='[升级] %s' % (alert.title or '告警'),
        description=('由告警升级自动生成\n来源：%s\n告警级别：%s\n%s'
                     % (source, alert.severity, alert.message or '')),
        work_order_type='incident',
        category='escalation',
        priority=priority,
        impact='medium',
        urgency='medium',
        device_id=alert.device_id,
        device_name=getattr(device, 'name', None) if device else None,
        status='open',
        correlation_group=group,
        auto_created=True,
        requester_name=requester_name,
        created_by=requester_name,
    )
    wo.generate_work_order_number()  # 先生成编号（work_order_number 非空），再 flush
    session.add(wo)
    session.flush()
    try:
        wo.apply_sla_policy()
        wo.compute_sla_status()
    except Exception as e:
        logger.warning('work order SLA compute skipped: %s', e)
    alert.work_order_id = wo.id
    return wo, True


def run_escalations(app=None, session=None):
    """Run the escalation engine over all enabled policies.

    Args:
        app: Flask app (wraps execution in app_context) or None.
        session: DB session; defaults to db.session (needs app context).

    Returns:
        list of dicts describing each performed escalation.
    """
    from extensions import db
    if app is not None:
        with app.app_context():
            return _run_impl(session or db.session)
    return _run_impl(session or db.session)


def _run_impl(session):
    from models.models import AlertEscalation, AlertEvent
    try:
        policies = (session.query(AlertEscalation)
                    .filter(AlertEscalation.enabled.is_(True)).all())
    except Exception as e:
        # 新列/表尚未迁移时优雅降级（例如未运行 patch_schema 的 MySQL 库）
        logger.warning('escalation scan skipped (schema not migrated?): %s', e)
        return []
    if not policies:
        return []
    now = _now()
    performed = []

    # 本批次开始时各活跃告警的原始级别快照：同一轮扫描内，多个策略可各自
    # 依据原始级别触发，避免第一个策略升级后影响后续策略的匹配。
    active = (session.query(AlertEvent)
              .filter(AlertEvent.status == 'active',
                      AlertEvent.suppressed.isnot(True)).all())
    orig_sev = {ev.id: (ev.severity or '').strip().lower() for ev in active}

    for policy in policies:
        orig = (policy.original_severity or '').strip().lower()
        if orig in ('', 'all'):
            continue  # must define a starting severity to escalate
        try:
            for ev in _find_policy_alerts(session, policy):
                logs = _policy_logs(session, ev, policy)
                level = len(logs)
                orig_match = orig_sev.get(ev.id, '') == orig
                if not (orig_match or level > 0):
                    continue
                level, due = _escalation_due(session, ev, policy, now, logs)
                if not due:
                    continue

                from_sev = ev.severity or ''
                to_sev = policy.target_severity or ev.severity or from_sev
                new_level = level + 1
                ev.severity = to_sev
                ev.updated_at = now
                policy.escalation_count = (policy.escalation_count or 0) + 1

                note = "\n[升级] L%d %s -> %s (%s)" % (
                    new_level, from_sev, to_sev,
                    now.strftime('%Y-%m-%d %H:%M'))
                ev.message = ((ev.message or '') + note)[:5000]

                content = _render_message(
                    policy.escalation_message, ev, policy,
                    new_level, from_sev, to_sev)
                title = '【告警升级】%s -> %s | %s' % (
                    from_sev, to_sev, (ev.title or '')[:60])
                users = policy.get_target_users() or []
                actions = policy.get_target_actions() or (['email'] if users else [])

                channels = []
                for ch in actions:
                    ok, msg = _send_channel(ch, users, title, content)
                    channels.append(ch)
                    logger.info('escalation notify [%s] alert=%s -> %s (%s)',
                                ch, ev.id, ok, msg)
                # 升级后自动建工单（幂等；失败不影响升级本身，回滚到保存点）
                wo_id = None
                wo_number = None
                if policy.auto_create_work_order:
                    try:
                        with session.begin_nested():
                            wo, _created = create_work_order_from_alert(
                                session, ev, source='escalation')
                            if wo:
                                wo_id = wo.id
                                wo_number = wo.work_order_number
                    except Exception as e:
                        logger.exception('escalation auto work-order failed '
                                         'for alert %s: %s', ev.id, e)

                # 单条升级记录（level 用于去重/加频计数），渠道合并展示
                session.add(_make_log(session, ev, policy, new_level,
                                      from_sev, to_sev,
                                      ','.join(channels) or 'none',
                                      users, content, wo_id))

                performed.append({
                    'alert_id': ev.id,
                    'policy_id': policy.id,
                    'policy': policy.name,
                    'level': new_level,
                    'from_severity': from_sev,
                    'to_severity': to_sev,
                    'channels': channels,
                    'title': ev.title,
                    'work_order_id': wo_id,
                    'work_order_number': wo_number,
                })
        except Exception as e:
            session.rollback()
            logger.exception('escalation policy %s failed: %s', policy.name, e)
    try:
        session.commit()
    except Exception as e:
        session.rollback()
        logger.exception('escalation commit failed: %s', e)
    return performed


def _make_log(session, ev, policy, level, from_sev, to_sev, channel, users, content,
              work_order_id=None):
    from models.models import AlertEscalationLog
    return AlertEscalationLog(
        alert_id=ev.id,
        policy_id=policy.id,
        level=level,
        from_severity=from_sev,
        to_severity=to_sev,
        channel=channel,
        target=','.join(users or []),
        message=content,
        work_order_id=work_order_id,
        escalated_at=_now(),
    )
