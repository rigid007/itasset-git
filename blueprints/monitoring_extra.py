"""
monitoring_extra.py - 监控扩展蓝图
设备健康评分 / 维护窗口 / 告警升级 / SLA追踪 / 异常检测 / 自动修复
"""
import json
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from datetime import datetime, timedelta
from sqlalchemy import func, desc, case
from extensions import db
from models.models import Device
from models.monitoring import (MetricData, DeviceHealthScore, MaintenanceWindow, AlertEscalationPolicy,
                                SlaUptime, AnomalyDetectionRule, AutomatedRemediation)
from utils.audit import log_audit
from utils.permission import permission_required

monitoring_extra_bp = Blueprint('monitoring_extra', __name__, url_prefix='/monitoring')


# ==================== 设备健康评分 ====================

@monitoring_extra_bp.route('/health-scores')
@login_required
@permission_required('monitor:view')
def health_scores():
    """健康评分仪表板"""
    page = request.args.get('page', 1, type=int)
    scores = DeviceHealthScore.query.order_by(DeviceHealthScore.score.asc()).paginate(page=page, per_page=20)

    # 统计分布
    devices = Device.query.count()
    healthy = DeviceHealthScore.query.filter(DeviceHealthScore.score >= 80).count()
    warning = DeviceHealthScore.query.filter(DeviceHealthScore.score >= 60, DeviceHealthScore.score < 80).count()
    critical = DeviceHealthScore.query.filter(DeviceHealthScore.score < 60).count()
    unscored = devices - DeviceHealthScore.query.count()
    if unscored < 0:
        unscored = 0

    return render_template('monitoring/health_scores.html',
                           scores=scores, devices=devices,
                           healthy=healthy, warning=warning, critical=critical, unscored=unscored)


@monitoring_extra_bp.route('/health-score/calculate', methods=['POST'])
@login_required
@permission_required('monitor:edit')
def health_score_calculate():
    """计算所有设备健康评分（基于实际监控数据）"""
    from models.models import MonitorData as MD

    def _to_score(value, max_val, inverted=True):
        if value is None:
            return None
        if inverted:
            raw = max(0, min(100, 100 - (value / max_val * 100)))
        else:
            raw = min(100, value / max_val * 100)
        return int(round(raw))

    devices = Device.query.all()
    count = 0
    for device in devices:
        latest = MD.query.filter_by(device_id=device.id)\
            .order_by(MD.collected_at.desc()).first()

        if latest:
            cpu_score = _to_score(latest.cpu_usage, 100) or 100
            memory_score = _to_score(latest.memory_usage, 100) or 100
            disk_score = _to_score(latest.disk_usage, 100) or 100
            network_score = 100 if latest.is_reachable else 30
            if latest.ping_time is not None:
                if latest.ping_time <= 50:
                    ping_score = 100
                elif latest.ping_time <= 100:
                    ping_score = 80
                elif latest.ping_time <= 200:
                    ping_score = 60
                else:
                    ping_score = 30
            else:
                ping_score = 70 if device.status == 'online' else (30 if device.status == 'offline' else 50)
        else:
            cpu_score = 100
            memory_score = 100
            disk_score = 100
            network_score = 100 if device.status == 'online' else (30 if device.status == 'offline' else 70)
            ping_score = 100 if device.status == 'online' else (30 if device.status == 'offline' else 70)

        score = int((cpu_score + memory_score + disk_score + network_score + ping_score) / 5)

        hs = DeviceHealthScore.query.filter_by(device_id=device.id).first()
        if hs:
            hs.score = score
            hs.cpu_score = cpu_score
            hs.memory_score = memory_score
            hs.disk_score = disk_score
            hs.network_score = network_score
            hs.ping_score = ping_score
            hs.calculated_at = datetime.utcnow()
        else:
            hs = DeviceHealthScore(device_id=device.id, score=score, cpu_score=cpu_score,
                                   memory_score=memory_score, disk_score=disk_score,
                                   network_score=network_score, ping_score=ping_score)
            db.session.add(hs)
        count += 1

    db.session.commit()
    log_audit('execute', 'device_health_score', 0,
              f'计算 {count} 台设备健康评分',
              details={'device_count': count})
    flash(f'已计算 {count} 台设备健康评分', 'success')
    return redirect(url_for('monitoring_extra.health_scores'))


# ==================== 维护窗口 ====================

