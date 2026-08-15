"""ITIL 增强 G-J 后端

G. 问题 -> 已知错误库(KEDB) 与知识库联动
H. 持续改进(CSI) 闭环 + MTTR/可用率度量仪表盘
I. 服务目录级 SLA 与上报流程
J. 事件归一化/关联规则引擎 (规则管理 + 手动执行)

蓝图名: itsm_adv_bp
"""
from flask import (
    Blueprint, request, redirect, url_for, flash, render_template,
    jsonify, Response,
)
from flask_login import login_required, current_user
from utils.permission import permission_required
from utils.audit import log_audit
from extensions import db
from datetime import datetime, timedelta
from sqlalchemy import func
from models.models import User, Device, AlertEvent
from models.maintenance_models import (
    WorkOrder, ProblemRecord, KnownError, KnowledgeArticle, ServiceCatalog,
    SLAPolicy, CSIImprovement, EventCorrelationRule,
    CSATSurvey, AvailabilityRecord, ChangeImpactAnalysis, ChangeRequest,
)
from utils.availability import collect_availability, get_real_availability
from utils.change_impact import simulate_change_impact, persist_impact_analysis

itsm_adv_bp = Blueprint('itsm_adv', __name__)


# ===========================================================================
# 通用度量计算
# ===========================================================================
def _median(values):
    vals = sorted([v for v in values if v is not None])
    if not vals:
        return None
    n = len(vals)
    mid = n // 2
    return vals[mid] if n % 2 else round((vals[mid - 1] + vals[mid]) / 2, 2)


def _window():
    end = datetime.utcnow()
    days = request.args.get('days', 30, type=int)
    start = end - timedelta(days=days)
    return start, end, days


def compute_metrics(start, end, service_id=None):
    """计算工单度量：MTTR、响应MTTR、SLA达标率、工单量、可用率、CSAT。

    可用率优先采用「对接监控/设备状态的真实采集」(AvailabilityRecord)，
    无采集数据时对服务级回退到基于工单解决时长的代理算法。
    """
    q = WorkOrder.query.filter(
        WorkOrder.requested_at >= start,
        WorkOrder.requested_at <= end,
    )
    if service_id:
        q = q.filter(WorkOrder.service_catalog_id == service_id)
    orders = q.all()

    resolved = [o for o in orders if o.status in ('resolved', 'closed')]
    res_times = [o.resolution_time for o in resolved if o.resolution_time is not None]
    resp_times = [o.actual_response_time for o in orders if o.actual_response_time is not None]

    sla_res_set = [o for o in orders if o.sla_resolution_time]
    sla_res_met = [o for o in sla_res_set if o.sla_resolution_met is True]
    sla_resp_set = [o for o in orders if o.sla_response_time]
    sla_resp_met = [o for o in sla_resp_set if o.sla_response_met is True]

    # 可用率：优先真实采集，否则代理
    availability, availability_source = _resolve_availability(start, end, service_id, res_times)

    csat = _compute_csat(service_id)

    by_category = {}
    for o in orders:
        by_category[o.category or '未分类'] = by_category.get(o.category or '未分类', 0) + 1
    by_priority = {}
    for o in orders:
        by_priority[o.priority or '未分类'] = by_priority.get(o.priority or '未分类', 0) + 1

    return {
        'total': len(orders),
        'resolved': len(resolved),
        'mttr_avg': round(sum(res_times) / len(res_times), 2) if res_times else None,
        'mttr_median': _median(res_times),
        'response_mttr_avg': round(sum(resp_times) / len(resp_times), 2) if resp_times else None,
        'sla_resolution_compliance': round(100.0 * len(sla_res_met) / len(sla_res_set), 1) if sla_res_set else None,
        'sla_response_compliance': round(100.0 * len(sla_resp_met) / len(sla_resp_set), 1) if sla_resp_set else None,
        'availability': availability,
        'availability_source': availability_source,
        'csat_avg': csat['avg'],
        'csat_count': csat['count'],
        'csat_distribution': csat['distribution'],
        'by_category': by_category,
        'by_priority': by_priority,
    }


