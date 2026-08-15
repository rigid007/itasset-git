"""
report_extra.py - 综合报表扩展
管理驾驶舱 / 合规框架 / 报表分发 / 趋势预测
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from datetime import datetime, timedelta
from extensions import db
from utils.audit import log_audit
from utils.permission import permission_required
from models.report_models import ReportDashboard, ReportDistribution, ComplianceFramework, ComplianceEvidence
from models.models import Device
from models.device_performance_models import DevicePerformance
from models.models import Alert
import json

report_extra_bp = Blueprint('report_extra', __name__, url_prefix='/report')


# ==================== 管理驾驶舱 ====================

@report_extra_bp.route('/executive-dashboard')
@login_required
@permission_required('report:view')
def executive_dashboard():
    """管理驾驶舱 - 全局概览"""
    # 设备概况
    total_devices = Device.query.count()
    online_devices = Device.query.filter_by(status='online').count()
    offline_devices = Device.query.filter_by(status='offline').count()

    # 告警统计
    recent_alerts = Alert.query.order_by(Alert.created_at.desc()).limit(10).all()
    critical_alerts = Alert.query.filter_by(severity='critical').count()

    # 性能趋势（最近7天）
    end = datetime.utcnow()
    start = end - timedelta(days=7)

    # 仪表板列表
    dashboards = ReportDashboard.query.order_by(ReportDashboard.is_default.desc(), ReportDashboard.created_at.desc()).all()

    return render_template('report/executive_dashboard.html',
                         total_devices=total_devices,
                         online_devices=online_devices,
                         offline_devices=offline_devices,
                         critical_alerts=critical_alerts,
                         recent_alerts=recent_alerts,
                         dashboards=dashboards)


# ==================== 仪表板管理 ====================

@report_extra_bp.route('/dashboards')
@login_required
@permission_required('report:view')
def dashboard_list():
    """仪表板列表"""
    dashboards = ReportDashboard.query.order_by(ReportDashboard.created_at.desc()).all()
    return render_template('report/dashboard_list.html', dashboards=dashboards)


@report_extra_bp.route('/dashboard/create', methods=['GET', 'POST'])
@login_required
@permission_required('report:edit')
def dashboard_create():
    """创建仪表板"""
    if request.method == 'POST':
        try:
            db_dashboard = ReportDashboard(
                name=request.form['name'],
                description=request.form.get('description', ''),
                dashboard_type=request.form.get('dashboard_type', 'operational'),
                layout_config=request.form.get('layout_config', '{}'),
                widgets=request.form.get('widgets', '[]'),
                role_access=request.form.get('role_access', 'all'),
                is_default=request.form.get('is_default') == 'on',
                is_shared=request.form.get('is_shared') == 'on',
                created_by=current_user.id,
            )
            db.session.add(db_dashboard)
            db.session.commit()

            log_audit('create', 'report_dashboard', db_dashboard.id,
                      f'创建仪表板 {db_dashboard.name}',
                      details={'dashboard_type': db_dashboard.dashboard_type},
                      user_id=current_user.id)

            flash('仪表板已创建', 'success')
            return redirect(url_for('report_extra.dashboard_list'))
        except Exception as e:
            db.session.rollback()
            flash(f'创建失败: {str(e)}', 'danger')
    return render_template('report/dashboard_form.html', dashboard=None)


@report_extra_bp.route('/dashboard/<int:id>')
@login_required
@permission_required('report:view')
def dashboard_view(id):
    """查看仪表板"""
    dashboard = ReportDashboard.query.get_or_404(id)
    return render_template('report/dashboard_view.html', dashboard=dashboard)


@report_extra_bp.route('/dashboard/<int:id>/delete', methods=['POST'])
@login_required
@permission_required('report:edit')
def dashboard_delete(id):
    """删除仪表板"""
    dashboard = ReportDashboard.query.get_or_404(id)
    db.session.delete(dashboard)
    db.session.commit()

    log_audit('delete', 'report_dashboard', id,
              f'删除仪表板 #{id}',
              user_id=current_user.id)

    flash('仪表板已删除', 'success')
    return redirect(url_for('report_extra.dashboard_list'))


# ==================== 合规管理 ====================

@report_extra_bp.route('/compliance/frameworks')
@login_required
@permission_required('report:view')
def compliance_frameworks():
    """合规框架列表"""
    frameworks = ComplianceFramework.query.order_by(ComplianceFramework.name).all()
    return render_template('report/compliance_frameworks.html', frameworks=frameworks)


@report_extra_bp.route('/compliance/framework/add', methods=['POST'])
@login_required
@permission_required('report:edit')
def compliance_framework_add():
    """添加合规框架"""
    try:
        cf = ComplianceFramework(
            name=request.form['name'],
            version=request.form.get('version', ''),
            description=request.form.get('description', ''),
            control_items=request.form.get('control_items', '[]'),
            enabled=request.form.get('enabled') == 'on',
        )
        db.session.add(cf)
        db.session.commit()

        log_audit('create', 'compliance_framework', cf.id,
                  f'添加合规框架 {cf.name}',
                  user_id=current_user.id)

        flash('合规框架已添加', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'添加失败: {str(e)}', 'danger')
    return redirect(url_for('report_extra.compliance_frameworks'))


@report_extra_bp.route('/compliance/framework/<int:id>/delete', methods=['POST'])
@login_required
@permission_required('report:edit')
def compliance_framework_delete(id):
    """删除合规框架（级联删除关联证据）"""
    framework = ComplianceFramework.query.get_or_404(id)
    name = framework.name
    try:
        ComplianceEvidence.query.filter_by(framework_id=id).delete()
        db.session.delete(framework)
        db.session.commit()
        log_audit('delete', 'compliance_framework', id, f'删除合规框架: {name}',
                  user_id=current_user.id)
        flash(f'合规框架 "{name}" 已删除（含关联证据）', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'删除失败: {str(e)}', 'danger')
    return redirect(url_for('report_extra.compliance_frameworks'))


@report_extra_bp.route('/compliance/evidence')
@login_required
@permission_required('report:view')
def compliance_evidence():
    """合规证据列表"""
    evidences = ComplianceEvidence.query.order_by(ComplianceEvidence.collected_at.desc()).all()
    frameworks = ComplianceFramework.query.filter_by(enabled=True).all()
    return render_template('report/compliance_evidence.html', evidences=evidences, frameworks=frameworks)


@report_extra_bp.route('/compliance/evidence/add', methods=['POST'])
@login_required
@permission_required('report:edit')
def compliance_evidence_add():
    """添加合规证据"""
    try:
        ce = ComplianceEvidence(
            framework_id=request.form['framework_id'],
            control_id=request.form['control_id'],
            evidence_type=request.form.get('evidence_type', 'manual'),
            content=request.form.get('content', ''),
            collected_by=current_user.id,
            status=request.form.get('status', 'pending'),
        )
        db.session.add(ce)
        db.session.commit()

        log_audit('create', 'compliance_evidence', ce.id,
                  f'添加合规证据 #{ce.id}',
                  details={'framework_id': ce.framework_id, 'control_id': ce.control_id},
                  user_id=current_user.id)

        flash('合规证据已添加', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'添加失败: {str(e)}', 'danger')
    return redirect(url_for('report_extra.compliance_evidence'))


@report_extra_bp.route('/compliance/evidence/<int:id>/delete', methods=['POST'])
@login_required
@permission_required('report:edit')
def compliance_evidence_delete(id):
    """删除合规证据"""
    evidence = ComplianceEvidence.query.get_or_404(id)
    try:
        db.session.delete(evidence)
        db.session.commit()
        log_audit('delete', 'compliance_evidence', id, f'删除合规证据 #{id}',
                  user_id=current_user.id)
        flash('合规证据已删除', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'删除失败: {str(e)}', 'danger')
    return redirect(url_for('report_extra.compliance_evidence'))


@report_extra_bp.route('/compliance/report')
@login_required
@permission_required('report:view')
def compliance_report():
    """合规报告"""
    frameworks = ComplianceFramework.query.filter_by(enabled=True).all()
    summary = []
    for fw in frameworks:
        total = ComplianceEvidence.query.filter_by(framework_id=fw.id).count()
        passed = ComplianceEvidence.query.filter_by(framework_id=fw.id, status='pass').count()
        failed = ComplianceEvidence.query.filter_by(framework_id=fw.id, status='fail').count()
        summary.append({
            'framework': fw,
            'total': total,
            'passed': passed,
            'failed': failed,
            'compliance_pct': round(passed / total * 100, 1) if total > 0 else 0,
        })
    return render_template('report/compliance_report.html', summary=summary)


# ==================== 报表分发 ====================

@report_extra_bp.route('/distribution')
@login_required
@permission_required('report:view')
def distribution_list():
    """分发任务列表"""
    distributions = ReportDistribution.query.order_by(ReportDistribution.created_at.desc()).all()
    return render_template('report/distribution_list.html', distributions=distributions)


@report_extra_bp.route('/distribution/add', methods=['POST'])
@login_required
@permission_required('report:edit')
def distribution_add():
    """添加分发任务"""
    try:
        rd = ReportDistribution(
            name=request.form['name'],
            report_type=request.form['report_type'],
            schedule_cron=request.form.get('schedule_cron', ''),
            format=request.form.get('format', 'pdf'),
            delivery_channel=request.form.get('delivery_channel', 'email'),
            recipients=request.form.get('recipients', '[]'),
            enabled=request.form.get('enabled') == 'on',
            retry_on_fail=request.form.get('retry_on_fail') == 'on',
            created_by=current_user.id,
        )
        db.session.add(rd)
        db.session.commit()

        log_audit('create', 'report_distribution', rd.id,
                  f'创建分发任务 {rd.name}',
                  details={'report_type': rd.report_type, 'delivery_channel': rd.delivery_channel},
                  user_id=current_user.id)

        flash('分发任务已创建', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'创建失败: {str(e)}', 'danger')
    return redirect(url_for('report_extra.distribution_list'))


@report_extra_bp.route('/distribution/<int:id>/toggle', methods=['POST'])
@login_required
@permission_required('report:edit')
def distribution_toggle(id):
    """启用/禁用分发任务"""
    dist = ReportDistribution.query.get_or_404(id)
    dist.enabled = not dist.enabled
    db.session.commit()

    status_text = '启用' if dist.enabled else '禁用'
    log_audit('update', 'report_distribution', id,
              f'{status_text}分发任务 {dist.name}',
              details={'enabled': dist.enabled},
              user_id=current_user.id)

    flash(f'分发任务已{status_text}', 'success')
    return redirect(url_for('report_extra.distribution_list'))


@report_extra_bp.route('/distribution/<int:id>/edit', methods=['POST'])
@login_required
@permission_required('report:edit')
def distribution_edit(id):
    """编辑分发任务"""
    dist = ReportDistribution.query.get_or_404(id)
    try:
        dist.name = request.form['name']
        dist.report_type = request.form.get('report_type', dist.report_type)
        dist.format = request.form.get('format', dist.format)
        dist.delivery_channel = request.form.get('delivery_channel', dist.delivery_channel)
        dist.schedule_cron = request.form.get('schedule_cron', '')
        dist.recipients = request.form.get('recipients', '[]')
        dist.enabled = request.form.get('enabled') == 'on'
        dist.retry_on_fail = request.form.get('retry_on_fail') == 'on'
        db.session.commit()
        log_audit('update', 'report_distribution', id, f'编辑分发任务: {dist.name}',
                  user_id=current_user.id)
        flash('分发任务已更新', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'更新失败: {str(e)}', 'danger')
    return redirect(url_for('report_extra.distribution_list'))


@report_extra_bp.route('/distribution/<int:id>/delete', methods=['POST'])
@login_required
@permission_required('report:edit')
def distribution_delete(id):
    """删除分发任务"""
    dist = ReportDistribution.query.get_or_404(id)
    name = dist.name
    try:
        db.session.delete(dist)
        db.session.commit()
        log_audit('delete', 'report_distribution', id, f'删除分发任务: {name}',
                  user_id=current_user.id)
        flash(f'分发任务 "{name}" 已删除', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'删除失败: {str(e)}', 'danger')
    return redirect(url_for('report_extra.distribution_list'))

@report_extra_bp.route('/api/trend/forecast')
@login_required
@permission_required('report:view')
def trend_forecast_api():
    """趋势预测数据"""
    days = request.args.get('days', 30, type=int)
    metric = request.args.get('metric', 'cpu')
    end = datetime.utcnow()
    start = end - timedelta(days=days)

    query = db.session.query(
        db.func.date(DevicePerformance.timestamp).label('date'),
        db.func.avg(DevicePerformance.cpu_usage).label('avg_cpu'),
        db.func.avg(DevicePerformance.memory_usage).label('avg_memory'),
        db.func.avg(DevicePerformance.disk_usage).label('avg_disk'),
    ).filter(
        DevicePerformance.timestamp.between(start, end)
    ).group_by(db.func.date(DevicePerformance.timestamp)).order_by('date').all()

    data = [{
        'date': row.date.isoformat() if row.date else None,
        'avg_cpu': float(row.avg_cpu or 0),
        'avg_memory': float(row.avg_memory or 0),
        'avg_disk': float(row.avg_disk or 0),
    } for row in query]

    return jsonify({'success': True, 'data': data, 'metric': metric, 'days': days})


@report_extra_bp.route('/trend-forecast')
@login_required
@permission_required('report:view')
def trend_forecast():
    """趋势预测页面"""
    return render_template('report/trend_forecast.html')