@monitoring_extra_bp.route('/maintenance-windows')
@login_required
@permission_required('monitor:view')
def maintenance_windows():
    """维护窗口列表"""
    page = request.args.get('page', 1, type=int)
    windows = MaintenanceWindow.query.order_by(MaintenanceWindow.start_time.desc()).paginate(page=page, per_page=20)
    devices = Device.query.order_by(Device.name).all()

    # 即将到来
    upcoming = MaintenanceWindow.query.filter(
        MaintenanceWindow.start_time >= datetime.utcnow(),
        MaintenanceWindow.status == 'scheduled'
    ).order_by(MaintenanceWindow.start_time.asc()).limit(5).all()

    return render_template('monitoring/maintenance_windows.html', windows=windows,
                           devices=devices, upcoming=upcoming)


@monitoring_extra_bp.route('/maintenance-window/add', methods=['POST'])
@login_required
@permission_required('monitor:edit')
def maintenance_window_add():
    """添加维护窗口"""
    try:
        device_ids = request.form.getlist('device_ids')
        mw = MaintenanceWindow(
            name=request.form['name'],
            description=request.form.get('description', ''),
            start_time=datetime.strptime(request.form['start_time'].replace('T', ' '), '%Y-%m-%d %H:%M'),
            end_time=datetime.strptime(request.form['end_time'].replace('T', ' '), '%Y-%m-%d %H:%M'),
            affected_device_ids=json.dumps([int(d) for d in device_ids]) if device_ids else '[]',
            reason=request.form.get('reason', ''),
            status='scheduled',
            created_by=current_user.id,
        )
        db.session.add(mw)
        db.session.commit()
        log_audit('create', 'maintenance_window', mw.id,
                  f'创建维护窗口: {mw.name}',
                  details={'name': mw.name, 'start_time': mw.start_time.isoformat()})
        flash('维护窗口已创建', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'创建失败: {str(e)}', 'danger')
    return redirect(url_for('monitoring_extra.maintenance_windows'))


@monitoring_extra_bp.route('/maintenance-window/<int:id>/cancel', methods=['POST'])
@login_required
@permission_required('monitor:edit')
def maintenance_window_cancel(id):
    """取消维护窗口"""
    mw = MaintenanceWindow.query.get_or_404(id)
    mw.status = 'cancelled'
    db.session.commit()
    log_audit('update', 'maintenance_window', mw.id,
              f'取消维护窗口: {mw.name}',
              details={'name': mw.name, 'status': 'cancelled'})
    flash('维护窗口已取消', 'success')
    return redirect(url_for('monitoring_extra.maintenance_windows'))


# ==================== SLA在线率 ====================

@monitoring_extra_bp.route('/sla-report')
@login_required
@permission_required('monitor:view')
def sla_report():
    """SLA在线率报表（基于实际MonitorData）"""
    from models.models import MonitorData as MD

    period = request.args.get('period', 'monthly')
    period_days = {'monthly': 30, 'quarterly': 90, 'yearly': 365}.get(period, 30)
    since = datetime.utcnow() - timedelta(days=period_days)

    devices = Device.query.all()
    sla_data = []
    for device in devices:
        # 优先用预计算的 SlaUptime 记录
        sla = SlaUptime.query.filter_by(device_id=device.id, period=period).order_by(
            SlaUptime.calculated_at.desc()).first()
        if sla:
            sla_data.append({
                'device': device,
                'uptime': sla.uptime_percentage,
                'total': sla.total_minutes,
                'downtime': sla.downtime_minutes,
            })
            continue

        # 从 MonitorData 实时计算
        stats = db.session.query(
            func.count(MD.id).label('total'),
            func.sum(case((MD.is_reachable == True, 1), else_=0)).label('reachable'),
        ).filter(
            MD.device_id == device.id,
            MD.collected_at >= since,
        ).first()

        total = stats.total or 0
        reachable = stats.reachable or 0
        if total > 0:
            uptime_pct = round(reachable / total * 100, 2)
            # 估算分钟数：用实际记录时间跨度
            time_range = db.session.query(
                func.max(MD.collected_at) - func.min(MD.collected_at)
            ).filter(
                MD.device_id == device.id,
                MD.collected_at >= since,
            ).scalar()
            if time_range:
                total_minutes = int(time_range.total_seconds() / 60)
            else:
                total_minutes = total * 5  # 默认~5分钟间隔估算
            downtime_min = int(total_minutes * (1 - uptime_pct / 100))
        else:
            uptime_pct = 100.0 if device.status == 'online' else 0.0
            total_minutes = 0
            downtime_min = 0

        sla_data.append({
            'device': device,
            'uptime': uptime_pct,
            'total': total_minutes,
            'downtime': downtime_min,
        })

    # 总体统计
    avg_uptime = sum(d['uptime'] for d in sla_data) / len(sla_data) if sla_data else 100
    below_sla = sum(1 for d in sla_data if d['uptime'] < 99.9)
    total_downtime = sum(d['downtime'] for d in sla_data)

    return render_template('monitoring/sla_report.html',
                           sla_data=sla_data, period=period,
                           avg_uptime=round(avg_uptime, 2), below_sla=below_sla,
                           total_downtime=total_downtime, total_devices=len(devices))