def _resolve_availability(start, end, service_id, res_times):
    """真实采集优先；无数据时对服务级回退代理算法。返回 (pct, source)。"""
    if service_id:
        real = get_real_availability(service_id, start, end)
        if real is not None:
            return real, 'real'
    period_hours = max((end - start).total_seconds() / 3600, 1)
    total_downtime = sum(res_times) if res_times else 0.0
    availability = max(0.0, 100.0 * (1 - total_downtime / period_hours))
    availability = round(min(availability, 100.0), 2)
    return availability, 'proxy'


def _compute_csat(service_id=None):
    """计算 CSAT 均值与分布。返回 dict。"""
    q = CSATSurvey.query
    if service_id:
        q = q.filter_by(service_catalog_id=service_id)
    surveys = q.all()
    ratings = [s.rating for s in surveys if s.rating]
    if not ratings:
        return {'avg': None, 'count': 0, 'distribution': {str(i): 0 for i in range(1, 6)}}
    avg = round(sum(ratings) / len(ratings), 2)
    dist = {str(i): 0 for i in range(1, 6)}
    for r in ratings:
        dist[str(r)] = dist.get(str(r), 0) + 1
    return {'avg': avg, 'count': len(ratings), 'distribution': dist}


# ===========================================================================
# H. 持续改进(CSI) 闭环 + 度量仪表盘
# ===========================================================================
@itsm_adv_bp.route('/csi')
@login_required
@permission_required('csi:view')
def csi_dashboard():
    start, end, days = _window()
    metrics = compute_metrics(start, end)
    csis = CSIImprovement.query.order_by(CSIImprovement.created_at.desc()).all()
    status_counts = {}
    for c in csis:
        status_counts[c.status] = status_counts.get(c.status, 0) + 1
    return render_template('maintenance/csi_dashboard.html',
                           metrics=metrics, csis=csis, status_counts=status_counts,
                           days=days, start=start, end=end)


@itsm_adv_bp.route('/csi/register', methods=['GET', 'POST'])
@login_required
@permission_required('csi:edit')
def csi_register():
    if request.method == 'POST':
        try:
            ci = CSIImprovement(
                code=f'CSI{datetime.utcnow().strftime("%Y%m%d%H%M%S")}',
                title=request.form['title'],
                description=request.form.get('description', ''),
                source_type=request.form.get('source_type', 'audit'),
                source_id=request.form.get('source_id', type=int),
                status='proposed',
                priority=request.form.get('priority', 'medium'),
                owner_id=request.form.get('owner_id', type=int),
                target_metric=request.form.get('target_metric', ''),
                baseline_value=request.form.get('baseline_value', type=float),
                target_value=request.form.get('target_value', type=float),
                expected_benefit=request.form.get('expected_benefit', ''),
                created_by=current_user.id,
            )
            db.session.add(ci)
            db.session.commit()
            log_audit('create', 'csi', ci.id, f"登记持续改进: {ci.title}", user_id=current_user.id)
            flash('持续改进项已登记', 'success')
            return redirect(url_for('itsm_adv.csi_dashboard'))
        except Exception as e:
            db.session.rollback()
            flash(f'登记失败: {e}', 'danger')

    users = User.query.filter_by(is_active=True).all()
    # 可从 问题/变更/工单 预填
    prefill = {
        'source_type': request.args.get('source_type', 'audit'),
        'source_id': request.args.get('source_id', type=int),
        'title': request.args.get('title', ''),
    }
    return render_template('maintenance/csi_form.html', ci=None, users=users, prefill=prefill)


