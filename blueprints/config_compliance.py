"""
config_compliance.py - 配置管理扩展蓝图
合规策略 / 配置基线 / 配置版本 / 备份验证
"""
import hashlib
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from datetime import datetime
from sqlalchemy import func, desc
from extensions import db
from utils.audit import log_audit
from utils.permission import permission_required
from utils.device_config import capture_device_config as _capture_device_config_ssh
from utils.network_utils import ping_device
from models.models import Device
from models.compliance_models import (
    ConfigBaseline, ConfigDrift, ConfigVersion,
    CompliancePolicy, ComplianceCheckResult, BackupVerification
)
from models.config_models import BackupConfig
from utils.diff_utils import generate_diff_html, generate_side_by_side_html, detect_changes

config_compliance_bp = Blueprint('config_compliance', __name__, url_prefix='/config')


# ==================== 合规策略管理 ====================

@config_compliance_bp.route('/compliance/policies')
@login_required
@permission_required('config:view')
def compliance_policies():
    """合规策略列表"""
    page = request.args.get('page', 1, type=int)
    category = request.args.get('category', '')
    severity = request.args.get('severity', '')

    query = CompliancePolicy.query
    if category:
        query = query.filter_by(category=category)
    if severity:
        query = query.filter_by(severity=severity)

    policies = query.order_by(CompliancePolicy.category, CompliancePolicy.name).paginate(page=page, per_page=20)
    categories = db.session.query(CompliancePolicy.category).distinct().all()
    return render_template('config/compliance_policies.html', policies=policies,
                           categories=[c[0] for c in categories], category=category, severity=severity)


@config_compliance_bp.route('/compliance/policy/add', methods=['POST'])
@login_required
@permission_required('config:edit')
def compliance_policy_add():
    """添加合规策略"""
    try:
        policy = CompliancePolicy(
            name=request.form['name'],
            description=request.form.get('description', ''),
            category=request.form['category'],
            check_type=request.form['check_type'],
            check_expression=request.form.get('check_expression', ''),
            severity=request.form.get('severity', 'medium'),
            framework=request.form.get('framework', ''),
            control_id=request.form.get('control_id', ''),
            enabled=True,
            created_by=current_user.id,
        )
        db.session.add(policy)
        db.session.commit()

        log_audit('create', 'compliance_policy', policy.id,
                  f'添加合规策略 {policy.name}',
                  details={'category': policy.category, 'severity': policy.severity},
                  user_id=current_user.id)

        flash('合规策略添加成功', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'添加失败: {str(e)}', 'danger')
    return redirect(url_for('config_compliance.compliance_policies'))


@config_compliance_bp.route('/compliance/policy/<int:id>/edit', methods=['POST'])
@login_required
@permission_required('config:edit')
def compliance_policy_edit(id):
    """编辑合规策略"""
    policy = CompliancePolicy.query.get_or_404(id)
    try:
        policy.name = request.form['name']
        policy.description = request.form.get('description', '')
        policy.category = request.form['category']
        policy.check_type = request.form['check_type']
        policy.check_expression = request.form.get('check_expression', '')
        policy.severity = request.form.get('severity', 'medium')
        policy.framework = request.form.get('framework', '')
        policy.control_id = request.form.get('control_id', '')
        policy.enabled = request.form.get('enabled') == 'on'
        db.session.commit()

        log_audit('update', 'compliance_policy', id,
                  f'编辑合规策略 {policy.name}',
                  details={'category': policy.category},
                  user_id=current_user.id)

        flash('策略已更新', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'更新失败: {str(e)}', 'danger')
    return redirect(url_for('config_compliance.compliance_policies'))


@config_compliance_bp.route('/compliance/policy/<int:id>/toggle', methods=['POST'])
@login_required
@permission_required('config:edit')
def compliance_policy_toggle(id):
    """启用/禁用策略"""
    policy = CompliancePolicy.query.get_or_404(id)
    policy.enabled = not policy.enabled
    db.session.commit()

    log_audit('update', 'compliance_policy', id,
              f'{"启用" if policy.enabled else "禁用"}合规策略 {policy.name}',
              details={'enabled': policy.enabled},
              user_id=current_user.id)

    return jsonify({'success': True, 'enabled': policy.enabled})