# ==================== SLA在线率 API ====================

@monitoring_extra_bp.route('/api/sla', methods=['GET'])
@login_required
@permission_required('monitor:view')
def api_get_sla():
    """获取SLA数据API"""
    device_id = request.args.get('device_id', type=int)
    period = request.args.get('period', 'monthly')
    query = SlaUptime.query
    if device_id:
        query = query.filter_by(device_id=device_id)
    query = query.filter_by(period=period).order_by(SlaUptime.calculated_at.desc()).limit(100)
    return jsonify({
        'success': True,
        'data': [s.to_dict() for s in query.all()]
    })


@monitoring_extra_bp.route('/api/sla', methods=['POST'])
@login_required
@permission_required('monitor:edit')
def api_set_sla():
    """写入/更新SLA数据API"""
    try:
        data = request.get_json(force=True)
        device_id = data.get('device_id')
        period = data.get('period', 'monthly')
        uptime = float(data.get('uptime_percentage', 100))
        total_min = int(data.get('total_minutes', 0))
        downtime_min = int(data.get('downtime_minutes', 0))
        period_start = datetime.fromisoformat(data['period_start']) if data.get('period_start') else None
        period_end = datetime.fromisoformat(data['period_end']) if data.get('period_end') else None

        if not device_id:
            return jsonify({'success': False, 'error': 'device_id required'}), 400

        existing = SlaUptime.query.filter_by(
            device_id=device_id, period=period, period_start=period_start
        ).first()
        if existing:
            existing.uptime_percentage = uptime
            existing.total_minutes = total_min
            existing.downtime_minutes = downtime_min
            existing.period_end = period_end
            existing.calculated_at = datetime.utcnow()
        else:
            sla = SlaUptime(
                device_id=device_id, period=period,
                uptime_percentage=uptime, total_minutes=total_min,
                downtime_minutes=downtime_min, period_start=period_start,
                period_end=period_end,
            )
            db.session.add(sla)
        db.session.commit()
        log_audit('update' if existing else 'create', 'sla_uptime', device_id,
                  f"{'更新' if existing else '创建'}SLA数据: 设备#{device_id} {period}",
                  details={'device_id': device_id, 'period': period, 'uptime': uptime})
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@monitoring_extra_bp.route('/api/sla/calculate', methods=['POST'])
@login_required
@permission_required('monitor:edit')
def api_trigger_sla_calc():
    """手动触发SLA计算"""
    try:
        from tasks.sla_calculator import calculate_sla
        from flask import current_app
        calculate_sla(current_app._get_current_object())
        log_audit('execute', 'sla_calculation', 0, '手动触发SLA计算')
        return jsonify({'success': True, 'message': 'SLA计算完成'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@monitoring_extra_bp.route('/escalation-policies')
@login_required
@permission_required('monitor:view')
def escalation_policies():
    """告警升级策略列表"""
    policies = AlertEscalationPolicy.query.order_by(AlertEscalationPolicy.escalation_level).all()
    from models.models import AlertRule
    alert_rules = AlertRule.query.all()
    return render_template('monitoring/escalation_policies.html', policies=policies, alert_rules=alert_rules)


@monitoring_extra_bp.route('/escalation-policy/add', methods=['POST'])
@login_required
@permission_required('monitor:edit')
def escalation_policy_add():
    """添加升级策略"""
    try:
        ep = AlertEscalationPolicy(
            name=request.form['name'],
            alert_rule_id=request.form.get('alert_rule_id', type=int),
            escalation_level=request.form.get('escalation_level', 1, type=int),
            wait_minutes=request.form.get('wait_minutes', 15, type=int),
            notify_channel=request.form.get('notify_channel', 'email'),
            notify_target=request.form.get('notify_target', ''),
            enabled=True,
        )
        db.session.add(ep)
        db.session.commit()
        log_audit('create', 'escalation_policy', ep.id,
                  f'创建升级策略: {ep.name}',
                  details={'name': ep.name, 'level': ep.escalation_level})
        flash('升级策略已添加', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'添加失败: {str(e)}', 'danger')
    return redirect(url_for('monitoring_extra.escalation_policies'))


# ==================== 异常检测 ====================

@monitoring_extra_bp.route('/anomaly-detection')
@login_required
@permission_required('monitor:view')
def anomaly_detection():
    """异常检测规则"""
    rules = AnomalyDetectionRule.query.all()
    devices = Device.query.all()
    return render_template('monitoring/anomaly_detection.html', rules=rules, devices=devices)


@monitoring_extra_bp.route('/anomaly-detection/add', methods=['POST'])
@login_required
@permission_required('monitor:edit')
def anomaly_detection_add():
    """添加异常检测规则"""
    try:
        rule = AnomalyDetectionRule(
            device_id=request.form.get('device_id', type=int),
            metric_name=request.form['metric_name'],
            method=request.form.get('method', 'statistical_deviation'),
            sensitivity=request.form.get('sensitivity', 'medium'),
            deviation_threshold=request.form.get('deviation_threshold', 2.0, type=float),
            enabled=True,
        )
        db.session.add(rule)
        db.session.commit()
        log_audit('create', 'anomaly_detection_rule', rule.id,
                  f'添加异常检测规则: {rule.metric_name}/{rule.method}',
                  details={'metric': rule.metric_name, 'method': rule.method, 'device_id': rule.device_id})
        flash('异常检测规则已添加', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'添加失败: {str(e)}', 'danger')
    return redirect(url_for('monitoring_extra.anomaly_detection'))


# ==================== 趋势预测API ====================

@monitoring_extra_bp.route('/predictive')
@login_required
@permission_required('monitor:view')
def predictive_analysis():
    """预测分析页面"""
    device_id = request.args.get('device_id', type=int)
    metric = request.args.get('metric', 'cpu_usage')
    days = request.args.get('days', 30, type=int)

    devices = Device.query.all()
    return render_template('monitoring/predictive.html', devices=devices,
                           selected_device_id=device_id, metric=metric, days=days)


@monitoring_extra_bp.route('/api/predictive-data')
@login_required
@permission_required('monitor:view')
def api_predictive_data():
    """预测数据API（基于实际监控数据）"""
    from models.models import MonitorData as MD

    device_id = request.args.get('device_id', type=int)
    metric = request.args.get('metric', 'cpu_usage')
    days = request.args.get('days', 30, type=int)

    now = datetime.utcnow()
    start_time = now - timedelta(days=days)

    # 支持 MonitorData 字段映射
    valid_metrics = {
        'cpu_usage': MD.cpu_usage,
        'memory_usage': MD.memory_usage,
        'disk_usage': MD.disk_usage,
        'temperature': MD.temperature,
        'network_in': MD.network_in,
        'network_out': MD.network_out,
    }

    col = valid_metrics.get(metric)
    history = []
    forecast = []

    if device_id and col:
        # 按天聚合实际数据
        records = db.session.query(
            func.date(MD.collected_at).label('day'),
            func.avg(col).label('avg_val'),
            func.max(col).label('max_val'),
            func.min(col).label('min_val'),
        ).filter(
            MD.device_id == device_id,
            MD.collected_at >= start_time,
            col != None,
        ).group_by(
            func.date(MD.collected_at)
        ).order_by(
            func.date(MD.collected_at)
        ).all()

        if records:
            for r in records:
                day_str = r.day.isoformat() if hasattr(r.day, 'isoformat') else str(r.day)
                history.append({
                    'timestamp': day_str,
                    'value': round(float(r.avg_val), 1) if r.avg_val else 0,
                })

            # 简单预测：取最近7天平均值为基准
            recent = [h['value'] for h in history[-7:]]
            base = sum(recent) / len(recent) if recent else 50
            # 计算简单趋势
            if len(recent) >= 2:
                trend = (recent[-1] - recent[0]) / len(recent)
            else:
                trend = 0

            for i in range(1, 8):
                ts = now + timedelta(hours=i * 24)
                val = base + trend * i
                forecast.append({
                    'timestamp': ts.isoformat(),
                    'value': round(max(0, val), 1),
                })

    if not history:
        # 无数据时返回空数组
        history = []
        forecast = []

    return jsonify({'history': history[-30:], 'forecast': forecast, 'metric': metric})


# ==================== 管理员仪表板 ====================

@monitoring_extra_bp.route('/dashboard')
@login_required
@permission_required('monitor:view')
def monitoring_dashboard():
    """监控管理仪表板"""
    total_devices = Device.query.count()
    scored = DeviceHealthScore.query.count()
    active_windows = MaintenanceWindow.query.filter(
        MaintenanceWindow.status == 'scheduled',
        MaintenanceWindow.start_time >= datetime.utcnow()
    ).count()
    avg_score = db.session.query(func.avg(DeviceHealthScore.score)).scalar() or 0

    return render_template('monitoring/monitor_management.html',
                           total_devices=total_devices, scored=scored,
                           active_windows=active_windows, avg_score=round(avg_score, 1))