@itsm_adv_bp.route('/csi/<int:ci_id>/edit', methods=['GET', 'POST'])
@login_required
@permission_required('csi:edit')
def csi_edit(ci_id):
    ci = CSIImprovement.query.get_or_404(ci_id)
    if request.method == 'POST':
        try:
            ci.title = request.form['title']
            ci.description = request.form.get('description', '')
            ci.source_type = request.form.get('source_type', ci.source_type)
            ci.source_id = request.form.get('source_id', type=int)
            ci.priority = request.form.get('priority', ci.priority)
            ci.owner_id = request.form.get('owner_id', type=int)
            ci.target_metric = request.form.get('target_metric', ci.target_metric)
            ci.baseline_value = request.form.get('baseline_value', type=float)
            ci.target_value = request.form.get('target_value', type=float)
            ci.actual_value = request.form.get('actual_value', type=float)
            ci.expected_benefit = request.form.get('expected_benefit', '')
            ci.review_notes = request.form.get('review_notes', ci.review_notes)
            db.session.commit()
            log_audit('update', 'csi', ci.id, f"编辑持续改进: {ci.title}", user_id=current_user.id)
            flash('已更新', 'success')
            return redirect(url_for('itsm_adv.csi_dashboard'))
        except Exception as e:
            db.session.rollback()
            flash(f'更新失败: {e}', 'danger')

    users = User.query.filter_by(is_active=True).all()
    return render_template('maintenance/csi_form.html', ci=ci, users=users, prefill={})


@itsm_adv_bp.route('/csi/<int:ci_id>/status', methods=['POST'])
@login_required
@permission_required('csi:edit')
def csi_update_status(ci_id):
    ci = CSIImprovement.query.get_or_404(ci_id)
    new_status = request.form.get('status')
    valid = ('proposed', 'approved', 'in_progress', 'completed', 'rejected')
    if new_status in valid:
        ci.status = new_status
        if new_status == 'completed':
            ci.completed_at = datetime.utcnow()
            if request.form.get('actual_value', type=float) is not None:
                ci.actual_value = request.form.get('actual_value', type=float)
        db.session.commit()
        log_audit('update', 'csi', ci.id, f"状态推进: {new_status}", user_id=current_user.id)
        flash(f'状态已更新为: {new_status}', 'success')
    return redirect(url_for('itsm_adv.csi_dashboard'))


# ===========================================================================
# I. 服务目录级 SLA 与上报流程
# ===========================================================================
@itsm_adv_bp.route('/sla/report')
@login_required
@permission_required('report:sla')
def sla_report():
    start, end, days = _window()
    service_id = request.args.get('service_id', type=int)
    services = ServiceCatalog.query.filter_by(enabled=True).all()
    metrics = compute_metrics(start, end, service_id)
    selected = ServiceCatalog.query.get(service_id) if service_id else None
    # 各服务概览
    service_rows = []
    for s in services:
        m = compute_metrics(start, end, s.id)
        sla = s.sla_policy
        service_rows.append({
            'service': s,
            'sla': sla,
            'mttr': m['mttr_avg'],
            'compliance': m['sla_resolution_compliance'],
            'availability': m['availability'],
            'volume': m['total'],
        })
    return render_template('maintenance/sla_report.html',
                           services=services, selected=selected, metrics=metrics,
                           service_rows=service_rows, days=days, start=start, end=end)


@itsm_adv_bp.route('/sla/report/export')
@login_required
@permission_required('report:sla')
def sla_report_export():
    start, end, days = _window()
    service_id = request.args.get('service_id', type=int)
    services = ServiceCatalog.query.filter_by(enabled=True).all()
    import csv, io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(['服务名称', 'SLA策略', '工单量', '已解决', 'MTTR(小时)',
               'MTTR中位数', '响应MTTR', 'SLA解决达标%', 'SLA响应达标%', '可用率%'])
    for s in services:
        m = compute_metrics(start, end, s.id)
        w.writerow([
            s.name, (s.sla_policy.name if s.sla_policy else ''),
            m['total'], m['resolved'], m['mttr_avg'] or '', m['mttr_median'] or '',
            m['response_mttr_avg'] or '', m['sla_resolution_compliance'] or '',
            m['sla_response_compliance'] or '', m['availability'],
        ])
    if service_id:
        m = compute_metrics(start, end, service_id)
        sel = ServiceCatalog.query.get(service_id)
        w.writerow([])
        w.writerow(['[所选服务]', sel.name, m['total'], m['resolved'],
                    m['mttr_avg'] or '', m['mttr_median'] or '',
                    m['response_mttr_avg'] or '', m['sla_resolution_compliance'] or '',
                    m['sla_response_compliance'] or '', m['availability']])
    resp = Response(buf.getvalue(), mimetype='text/csv')
    resp.headers['Content-Disposition'] = f'attachment; filename=sla_report_{days}d.csv'
    return resp