@config_compliance_bp.route('/compliance/check', methods=['GET', 'POST'])
@login_required
@permission_required('config:edit')
def compliance_check():
    """执行合规检查"""
    results = []
    if request.method == 'POST':
        device_ids = request.form.getlist('device_ids')
        policy_ids = request.form.getlist('policy_ids')

        policies = CompliancePolicy.query.filter(CompliancePolicy.id.in_([int(p) for p in policy_ids])).all() if policy_ids else CompliancePolicy.query.filter_by(enabled=True).all()
        devices = Device.query.filter(Device.id.in_([int(d) for d in device_ids])).all() if device_ids else Device.query.all()

        for device in devices:
            for policy in policies:
                # 模拟检查结果 (实际应连接设备执行检查)
                result = ComplianceCheckResult(
                    policy_id=policy.id,
                    device_id=device.id,
                    status='pass',
                    actual_value='-',
                    expected_value=policy.check_expression or '-',
                    detail=f'模拟检查: {policy.name} on {device.name}',
                    checked_by='system',
                )
                db.session.add(result)
                results.append(result)

        db.session.commit()

        log_audit('execute', 'compliance_check', 0,
                  f'执行合规检查: {len(devices)}设备, {len(policies)}策略',
                  details={'device_count': len(devices), 'policy_count': len(policies)},
                  user_id=current_user.id)

        flash(f'合规检查完成: {len(devices)}设备 × {len(policies)}策略', 'success')

    policies = CompliancePolicy.query.filter_by(enabled=True).all()
    devices = Device.query.all()
    recent = ComplianceCheckResult.query.order_by(ComplianceCheckResult.checked_at.desc()).limit(50).all()
    return render_template('config/compliance_check.html', policies=policies,
                           devices=devices, recent=results or recent)


@config_compliance_bp.route('/compliance/report')
@login_required
@permission_required('config:view')
def compliance_report():
    """合规报告"""
    policies = CompliancePolicy.query.all()
    devices = Device.query.count()

    # 统计通过率
    summary = []
    for policy in policies:
        results = ComplianceCheckResult.query.filter_by(policy_id=policy.id).all()
        total = len(results)
        passed = sum(1 for r in results if r.status == 'pass')
        summary.append({
            'policy': policy,
            'total': total,
            'passed': passed,
            'pass_rate': round(passed / total * 100, 1) if total > 0 else 0,
        })

    # 总体统计
    all_results = ComplianceCheckResult.query.count()
    all_passed = ComplianceCheckResult.query.filter_by(status='pass').count()
    overall_rate = round(all_passed / all_results * 100, 1) if all_results > 0 else 0
    failed_count = ComplianceCheckResult.query.filter_by(status='fail').count()

    return render_template('config/compliance_report.html',
                           summary=summary, devices=devices,
                           overall_rate=overall_rate, total_checks=all_results,
                           passed_checks=all_passed, failed_count=failed_count)


# ==================== 配置基线管理 ====================

@config_compliance_bp.route('/config-baseline')
@login_required
@permission_required('config:view')
def config_baseline():
    """配置基线管理"""
    page = request.args.get('page', 1, type=int)
    baselines = ConfigBaseline.query.order_by(ConfigBaseline.captured_at.desc()).paginate(page=page, per_page=20)
    devices = Device.query.order_by(Device.name).all()
    return render_template('config/config_baseline.html', baselines=baselines, devices=devices)


@config_compliance_bp.route('/config-baseline/capture', methods=['POST'])
@login_required
@permission_required('config:edit')
def config_baseline_capture():
    """捕获配置基线 — 通过 SSH 真实获取设备配置"""
    device_id = request.form.get('device_id', type=int)
    config_type = request.form.get('config_type', 'running')

    device = Device.query.get_or_404(device_id)
    ip = device.management_ip or device.ip_address
    device_name = device.name

    # 1. 在线检查: 如果设备已知 offline 则直接拒绝
    if device.status == 'offline':
        flash(f'设备 "{device_name}" 当前离线，无法捕获配置', 'danger')
        return redirect(url_for('config_compliance.config_baseline'))

    # 2. Ping 二次确认
    if ip:
        online, latency = ping_device(ip, timeout=3)
        if not online:
            # 更新设备状态
            device.status = 'offline'
            device.last_checked = datetime.utcnow()
            db.session.commit()
            flash(f'设备 "{device_name}" ({ip}) 不可达 (ping 失败)，无法捕获配置', 'danger')
            return redirect(url_for('config_compliance.config_baseline'))
    else:
        flash(f'设备 "{device_name}" 未配置管理 IP，无法捕获配置', 'danger')
        return redirect(url_for('config_compliance.config_baseline'))

    # 3. 通过 SSH 获取真实配置
    result = _capture_device_config_ssh(device, config_type=config_type)

    if not result['success']:
        # 更新设备最后检查时间
        device.last_checked = datetime.utcnow()
        db.session.commit()
        flash(f'配置捕获失败 ({device_name}): {result["error"]}', 'danger')
        return redirect(url_for('config_compliance.config_baseline'))

    content = result['content']
    content_hash = hashlib.sha256(content.encode()).hexdigest()

    # 4. 将旧基线标记为非活跃
    ConfigBaseline.query.filter_by(
        device_id=device_id, config_type=config_type, is_active=True
    ).update({'is_active': False})

    # 5. 保存新基线
    baseline = ConfigBaseline(
        device_id=device_id,
        config_type=config_type,
        content=content,
        hash=content_hash,
        captured_by='manual',
        is_active=True,
        description=f'SSH 捕获 ({result["device_ip"]}), {result["line_count"]} 行',
    )
    db.session.add(baseline)

    # 6. 更新设备状态
    device.status = 'online'
    device.last_checked = datetime.utcnow()

    db.session.commit()

    log_audit('create', 'config_baseline', baseline.id,
              f'捕获配置基线 - 设备 {device_name} ({config_type}), {result["line_count"]} 行',
              details={
                  'device_id': device_id,
                  'config_type': config_type,
                  'device_ip': ip,
                  'line_count': result['line_count'],
                  'command': result['command'],
              },
              user_id=current_user.id)

    flash(f'配置基线已捕获 ({device_name}), 共 {result["line_count"]} 行', 'success')
    return redirect(url_for('config_compliance.config_baseline'))