@itsm_adv_bp.route('/service-catalog/<int:id>/edit', methods=['POST'])
@login_required
@permission_required('maintenance:edit')
def service_catalog_edit(id):
    sc = ServiceCatalog.query.get_or_404(id)
    try:
        sc.name = request.form.get('name', sc.name)
        sc.description = request.form.get('description', sc.description)
        sc.category = request.form.get('category', sc.category)
        sc.service_type = request.form.get('service_type', sc.service_type)
        sc.estimated_fulfillment_time = request.form.get('estimated_fulfillment_time', type=int, default=sc.estimated_fulfillment_time)
        sc.sla_policy_id = request.form.get('sla_policy_id', type=int)
        sc.enabled = request.form.get('enabled') == 'on'
        db.session.commit()
        flash('服务已更新', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'更新失败: {e}', 'danger')
    return redirect(url_for('maintenance_extra.service_catalog'))


@itsm_adv_bp.route('/service-catalog/<int:id>/devices', methods=['POST'])
@login_required
@permission_required('maintenance:edit')
def service_catalog_devices_edit(id):
    sc = ServiceCatalog.query.get_or_404(id)
    try:
        from models.models import Device
        device_ids = request.form.getlist('device_ids', type=int)
        devices = Device.query.filter(Device.id.in_(device_ids)).all() if device_ids else []
        sc.mapped_devices = devices
        db.session.commit()
        flash('服务设备映射已更新（用于真实可用率与服务级影响聚合）', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'更新失败: {e}', 'danger')
    return redirect(url_for('maintenance_extra.service_catalog'))


# ===========================================================================
# G. 问题 -> 已知错误(KEDB) 与知识库联动
# ===========================================================================
@itsm_adv_bp.route('/problem/<int:problem_id>/mark-known-error', methods=['POST'])
@login_required
@permission_required('maintenance:edit')
def problem_mark_known_error(problem_id):
    problem = ProblemRecord.query.get_or_404(problem_id)
    try:
        problem.known_error = True
        problem.known_error_ref = f'KE{datetime.utcnow().strftime("%Y%m%d%H%M%S")}'
        ke = KnownError(
            ke_number=problem.known_error_ref,
            title=problem.title,
            description=problem.description,
            symptom=problem.description,
            root_cause=problem.root_cause,
            workaround=problem.workaround,
            resolution=problem.resolution,
            severity=problem.severity,
            status='active' if problem.status != 'closed' else 'resolved',
            linked_problem_id=problem.id,
        )
        db.session.add(ke)
        db.session.flush()
        # 可选：同时生成知识库文章
        if request.form.get('create_kb') == 'on':
            art = KnowledgeArticle(
                title=f'[已知错误] {problem.title}',
                content=(f"## 症状\n{problem.description or ''}\n\n"
                         f"## 根因\n{problem.root_cause or ''}\n\n"
                         f"## 临时方案\n{problem.workaround or ''}\n\n"
                         f"## 最终方案\n{problem.resolution or ''}"),
                category='known_error',
                tags='known_error,KEDB',
                device_type=problem.device.type if problem.device else '',
                vendor=problem.device.vendor if problem.device else '',
                author_id=current_user.id,
                status='published',
                published_at=datetime.utcnow(),
            )
            db.session.add(art)
            db.session.flush()
            ke.knowledge_article_id = art.id
        db.session.commit()
        log_audit('update', 'problem', problem.id, f"标记为已知错误 {ke.ke_number}", user_id=current_user.id)
        flash(f'已登记为已知错误 {ke.ke_number}', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'操作失败: {e}', 'danger')
    return redirect(url_for('maintenance_extra.problem_detail', id=problem.id))


@itsm_adv_bp.route('/known-error/<int:ke_id>/link-kb', methods=['POST'])
@login_required
@permission_required('maintenance:edit')
def known_error_link_kb(ke_id):
    ke = KnownError.query.get_or_404(ke_id)
    try:
        art = KnowledgeArticle(
            title=f'[已知错误] {ke.title}',
            content=(f"## 症状\n{ke.symptom or ''}\n\n"
                     f"## 根因\n{ke.root_cause or ''}\n\n"
                     f"## 临时方案\n{ke.workaround or ''}\n\n"
                     f"## 最终方案\n{ke.resolution or ''}"),
            category='known_error',
            tags='known_error,KEDB',
            author_id=current_user.id,
            status='published',
            published_at=datetime.utcnow(),
        )
        db.session.add(art)
        db.session.flush()
        ke.knowledge_article_id = art.id
        if ke.status == 'resolved' and not ke.resolution:
            pass
        db.session.commit()
        log_audit('update', 'known_error', ke.id, f"生成知识库文章 #{art.id}", user_id=current_user.id)
        flash('已生成关联知识库文章', 'success')
        return redirect(url_for('maintenance_extra.kb_article', id=art.id))
    except Exception as e:
        db.session.rollback()
        flash(f'操作失败: {e}', 'danger')
    return redirect(url_for('maintenance_extra.known_errors'))


# ===========================================================================
# J. 事件归一化/关联规则引擎
# ===========================================================================
@itsm_adv_bp.route('/event-rules')
@login_required
@permission_required('event:rules')
def event_rules():
    rules = EventCorrelationRule.query.order_by(EventCorrelationRule.priority_order.asc()).all()
    return render_template('maintenance/event_rules.html', rules=rules)


@itsm_adv_bp.route('/event-rule/new', methods=['GET', 'POST'])
@login_required
@permission_required('event:rules')
def event_rule_new():
    if request.method == 'POST':
        try:
            rule = EventCorrelationRule(
                name=request.form['name'],
                description=request.form.get('description', ''),
                enabled=request.form.get('enabled') == 'on',
                priority_order=request.form.get('priority_order', 100, type=int),
                match_scope=request.form.get('match_scope', 'message'),
                match_operator=request.form.get('match_operator', 'contains'),
                match_value=request.form.get('match_value', ''),
                action=request.form.get('action', 'suppress'),
                group_by=request.form.get('group_by', 'none'),
                suppression_window_min=request.form.get('suppression_window_min', 60, type=int),
                new_severity=request.form.get('new_severity') or None,
                new_priority=request.form.get('new_priority') or None,
                normalize_template=request.form.get('normalize_template') or None,
                auto_ticket=request.form.get('auto_ticket') == 'on',
                created_by=current_user.id,
            )
            db.session.add(rule)
            db.session.commit()
            flash('规则已创建', 'success')
            return redirect(url_for('itsm_adv.event_rules'))
        except Exception as e:
            db.session.rollback()
            flash(f'创建失败: {e}', 'danger')
    return render_template('maintenance/event_rule_form.html', rule=None)