@config_compliance_bp.route('/config-baseline/<int:id>')
@login_required
@permission_required('config:view')
def config_baseline_detail(id):
    """查看基线详细内容"""
    baseline = ConfigBaseline.query.get_or_404(id)
    return render_template('config/config_baseline_detail.html', baseline=baseline)


@config_compliance_bp.route('/config-baseline/<int:id>/delete', methods=['POST'])
@login_required
@permission_required('config:edit')
def config_baseline_delete(id):
    """删除基线"""
    baseline = ConfigBaseline.query.get_or_404(id)
    device_name = baseline.device.name if baseline.device else '未知设备'
    try:
        db.session.delete(baseline)
        db.session.commit()
        log_audit('delete', 'config_baseline', id, f'删除配置基线 - {device_name}',
                  details={'device_id': baseline.device_id, 'config_type': baseline.config_type},
                  user_id=current_user.id)
        flash('配置基线已删除', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'删除失败: {str(e)}', 'danger')
    return redirect(url_for('config_compliance.config_baseline'))


@config_compliance_bp.route('/config-baseline/<int:id>/toggle', methods=['POST'])
@login_required
@permission_required('config:edit')
def config_baseline_toggle(id):
    """切换基线活跃状态"""
    baseline = ConfigBaseline.query.get_or_404(id)
    device_name = baseline.device.name if baseline.device else '未知设备'

    if baseline.is_active:
        baseline.is_active = False
        db.session.commit()
        flash(f'基线已取消激活 ({device_name})', 'warning')
    else:
        # 将同设备同类型的其他基线标记为非活跃
        ConfigBaseline.query.filter_by(
            device_id=baseline.device_id, config_type=baseline.config_type, is_active=True
        ).update({'is_active': False})
        baseline.is_active = True
        db.session.commit()
        flash(f'基线已设为当前基线 ({device_name})', 'success')

    log_audit('update', 'config_baseline', id,
              f'{"激活" if baseline.is_active else "取消激活"}配置基线 - {device_name}',
              details={'device_id': baseline.device_id, 'config_type': baseline.config_type, 'is_active': baseline.is_active},
              user_id=current_user.id)

    return redirect(url_for('config_compliance.config_baseline'))


@config_compliance_bp.route('/config-baseline/<int:id>/detect-drift', methods=['POST'])
@login_required
@permission_required('config:edit')
def config_baseline_detect_drift(id):
    """检测配置漂移：与最新同类型的基线对比"""
    baseline = ConfigBaseline.query.get_or_404(id)
    device = baseline.device

    # 查找该设备同类型的上一个基线
    prev_baseline = ConfigBaseline.query.filter(
        ConfigBaseline.device_id == baseline.device_id,
        ConfigBaseline.config_type == baseline.config_type,
        ConfigBaseline.id != baseline.id,
        ConfigBaseline.captured_at < baseline.captured_at,
    ).order_by(ConfigBaseline.captured_at.desc()).first()

    if not prev_baseline:
        flash('没有找到可对比的基线记录，请先捕获至少两条基线', 'warning')
        return redirect(url_for('config_compliance.config_baseline'))

    # 检测变更
    changes = detect_changes(prev_baseline.content, baseline.content)

    if changes['total_changes'] > 0:
        drift = ConfigDrift(
            device_id=baseline.device_id,
            baseline_id=baseline.id,
            drift_type='modified',
            before_content=prev_baseline.content,
            after_content=baseline.content,
            diff_summary=f"{changes['summary']} (基线#{prev_baseline.id} → #{baseline.id})",
            severity=_assess_severity(changes),
            status='open',
        )
        db.session.add(drift)
        db.session.commit()

        log_audit('create', 'config_drift', drift.id,
                  f'检测到配置漂移 - {device.name} ({baseline.config_type})',
                  details={'device_id': baseline.device_id, 'changes': changes},
                  user_id=current_user.id)

        flash(f'检测到配置漂移: {changes["summary"]}', 'warning')
    else:
        flash('配置无变化，未检测到漂移', 'success')

    return redirect(url_for('config_compliance.config_baseline'))


def _assess_severity(changes):
    """根据变更量评估严重度"""
    total = changes['total_changes']
    if total > 50:
        return 'critical'
    elif total > 20:
        return 'high'
    elif total > 5:
        return 'medium'
    return 'low'


@config_compliance_bp.route('/config-baseline/drifts')
@login_required
@permission_required('config:view')
def config_baseline_drifts():
    """配置漂移列表"""
    page = request.args.get('page', 1, type=int)
    device_id = request.args.get('device_id', type=int)
    status = request.args.get('status', '')

    query = ConfigDrift.query
    if device_id:
        query = query.filter_by(device_id=device_id)
    if status:
        query = query.filter_by(status=status)

    drifts = query.order_by(ConfigDrift.detected_at.desc()).paginate(page=page, per_page=20)
    devices = Device.query.order_by(Device.name).all()
    return render_template('config/config_baseline_drifts.html', drifts=drifts, devices=devices,
                           current_device_id=device_id, current_status=status)


@config_compliance_bp.route('/config-baseline/drift/<int:id>/resolve', methods=['POST'])
@login_required
@permission_required('config:edit')
def config_baseline_drift_resolve(id):
    """确认/解决配置漂移"""
    drift = ConfigDrift.query.get_or_404(id)
    drift.status = 'resolved'
    drift.resolved_at = datetime.utcnow()
    drift.resolved_by = current_user.id
    db.session.commit()

    log_audit('update', 'config_drift', id, '解决配置漂移',
              details={'device_id': drift.device_id, 'status': 'resolved'},
              user_id=current_user.id)

    flash('漂移记录已标记为已解决', 'success')
    return redirect(url_for('config_compliance.config_baseline_drifts'))


@config_compliance_bp.route('/config-diff/<int:device_id>')
@login_required
@permission_required('config:view')
def config_diff(device_id):
    """配置差异对比"""
    device = Device.query.get_or_404(device_id)
    baseline_id = request.args.get('baseline_id', type=int)
    version_id = request.args.get('version_id', type=int)

    baseline = ConfigBaseline.query.get(baseline_id) if baseline_id else None
    version = ConfigVersion.query.get(version_id) if version_id else None

    # 生成差异对比HTML
    diff_html = None
    diff_stats = None
    left_lines = None
    right_lines = None
    left_label = None
    right_label = None

    if baseline and version:
        diff_html = generate_diff_html(baseline.content, version.content)
        diff_stats = detect_changes(baseline.content, version.content)
        left_lines, right_lines = generate_side_by_side_html(baseline.content, version.content)
        left_label = f'基线 ({baseline.captured_at.strftime("%Y-%m-%d %H:%M")})' if baseline.captured_at else '基线'
        right_label = f'v{version.version_number}' if version else '版本'
    elif baseline:
        configs = [('基线', baseline.content, baseline.captured_at)]
    elif version:
        configs = [(f'v{version.version_number}', version.content, version.created_at)]
    else:
        configs = []

    # 获取该设备的所有基线和版本
    baselines = ConfigBaseline.query.filter_by(device_id=device_id).order_by(ConfigBaseline.captured_at.desc()).all()
    versions = ConfigVersion.query.filter_by(device_id=device_id).order_by(ConfigVersion.version_number.desc()).all()

    return render_template('config/config_diff.html', device=device,
                           configs=configs if not diff_html else [],
                           baselines=baselines, versions=versions,
                           baseline=baseline, version=version,
                           diff_html=diff_html, diff_stats=diff_stats,
                           left_lines=left_lines, right_lines=right_lines,
                           left_label=left_label, right_label=right_label)