@itsm_adv_bp.route('/event-rule/<int:rule_id>/edit', methods=['GET', 'POST'])
@login_required
@permission_required('event:rules')
def event_rule_edit(rule_id):
    rule = EventCorrelationRule.query.get_or_404(rule_id)
    if request.method == 'POST':
        try:
            rule.name = request.form['name']
            rule.description = request.form.get('description', '')
            rule.enabled = request.form.get('enabled') == 'on'
            rule.priority_order = request.form.get('priority_order', 100, type=int)
            rule.match_scope = request.form.get('match_scope', 'message')
            rule.match_operator = request.form.get('match_operator', 'contains')
            rule.match_value = request.form.get('match_value', '')
            rule.action = request.form.get('action', 'suppress')
            rule.group_by = request.form.get('group_by', 'none')
            rule.suppression_window_min = request.form.get('suppression_window_min', 60, type=int)
            rule.new_severity = request.form.get('new_severity') or None
            rule.new_priority = request.form.get('new_priority') or None
            rule.normalize_template = request.form.get('normalize_template') or None
            rule.auto_ticket = request.form.get('auto_ticket') == 'on'
            db.session.commit()
            flash('规则已更新', 'success')
            return redirect(url_for('itsm_adv.event_rules'))
        except Exception as e:
            db.session.rollback()
            flash(f'更新失败: {e}', 'danger')
    return render_template('maintenance/event_rule_form.html', rule=rule)


@itsm_adv_bp.route('/event-rule/<int:rule_id>/toggle', methods=['POST'])
@login_required
@permission_required('event:rules')
def event_rule_toggle(rule_id):
    rule = EventCorrelationRule.query.get_or_404(rule_id)
    rule.enabled = not rule.enabled
    db.session.commit()
    return jsonify({'success': True, 'enabled': rule.enabled})


@itsm_adv_bp.route('/event-rule/<int:rule_id>/delete', methods=['POST'])
@login_required
@permission_required('event:rules')
def event_rule_delete(rule_id):
    rule = EventCorrelationRule.query.get_or_404(rule_id)
    db.session.delete(rule)
    db.session.commit()
    flash('规则已删除', 'success')
    return redirect(url_for('itsm_adv.event_rules'))


@itsm_adv_bp.route('/event-rules/apply', methods=['POST'])
@login_required
@permission_required('event:rules')
def apply_event_rules():
    from utils.event_correlation import run_correlation_on_existing
    stats = run_correlation_on_existing(db.session)
    db.session.commit()
    flash(f"已处理 {stats['checked']} 条告警：抑制 {stats['suppressed']}，归一化/升级 {stats['normalized']}", 'info')
    return redirect(url_for('itsm_adv.event_rules'))


# ===========================================================================
# K. 真实可用率采集 (对接监控/设备状态，替代代理算法)
# ===========================================================================
@itsm_adv_bp.route('/availability/collect', methods=['POST'])
@login_required
@permission_required('availability:collect')
def availability_collect():
    days = request.form.get('days', 30, type=int)
    try:
        stats = collect_availability(db.session, days=days)
        db.session.commit()
        flash(f"已采集可用率记录 {stats['written']} 条（设备 {len(stats['device_rows'])} / 服务 {len(stats['service_rows'])}）",
              'success')
    except Exception as e:
        db.session.rollback()
        flash(f'采集失败: {e}', 'danger')
    return redirect(url_for('itsm_adv.availability_report'))


@itsm_adv_bp.route('/availability')
@login_required
@permission_required('csi:view')
def availability_report():
    start, end, days = _window()
    device_recs = AvailabilityRecord.query.filter_by(scope='device').filter(
        AvailabilityRecord.period_start >= start, AvailabilityRecord.period_end <= end
    ).order_by(AvailabilityRecord.availability_pct.asc()).all()
    service_recs = AvailabilityRecord.query.filter_by(scope='service').filter(
        AvailabilityRecord.period_start >= start, AvailabilityRecord.period_end <= end
    ).order_by(AvailabilityRecord.availability_pct.asc()).all()
    all_services = ServiceCatalog.query.filter_by(enabled=True).all()
    # 已映射设备但尚未产生采集记录的服务(提示需先采集)
    mapped_service_ids = {r.service_catalog_id for r in service_recs}
    return render_template('maintenance/availability_report.html',
                           device_recs=device_recs, service_recs=service_recs,
                           all_services=all_services, mapped_service_ids=mapped_service_ids,
                           days=days, start=start, end=end)


# ===========================================================================
# M. 服务目录级客户满意度(CSAT) 度量
# ===========================================================================
@itsm_adv_bp.route('/csat')
@login_required
@permission_required('csat:view')
def csat_dashboard():
    services = ServiceCatalog.query.filter_by(enabled=True).all()
    rows = []
    for s in services:
        c = _compute_csat(s.id)
        rows.append({'service': s, 'avg': c['avg'], 'count': c['count'], 'distribution': c['distribution']})
    overall = _compute_csat(None)
    return render_template('maintenance/csat_dashboard.html', rows=rows, overall=overall)


@itsm_adv_bp.route('/csat/submit', methods=['POST'])
@login_required
def csat_submit():
    try:
        survey = CSATSurvey(
            service_catalog_id=request.form.get('service_catalog_id', type=int) or None,
            work_order_id=request.form.get('work_order_id', type=int) or None,
            rating=request.form.get('rating', type=int),
            comment=request.form.get('comment', ''),
            channel=request.form.get('channel', 'manual'),
            respondent=request.form.get('respondent') or (current_user.username if current_user.is_authenticated else None),
        )
        db.session.add(survey)
        db.session.commit()
        flash('满意度评价已提交', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'提交失败: {e}', 'danger')
    return redirect(request.referrer or url_for('itsm_adv.csat_dashboard'))


# ===========================================================================
# L. 变更影响模拟(先算影响再实施)
# ===========================================================================
@itsm_adv_bp.route('/change/<int:change_id>/impact')
@login_required
@permission_required('change:impact')
def change_impact(change_id):
    change = ChangeRequest.query.get_or_404(change_id)
    result = simulate_change_impact(change)
    # 持久化快照(便于审计与对比)
    try:
        persist_impact_analysis(change, result, db.session)
        db.session.commit()
    except Exception:
        db.session.rollback()
    direct_devices = Device.query.filter(Device.id.in_(result['direct_device_ids'])).all() \
        if result['direct_device_ids'] else []
    impacted_devices = Device.query.filter(Device.id.in_(result['impacted_device_ids'])).all() \
        if result['impacted_device_ids'] else []
    impacted_services = ServiceCatalog.query.filter(ServiceCatalog.id.in_(result['impacted_service_ids'])).all() \
        if result['impacted_service_ids'] else []
    last = change.impact_analyses.order_by(ChangeImpactAnalysis.simulated_at.desc()).first()
    return render_template('maintenance/change_impact.html', change=change, result=result,
                           direct_devices=direct_devices, impacted_devices=impacted_devices,
                           impacted_services=impacted_services, last=last)


# ===========================================================================
# M. SLA 策略管理（服务级别管理实践）
# ===========================================================================
@itsm_adv_bp.route('/sla-policies')
@login_required
@permission_required('maintenance:view')
def sla_policies():
    """SLA 策略列表（含被引用情况）"""
    policies = SLAPolicy.query.order_by(
        SLAPolicy.is_active.desc(), SLAPolicy.category, SLAPolicy.priority
    ).all()
    service_counts = dict(
        db.session.query(ServiceCatalog.sla_policy_id, func.count(ServiceCatalog.id))
        .filter(ServiceCatalog.sla_policy_id.isnot(None))
        .group_by(ServiceCatalog.sla_policy_id).all()
    )
    order_counts = dict(
        db.session.query(WorkOrder.sla_policy_id, func.count(WorkOrder.id))
        .filter(WorkOrder.sla_policy_id.isnot(None))
        .group_by(WorkOrder.sla_policy_id).all()
    )
    ref_count = sum(service_counts.values()) + sum(order_counts.values())
    return render_template('maintenance/sla_policies.html', policies=policies,
                           service_counts=service_counts, order_counts=order_counts,
                           ref_count=ref_count)