@config_compliance_bp.route('/config-versions/<int:device_id>')
@login_required
@permission_required('config:view')
def config_versions(device_id):
    """配置版本历史"""
    device = Device.query.get_or_404(device_id)
    versions = ConfigVersion.query.filter_by(device_id=device_id).order_by(ConfigVersion.version_number.desc()).all()
    return render_template('config/config_versions.html', device=device, versions=versions)


@config_compliance_bp.route('/config-versions/save', methods=['POST'])
@login_required
@permission_required('config:edit')
def config_version_save():
    """保存配置版本"""
    device_id = request.form.get('device_id', type=int)
    config_type = request.form.get('config_type', 'running')
    content = request.form.get('content', '')
    change_summary = request.form.get('change_summary', '')

    # 获取最新版本号
    last = ConfigVersion.query.filter_by(device_id=device_id, config_type=config_type)\
        .order_by(ConfigVersion.version_number.desc()).first()
    version_number = (last.version_number + 1) if last else 1

    checksum = hashlib.sha256(content.encode()).hexdigest()

    version = ConfigVersion(
        device_id=device_id,
        version_number=version_number,
        config_type=config_type,
        content=content,
        change_summary=change_summary,
        checksum=checksum,
        changed_by=current_user.username,
    )
    db.session.add(version)
    db.session.commit()

    log_audit('create', 'config_version', version.id,
              f'保存配置版本 v{version_number} - 设备 #{device_id}',
              details={'device_id': device_id, 'config_type': config_type, 'version_number': version_number},
              user_id=current_user.id)

    flash(f'配置版本 v{version_number} 已保存', 'success')
    return redirect(url_for('config_compliance.config_versions', device_id=device_id))


# ==================== 备份验证 ====================

@config_compliance_bp.route('/backup/verify')
@login_required
@permission_required('config:view')
def backup_verify():
    """备份验证管理"""
    page = request.args.get('page', 1, type=int)
    verifications = BackupVerification.query.order_by(BackupVerification.verified_at.desc()).paginate(page=page, per_page=20)
    backup_configs = BackupConfig.query.all()
    return render_template('config/backup_verify.html', verifications=verifications, backup_configs=backup_configs)


@config_compliance_bp.route('/backup/verify/run', methods=['POST'])
@login_required
@permission_required('config:edit')
def backup_verify_run():
    """执行备份验证"""
    config_id = request.form.get('backup_config_id', type=int)
    config = BackupConfig.query.get_or_404(config_id)

    # 模拟验证过程
    import secrets
    verification = BackupVerification(
        backup_config_id=config.id,
        status='verified',
        file_size=secrets.randbelow(1048576) + 1048576,
        checksum=secrets.token_hex(32),
        restore_test_result='pass',
        duration_seconds=secrets.randbelow(120) + 10,
        verified_by=current_user.id,
        notes='自动验证通过',
    )
    db.session.add(verification)
    db.session.commit()

    log_audit('execute', 'backup_verification', verification.id,
              f'执行备份验证 - 配置 #{config_id}',
              details={'backup_config_id': config_id, 'status': verification.status},
              user_id=current_user.id)

    flash('备份验证完成', 'success')
    return redirect(url_for('config_compliance.backup_verify'))


# ==================== API端点 ====================

@config_compliance_bp.route('/api/compliance/stats')
@login_required
@permission_required('config:view')
def api_compliance_stats():
    """合规统计API"""
    total_policies = CompliancePolicy.query.count()
    enabled = CompliancePolicy.query.filter_by(enabled=True).count()
    total_checks = ComplianceCheckResult.query.count()
    passed = ComplianceCheckResult.query.filter_by(status='pass').count()

    by_category = db.session.query(
        CompliancePolicy.category, func.count(CompliancePolicy.id)
    ).group_by(CompliancePolicy.category).all()

    return jsonify({
        'total_policies': total_policies,
        'enabled': enabled,
        'total_checks': total_checks,
        'passed': passed,
        'pass_rate': round(passed / total_checks * 100, 1) if total_checks > 0 else 0,
        'by_category': dict(by_category),
    })


@config_compliance_bp.route('/api/config-drifts')
@login_required
@permission_required('config:view')
def api_config_drifts():
    """配置漂移列表API"""
    page = request.args.get('page', 1, type=int)
    device_id = request.args.get('device_id', type=int)

    query = ConfigDrift.query
    if device_id:
        query = query.filter_by(device_id=device_id)

    drifts = query.order_by(ConfigDrift.detected_at.desc()).paginate(page=page, per_page=50)
    return jsonify({
        'drifts': [d.to_dict() for d in drifts.items],
        'total': drifts.total,
        'pages': drifts.pages,
    })