def _validate_sla_policy_form():
    """校验并规整 SLA 策略表单数据，返回 (data, error)"""
    name = (request.form.get('name') or '').strip()
    if not name:
        return None, '策略名称不能为空'
    if len(name) > 100:
        return None, '策略名称不能超过 100 字符'
    return {
        'name': name,
        'description': (request.form.get('description') or '').strip(),
        'category': request.form.get('category') or 'incident',
        'priority': request.form.get('priority') or 'medium',
        'response_time': request.form.get('response_time', type=int),
        'resolution_time': request.form.get('resolution_time', type=int),
        'business_hours': (request.form.get('business_hours') or '').strip() or None,
        'is_active': request.form.get('is_active') == 'on',
    }, None


@itsm_adv_bp.route('/sla-policies/create', methods=['POST'])
@login_required
@permission_required('itsm:sla:manage')
def sla_policy_create():
    data, err = _validate_sla_policy_form()
    if err:
        flash(err, 'danger')
        return redirect(url_for('itsm_adv.sla_policies'))
    if SLAPolicy.query.filter_by(name=data['name']).first():
        flash(f'SLA 策略「{data["name"]}」已存在', 'warning')
        return redirect(url_for('itsm_adv.sla_policies'))
    policy = SLAPolicy(**data)
    db.session.add(policy)
    db.session.commit()
    log_audit('create', 'sla_policy', policy.id, f'创建SLA策略: {policy.name}', user_id=current_user.id)
    flash(f'SLA 策略「{policy.name}」创建成功', 'success')
    return redirect(url_for('itsm_adv.sla_policies'))


@itsm_adv_bp.route('/sla-policies/<int:policy_id>/edit', methods=['POST'])
@login_required
@permission_required('itsm:sla:manage')
def sla_policy_edit(policy_id):
    policy = SLAPolicy.query.get_or_404(policy_id)
    data, err = _validate_sla_policy_form()
    if err:
        flash(err, 'danger')
        return redirect(url_for('itsm_adv.sla_policies'))
    dup = SLAPolicy.query.filter(SLAPolicy.name == data['name'], SLAPolicy.id != policy_id).first()
    if dup:
        flash(f'SLA 策略「{data["name"]}」已存在', 'warning')
        return redirect(url_for('itsm_adv.sla_policies'))
    for key, value in data.items():
        setattr(policy, key, value)
    db.session.commit()
    log_audit('update', 'sla_policy', policy.id, f'编辑SLA策略: {policy.name}', user_id=current_user.id)
    flash(f'SLA 策略「{policy.name}」已更新', 'success')
    return redirect(url_for('itsm_adv.sla_policies'))


@itsm_adv_bp.route('/sla-policies/<int:policy_id>/toggle', methods=['POST'])
@login_required
@permission_required('itsm:sla:manage')
def sla_policy_toggle(policy_id):
    policy = SLAPolicy.query.get_or_404(policy_id)
    policy.is_active = not policy.is_active
    db.session.commit()
    log_audit('update', 'sla_policy', policy.id,
              f"{'启用' if policy.is_active else '停用'}SLA策略: {policy.name}", user_id=current_user.id)
    flash(f'策略「{policy.name}」已{"启用" if policy.is_active else "停用"}', 'success')
    return redirect(url_for('itsm_adv.sla_policies'))


@itsm_adv_bp.route('/sla-policies/<int:policy_id>/delete', methods=['POST'])
@login_required
@permission_required('itsm:sla:manage')
def sla_policy_delete(policy_id):
    policy = SLAPolicy.query.get_or_404(policy_id)
    sc = ServiceCatalog.query.filter_by(sla_policy_id=policy.id).count()
    wo = WorkOrder.query.filter_by(sla_policy_id=policy.id).count()
    if sc or wo:
        flash(f'策略「{policy.name}」仍被 {sc} 个服务目录 / {wo} 张工单引用，请先解除引用或停用', 'danger')
        return redirect(url_for('itsm_adv.sla_policies'))
    db.session.delete(policy)
    db.session.commit()
    log_audit('delete', 'sla_policy', policy.id, f'删除SLA策略: {policy.name}', user_id=current_user.id)
    flash(f'策略「{policy.name}」已删除', 'success')
    return redirect(url_for('itsm_adv.sla_policies'))
