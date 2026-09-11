# -*- coding: utf-8 -*-
"""自动化执行中心蓝图：批量执行 / 作业模板 / 审批 / 定时 / API 令牌 / WebSSH。"""
import io
import json
from datetime import datetime
from functools import wraps

from flask import (
    Blueprint, request, jsonify, render_template, redirect, url_for, flash,
    current_app, send_file,
)
from flask_login import login_required, current_user

from extensions import db
from models.exec_models import ExecTask, ExecTaskDevice, ExecTemplate, ApiKey
from models.models import Device
from models.device_group_models import DeviceGroup
from models.network_models import Subnet, IPAddress
from forms import ExecTaskForm, ExecTemplateForm, ApiKeyForm
from utils.permission import permission_required
from utils.audit import log_audit
from services.execution_service import (
    run_task, cancel_task, rollback_device, reschedule_exec_task,
    remove_exec_task_job, validate_exec_schedule,
)

automation_bp = Blueprint('automation', __name__, url_prefix='/automation')

STATUS_LABELS = {
    'ready': '待执行', 'waiting_approval': '待审批', 'running': '执行中',
    'completed': '已完成', 'partial': '部分成功', 'failed': '失败',
    'cancelled': '已取消', 'rejected': '已驳回',
}
TASK_TYPE_LABELS = {
    'command': '命令执行', 'script': '脚本执行', 'config_push': '配置下发',
}
PROTOCOL_LABELS = {
    'auto': '自动', 'ssh': 'SSH', 'winrm': 'WinRM', 'netmiko': 'Netmiko', 'local': '本机',
}


def _audit(action, resource_type, resource_id, message, **kwargs):
    log_audit(
        action, resource_type, resource_id, message,
        user_id=current_user.id if current_user.is_authenticated else None,
        **kwargs,
    )


def _collect_group_devices(group):
    devices = list(group.devices) if group.devices else []
    seen = {d.id for d in devices}
    for child in group.children or []:
        for d in _collect_group_devices(child):
            if d.id not in seen:
                seen.add(d.id)
                devices.append(d)
    return devices


def _resolve_target_devices(target_mode, device_ids=None, group_id=None, subnet_id=None, require_ip=False):
    """根据目标选择方式解析设备列表（去重，并过滤退役设备）。"""
    import ipaddress as ipmod
    devices = []
    if target_mode == 'devices':
        if device_ids:
            devices = Device.query.filter(Device.id.in_(device_ids), Device.is_decommissioned.is_(False)).all()
    elif target_mode == 'group':
        group = DeviceGroup.query.get(group_id) if group_id else None
        if group:
            devices = _collect_group_devices(group)
    elif target_mode == 'subnet':
        subnet = Subnet.query.get(subnet_id) if subnet_id else None
        if subnet:
            seen = set()
            for rec in subnet.ip_addresses.filter(IPAddress.device_id.isnot(None)).all():
                if rec.device and rec.device_id not in seen:
                    seen.add(rec.device_id)
                    devices.append(rec.device)
            try:
                net = ipmod.IPv4Network(f'{subnet.network}/{subnet.prefix_length}', strict=False)
                for d in Device.query.filter(Device.is_decommissioned.is_(False)).all():
                    ip = d.management_ip or d.ip_address
                    if ip and d.id not in seen:
                        try:
                            if ipmod.ip_address(ip) in net:
                                seen.add(d.id)
                                devices.append(d)
                        except ValueError:
                            pass
            except ValueError:
                pass
    elif target_mode == 'all':
        devices = Device.query.filter(
            Device.is_decommissioned.is_(False),
            db.or_(Device.management_ip.isnot(None), Device.ip_address.isnot(None)),
        ).all()
    # 过滤退役设备；本地执行以外必须有可连接 IP。
    devices = [d for d in devices if not d.is_decommissioned]
    if require_ip:
        devices = [d for d in devices if d.management_ip or d.ip_address]
    return list({d.id: d for d in devices}.values())


def _form_target_ref(form):
    """将表单目标选择转为可追溯的 target_ref。"""
    if form.target_mode.data == 'group':
        return str(form.group_id.data or '')
    if form.target_mode.data == 'subnet':
        return str(form.subnet_id.data or '')
    if form.target_mode.data == 'devices':
        return ','.join(str(i) for i in (form.device_ids.data or []))[:200]
    return ''

# ==================== API 令牌鉴权 ====================

def api_token_required(scope='read'):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            token = request.headers.get('Authorization', '')
            if token.startswith('Bearer '):
                token = token[7:]
            if not token:
                token = request.headers.get('X-API-Key', '')
            if not token:
                return jsonify({'error': '缺少 API 令牌'}), 401
            key = ApiKey.query.filter_by(key_hash=ApiKey.hash_key(token)).first()
            if not key or not key.is_active:
                return jsonify({'error': 'API 令牌无效或已停用'}), 401
            if scope == 'write' and key.scope != 'write':
                return jsonify({'error': '该令牌没有写权限'}), 403
            key.last_used_at = datetime.utcnow()
            db.session.commit()
            return f(*args, **kwargs)
        return wrapper
    return decorator


# ==================== 概览 ====================

@automation_bp.route('/')
@login_required
@permission_required('exec:view')
def dashboard():
    stats = {s: ExecTask.query.filter_by(status=s).count() for s in STATUS_LABELS}
    total = sum(stats.values())
    success = db.session.query(db.func.coalesce(db.func.sum(ExecTask.success_count), 0)).scalar() or 0
    failed = db.session.query(db.func.coalesce(db.func.sum(ExecTask.failed_count), 0)).scalar() or 0
    rate = round(success / (success + failed) * 100, 1) if (success + failed) else 0
    recent = ExecTask.query.order_by(ExecTask.created_at.desc()).limit(10).all()
    templates = ExecTemplate.query.count()
    api_keys = ApiKey.query.count()
    return render_template(
        'automation/dashboard.html',
        stats=stats, total=total, success=success, failed=failed, rate=rate,
        recent=recent, templates=templates, api_keys=api_keys,
        status_labels=STATUS_LABELS, task_type_labels=TASK_TYPE_LABELS,
    )


# ==================== 任务管理 ====================

@automation_bp.route('/tasks')
@login_required
@permission_required('exec:view')
def task_list():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    status = request.args.get('status', '').strip()
    task_type = request.args.get('task_type', '').strip()
    q = request.args.get('q', '').strip()
    query = ExecTask.query
    if status:
        query = query.filter(ExecTask.status == status)
    if task_type:
        query = query.filter(ExecTask.task_type == task_type)
    if q:
        like = f'%{q}%'
        query = query.filter(db.or_(
            ExecTask.name.like(like),
            ExecTask.description.like(like),
        ))
    pagination = query.order_by(ExecTask.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False)
    return render_template(
        'automation/task_list.html',
        pagination=pagination, tasks=pagination.items,
        status=status, task_type=task_type, q=q,
        status_labels=STATUS_LABELS, task_type_labels=TASK_TYPE_LABELS,
    )


@automation_bp.route('/tasks/create', methods=['GET', 'POST'])
@login_required
@permission_required('exec:run')
def task_create():
    form = ExecTaskForm()
    template = None
    if request.method == 'GET':
        tid = request.args.get('template_id', type=int)
        if tid:
            template = ExecTemplate.query.get(tid)
            if template:
                form.name.data = template.name
                form.description.data = template.description
                form.task_type.data = template.task_type
                form.protocol.data = template.protocol
                form.content.data = template.content
                form.timeout.data = template.timeout or 30
                form.approval_required.data = template.approval_required
    if form.validate_on_submit():
        app = current_app._get_current_object()
        if form.target_mode.data == 'devices' and not form.device_ids.data:
            flash('手动选择设备时至少选择一台设备', 'danger')
            return render_template('automation/task_form.html', form=form, title='新建任务',
                                   templates=ExecTemplate.query.order_by(ExecTemplate.name).all())
        require_ip = form.protocol.data != 'local'
        devices = _resolve_target_devices(
            form.target_mode.data, form.device_ids.data,
            form.group_id.data, form.subnet_id.data, require_ip=require_ip,
        )
        if not devices:
            if require_ip:
                flash('目标范围内没有可执行的设备（需要有 IP 地址）', 'danger')
            else:
                flash('目标范围内没有可用设备', 'danger')
            return render_template('automation/task_form.html', form=form, title='新建任务',
                                   templates=ExecTemplate.query.order_by(ExecTemplate.name).all())
        if form.schedule_enabled.data:
            valid, msg = validate_exec_schedule(form.schedule_type.data, form.schedule_value.data)
            if not valid:
                flash(f'定时设置无效：{msg}', 'danger')
                return render_template('automation/task_form.html', form=form, title='新建任务',
                                       templates=ExecTemplate.query.order_by(ExecTemplate.name).all())
        target_ref = _form_target_ref(form)
        task = ExecTask(
            name=form.name.data.strip(),
            description=form.description.data,
            task_type=form.task_type.data,
            protocol=form.protocol.data,
            content=form.content.data,
            timeout=form.timeout.data or 30,
            target_scope=form.target_mode.data,
            target_ref=target_ref,
            approval_required=form.approval_required.data,
            approval_status='pending' if form.approval_required.data else 'none',
            status='waiting_approval' if form.approval_required.data else 'ready',
            schedule_enabled=form.schedule_enabled.data,
            schedule_type=form.schedule_type.data,
            schedule_value=form.schedule_value.data.strip(),
            notify_enabled=form.notify_enabled.data,
            created_by=current_user.id,
            device_count=len(devices),
        )
        db.session.add(task)
        db.session.flush()
        seen = set()
        for d in devices:
            if d.id in seen:
                continue
            seen.add(d.id)
            db.session.add(ExecTaskDevice(
                task_id=task.id,
                device_id=d.id,
                device_name=d.name,
                ip_address=d.management_ip or d.ip_address or '',
                protocol=form.protocol.data,
                status='pending',
            ))
        try:
            db.session.commit()
            _audit('create', 'exec_task', task.id, f'新建执行任务: {task.name}（{len(devices)} 台设备）')
            if form.schedule_enabled.data:
                reschedule_exec_task(task.id)
            flash(f'任务 "{task.name}" 创建成功，目标 {len(devices)} 台设备', 'success')
            if form.approval_required.data:
                flash('该任务需要审批通过后才会执行', 'info')
                return redirect(url_for('automation.task_detail', id=task.id))
            if form.auto_run.data:
                run_task(app, task.id)
                flash('任务已开始执行', 'info')
            return redirect(url_for('automation.task_detail', id=task.id))
        except Exception as e:
            db.session.rollback()
            flash(f'创建失败: {e}', 'danger')
    return render_template('automation/task_form.html', form=form, title='新建任务',
                           templates=ExecTemplate.query.order_by(ExecTemplate.name).all())

@automation_bp.route('/tasks/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@permission_required('exec:run')
def task_edit(id):
    task = ExecTask.query.get_or_404(id)
    if task.status == 'running':
        flash('任务正在执行，不能编辑', 'warning')
        return redirect(url_for('automation.task_detail', id=task.id))
    form = ExecTaskForm(obj=task)
    if request.method == 'GET':
        if task.target_scope == 'devices':
            form.device_ids.data = [r.device_id for r in task.devices.all() if r.device_id]
        elif task.target_scope == 'group':
            try:
                form.group_id.data = int(task.target_ref or 0)
            except (TypeError, ValueError):
                form.group_id.data = 0
        elif task.target_scope == 'subnet':
            try:
                form.subnet_id.data = int(task.target_ref or 0)
            except (TypeError, ValueError):
                form.subnet_id.data = 0
    if form.validate_on_submit():
        if form.target_mode.data == 'devices' and not form.device_ids.data:
            flash('手动选择设备时至少选择一台设备', 'danger')
            return render_template('automation/task_form.html', form=form, title='编辑任务',
                                   templates=ExecTemplate.query.order_by(ExecTemplate.name).all())
        require_ip = form.protocol.data != 'local'
        devices = _resolve_target_devices(
            form.target_mode.data, form.device_ids.data,
            form.group_id.data, form.subnet_id.data, require_ip=require_ip,
        )
        if not devices:
            if require_ip:
                flash('目标范围内没有可执行的设备（需要有 IP 地址）', 'danger')
            else:
                flash('目标范围内没有可用设备', 'danger')
            return render_template('automation/task_form.html', form=form, title='编辑任务',
                                   templates=ExecTemplate.query.order_by(ExecTemplate.name).all())
        if form.schedule_enabled.data:
            valid, msg = validate_exec_schedule(form.schedule_type.data, form.schedule_value.data)
            if not valid:
                flash(f'定时设置无效：{msg}', 'danger')
                return render_template('automation/task_form.html', form=form, title='编辑任务',
                                       templates=ExecTemplate.query.order_by(ExecTemplate.name).all())
        target_ref = _form_target_ref(form)
        old_ids = {r.device_id for r in task.devices.all() if r.device_id}
        new_ids = {d.id for d in devices}
        target_changed = (old_ids != new_ids or task.target_scope != form.target_mode.data or task.target_ref != target_ref)
        approval_changed = task.approval_required != form.approval_required.data
        task.name = form.name.data.strip()
        task.description = form.description.data
        task.task_type = form.task_type.data
        task.protocol = form.protocol.data
        task.content = form.content.data
        task.timeout = form.timeout.data or 30
        task.target_scope = form.target_mode.data
        task.target_ref = target_ref
        task.approval_required = form.approval_required.data
        task.schedule_enabled = form.schedule_enabled.data
        task.schedule_type = form.schedule_type.data
        task.schedule_value = form.schedule_value.data.strip()
        task.notify_enabled = form.notify_enabled.data
        if target_changed or approval_changed:
            if target_changed:
                for r in task.devices.all():
                    db.session.delete(r)
                db.session.flush()
                seen = set()
                for d in devices:
                    if d.id in seen:
                        continue
                    seen.add(d.id)
                    db.session.add(ExecTaskDevice(
                        task_id=task.id,
                        device_id=d.id,
                        device_name=d.name,
                        ip_address=d.management_ip or d.ip_address or '',
                        protocol=form.protocol.data,
                        status='pending',
                    ))
            task.device_count = len(devices)
            task.approval_status = 'pending' if form.approval_required.data else 'none'
            task.status = 'waiting_approval' if form.approval_required.data else 'ready'
            task.approver_id = None
            task.approved_at = None
            task.approval_comment = None
            task.started_at = None
            task.finished_at = None
            task.success_count = 0
            task.failed_count = 0
            task.result_summary = None
        else:
            task.device_count = len(devices)
            for r in task.devices.all():
                r.protocol = form.protocol.data
        try:
            db.session.commit()
            _audit('update', 'exec_task', task.id, f'编辑执行任务: {task.name}')
            if task.schedule_enabled:
                reschedule_exec_task(task.id)
            else:
                remove_exec_task_job(task.id)
            flash('任务已更新', 'success')
            return redirect(url_for('automation.task_detail', id=task.id))
        except Exception as e:
            db.session.rollback()
            flash(f'更新失败: {e}', 'danger')
    return render_template('automation/task_form.html', form=form, title='编辑任务',
                           templates=ExecTemplate.query.order_by(ExecTemplate.name).all())

@automation_bp.route('/tasks/<int:id>')
@login_required
@permission_required('exec:view')
def task_detail(id):
    task = ExecTask.query.get_or_404(id)
    page = request.args.get('page', 1, type=int)
    status = request.args.get('status', '').strip()
    query = task.devices
    if status:
        query = query.filter(ExecTaskDevice.status == status)
    pagination = query.order_by(ExecTaskDevice.id).paginate(page=page, per_page=50, error_out=False)
    return render_template(
        'automation/task_detail.html',
        task=task, pagination=pagination, results=pagination.items,
        status=status, status_labels=STATUS_LABELS,
        task_type_labels=TASK_TYPE_LABELS, protocol_labels=PROTOCOL_LABELS,
    )


@automation_bp.route('/tasks/<int:id>/run', methods=['POST'])
@login_required
@permission_required('exec:run')
def task_run(id):
    task = ExecTask.query.get_or_404(id)
    if task.status == 'running':
        flash('任务已在执行中，请勿重复执行', 'warning')
        return redirect(url_for('automation.task_detail', id=task.id))
    if task.approval_required and task.approval_status != 'approved':
        flash('该任务需要审批通过后才能执行', 'warning')
        return redirect(url_for('automation.task_detail', id=task.id))
    retry_failed = request.form.get('retry_failed') == 'on'
    app = current_app._get_current_object()
    if run_task(app, task.id, retry_failed=retry_failed):
        _audit('run', 'exec_task', task.id, f'执行任务: {task.name}（重试失败: {retry_failed}）')
        flash('任务已开始执行', 'info')
    else:
        flash('任务未启动：可能正在执行或没有可执行的设备', 'warning')
    return redirect(url_for('automation.task_detail', id=task.id))

@automation_bp.route('/tasks/<int:id>/cancel', methods=['POST'])
@login_required
@permission_required('exec:run')
def task_cancel(id):
    task = ExecTask.query.get_or_404(id)
    app = current_app._get_current_object()
    if cancel_task(app, task.id):
        task.status = 'cancelled'
        db.session.commit()
        _audit('cancel', 'exec_task', task.id, f'取消任务: {task.name}')
        flash('任务已取消', 'success')
    else:
        flash('任务当前不可取消', 'warning')
    return redirect(url_for('automation.task_detail', id=task.id))


@automation_bp.route('/tasks/<int:id>/approve', methods=['POST'])
@login_required
@permission_required('exec:approve')
def task_approve(id):
    task = ExecTask.query.get_or_404(id)
    if task.approval_status != 'pending':
        flash('该任务不在待审批状态', 'warning')
        return redirect(url_for('automation.task_detail', id=task.id))
    task.approval_status = 'approved'
    task.status = 'ready'
    task.approver_id = current_user.id
    task.approved_at = datetime.utcnow()
    task.approval_comment = (request.form.get('comment') or '').strip()
    db.session.commit()
    _audit('approve', 'exec_task', task.id, f'审批通过任务: {task.name}')
    app = current_app._get_current_object()
    if run_task(app, task.id):
        flash('已审批通过，任务开始执行', 'success')
    else:
        flash('已审批通过，但任务未启动（可能没有可执行设备）', 'warning')
    return redirect(url_for('automation.task_detail', id=task.id))


@automation_bp.route('/tasks/<int:id>/reject', methods=['POST'])
@login_required
@permission_required('exec:approve')
def task_reject(id):
    task = ExecTask.query.get_or_404(id)
    if task.approval_status != 'pending':
        flash('该任务不在待审批状态', 'warning')
        return redirect(url_for('automation.task_detail', id=task.id))
    task.approval_status = 'rejected'
    task.status = 'rejected'
    task.approver_id = current_user.id
    task.approval_comment = (request.form.get('comment') or '').strip()
    db.session.commit()
    _audit('reject', 'exec_task', task.id, f'驳回任务: {task.name}')
    flash('任务已驳回', 'success')
    return redirect(url_for('automation.task_detail', id=task.id))


@automation_bp.route('/tasks/<int:id>/delete', methods=['POST'])
@login_required
@permission_required('exec:run')
def task_delete(id):
    task = ExecTask.query.get_or_404(id)
    if task.status == 'running':
        flash('任务正在执行，不能删除', 'warning')
        return redirect(url_for('automation.task_detail', id=task.id))
    remove_exec_task_job(task.id)
    name = task.name
    db.session.delete(task)
    db.session.commit()
    _audit('delete', 'exec_task', id, f'删除执行任务: {name}')
    flash(f'任务 "{name}" 已删除', 'success')
    return redirect(url_for('automation.task_list'))


@automation_bp.route('/tasks/<int:id>/devices/<int:record_id>/rollback', methods=['POST'])
@login_required
@permission_required('exec:run')
def task_device_rollback(id, record_id):
    task = ExecTask.query.get_or_404(id)
    app = current_app._get_current_object()
    ok, msg = rollback_device(app, task.id, record_id)
    _audit('rollback', 'exec_task_device', record_id, f'回滚配置: {task.name}', details={'result': msg})
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('automation.task_detail', id=task.id) + '#results')


@automation_bp.route('/tasks/<int:id>/export')
@login_required
@permission_required('exec:view')
def task_export(id):
    task = ExecTask.query.get_or_404(id)
    lines = [f'任务: {task.name}', f'状态: {STATUS_LABELS.get(task.status, task.status)}',
             f'结果: {task.result_summary or ""}', '=' * 60, '']
    for r in task.devices.all():
        lines.append(f'[{r.status}] {r.device_name} ({r.ip_address}) - {r.protocol}')
        if r.output:
            lines.append(r.output)
        if r.error:
            lines.append(f'[错误] {r.error}')
        lines.append('-' * 60)
    buf = io.BytesIO('\n'.join(lines).encode('utf-8'))
    return send_file(buf, as_attachment=True, download_name=f'task_{task.id}_{task.name}.txt',
                     mimetype='text/plain; charset=utf-8')


# ==================== 作业模板 ====================

@automation_bp.route('/templates')
@login_required
@permission_required('exec:view')
def template_list():
    q = request.args.get('q', '').strip()
    query = ExecTemplate.query
    if q:
        like = f'%{q}%'
        query = query.filter(db.or_(ExecTemplate.name.like(like), ExecTemplate.description.like(like)))
    templates = query.order_by(ExecTemplate.name).all()
    return render_template('automation/template_list.html', templates=templates, q=q,
                           task_type_labels=TASK_TYPE_LABELS)


@automation_bp.route('/templates/create', methods=['GET', 'POST'])
@login_required
@permission_required('exec:run')
def template_create():
    form = ExecTemplateForm()
    if form.validate_on_submit():
        if ExecTemplate.query.filter_by(name=form.name.data.strip()).first():
            flash('模板名称已存在', 'danger')
            return render_template('automation/template_form.html', form=form, title='新建模板')
        tpl = ExecTemplate(
            name=form.name.data.strip(),
            description=form.description.data,
            task_type=form.task_type.data,
            protocol=form.protocol.data,
            content=form.content.data,
            timeout=form.timeout.data or 30,
            approval_required=form.approval_required.data,
            created_by=current_user.id,
        )
        db.session.add(tpl)
        try:
            db.session.commit()
            _audit('create', 'exec_template', tpl.id, f'新建作业模板: {tpl.name}')
            flash(f'模板 "{tpl.name}" 创建成功', 'success')
            return redirect(url_for('automation.template_list'))
        except Exception as e:
            db.session.rollback()
            flash(f'创建失败: {e}', 'danger')
    return render_template('automation/template_form.html', form=form, title='新建模板')


@automation_bp.route('/templates/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@permission_required('exec:run')
def template_edit(id):
    tpl = ExecTemplate.query.get_or_404(id)
    form = ExecTemplateForm(obj=tpl)
    if form.validate_on_submit():
        dup = ExecTemplate.query.filter(ExecTemplate.name == form.name.data.strip(), ExecTemplate.id != tpl.id).first()
        if dup:
            flash('模板名称已被使用', 'danger')
            return render_template('automation/template_form.html', form=form, title='编辑模板')
        tpl.name = form.name.data.strip()
        tpl.description = form.description.data
        tpl.task_type = form.task_type.data
        tpl.protocol = form.protocol.data
        tpl.content = form.content.data
        tpl.timeout = form.timeout.data or 30
        tpl.approval_required = form.approval_required.data
        try:
            db.session.commit()
            _audit('update', 'exec_template', tpl.id, f'编辑作业模板: {tpl.name}')
            flash('模板已更新', 'success')
            return redirect(url_for('automation.template_list'))
        except Exception as e:
            db.session.rollback()
            flash(f'更新失败: {e}', 'danger')
    return render_template('automation/template_form.html', form=form, title='编辑模板')


@automation_bp.route('/templates/<int:id>/delete', methods=['POST'])
@login_required
@permission_required('exec:run')
def template_delete(id):
    tpl = ExecTemplate.query.get_or_404(id)
    name = tpl.name
    db.session.delete(tpl)
    db.session.commit()
    _audit('delete', 'exec_template', id, f'删除作业模板: {name}')
    flash(f'模板 "{name}" 已删除', 'success')
    return redirect(url_for('automation.template_list'))


# ==================== API 令牌管理 ====================

@automation_bp.route('/api-keys')
@login_required
@permission_required('exec:view')
def api_key_list():
    keys = ApiKey.query.order_by(ApiKey.created_at.desc()).all()
    return render_template('automation/api_keys.html', keys=keys)


@automation_bp.route('/api-keys/create', methods=['POST'])
@login_required
@permission_required('exec:run')
def api_key_create():
    form = ApiKeyForm()
    if form.validate_on_submit():
        raw = ApiKey.generate_key()
        key = ApiKey(
            name=form.name.data.strip(),
            key_prefix=raw[:12],
            key_hash=ApiKey.hash_key(raw),
            scope=form.scope.data,
            created_by=current_user.id,
        )
        db.session.add(key)
        try:
            db.session.commit()
            _audit('create', 'api_key', key.id, f'生成 API 令牌: {key.name}')
            flash(f'令牌已生成（仅显示一次，请妥善保存）：{raw}', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'生成失败: {e}', 'danger')
    return redirect(url_for('automation.api_key_list'))


@automation_bp.route('/api-keys/<int:id>/toggle', methods=['POST'])
@login_required
@permission_required('exec:run')
def api_key_toggle(id):
    key = ApiKey.query.get_or_404(id)
    key.is_active = not key.is_active
    db.session.commit()
    flash(f'令牌 {key.name} 已{"停用" if not key.is_active else "启用"}', 'success')
    return redirect(url_for('automation.api_key_list'))


@automation_bp.route('/api-keys/<int:id>/delete', methods=['POST'])
@login_required
@permission_required('exec:run')
def api_key_delete(id):
    key = ApiKey.query.get_or_404(id)
    name = key.name
    db.session.delete(key)
    db.session.commit()
    _audit('delete', 'api_key', id, f'删除 API 令牌: {name}')
    flash(f'令牌 "{name}" 已删除', 'success')
    return redirect(url_for('automation.api_key_list'))


# ==================== WebSSH ====================

@automation_bp.route('/ssh')
@login_required
@permission_required('exec:view')
def ssh_terminal():
    devices = Device.query.filter(
        Device.is_decommissioned.is_(False),
        db.or_(Device.management_ip.isnot(None), Device.ip_address.isnot(None)),
    ).order_by(Device.name).all()
    return render_template('automation/ssh.html', devices=devices)


# ==================== 对外 API v1 ====================

@automation_bp.route('/api/v1/devices')
@api_token_required('read')
def api_v1_devices():
    q = request.args.get('q', '').strip()
    device_type = request.args.get('device_type', '').strip()
    query = Device.query.filter(Device.is_decommissioned.is_(False))
    if q:
        like = f'%{q}%'
        query = query.filter(db.or_(Device.name.like(like), Device.ip_address.like(like),
                                    Device.management_ip.like(like)))
    if device_type:
        query = query.filter(Device.device_type == device_type)
    devices = query.order_by(Device.name).limit(500).all()
    return jsonify({'success': True, 'data': [{
        'id': d.id, 'name': d.name, 'device_type': d.device_type,
        'ip': d.management_ip or d.ip_address or '', 'brand': d.brand or '',
        'status': d.status,
    } for d in devices]})


@automation_bp.route('/api/v1/subnets')
@api_token_required('read')
def api_v1_subnets():
    subnets = Subnet.query.order_by(Subnet.network).all()
    return jsonify({'success': True, 'data': [s.to_dict() for s in subnets]})


@automation_bp.route('/api/v1/ips')
@api_token_required('read')
def api_v1_ips():
    subnet_id = request.args.get('subnet_id', type=int)
    query = IPAddress.query
    if subnet_id:
        query = query.filter(IPAddress.subnet_id == subnet_id)
    ips = query.order_by(IPAddress.ip_address).limit(2000).all()
    return jsonify({'success': True, 'data': [ip.to_dict() for ip in ips]})


@automation_bp.route('/api/v1/tasks')
@api_token_required('read')
def api_v1_tasks():
    status = request.args.get('status', '').strip()
    query = ExecTask.query
    if status:
        query = query.filter(ExecTask.status == status)
    tasks = query.order_by(ExecTask.created_at.desc()).limit(100).all()
    return jsonify({'success': True, 'data': [t.to_dict() for t in tasks]})


@automation_bp.route('/api/v1/tasks', methods=['POST'])
@api_token_required('write')
def api_v1_task_create():
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    device_ids = data.get('device_ids') or []
    content = data.get('content') or ''
    if not name or not device_ids or not content:
        return jsonify({'success': False, 'error': '缺少必填字段 name/device_ids/content'}), 400
    devices = Device.query.filter(Device.id.in_(device_ids), Device.is_decommissioned.is_(False)).all()
    if not devices:
        return jsonify({'success': False, 'error': '没有匹配的设备'}), 400
    app = current_app._get_current_object()
    task = ExecTask(
        name=name,
        description=data.get('description') or '由 API 创建',
        task_type=data.get('task_type', 'command'),
        protocol=data.get('protocol', 'auto'),
        content=content,
        timeout=int(data.get('timeout', 30)),
        target_scope='devices',
        approval_required=False,
        approval_status='none',
        status='ready',
        notify_enabled=bool(data.get('notify', True)),
        device_count=len(devices),
    )
    db.session.add(task)
    db.session.flush()
    seen = set()
    for d in devices:
        if d.id in seen:
            continue
        seen.add(d.id)
        db.session.add(ExecTaskDevice(
            task_id=task.id, device_id=d.id, device_name=d.name,
            ip_address=d.management_ip or d.ip_address or '',
            protocol=task.protocol, status='pending',
        ))
    db.session.commit()
    if data.get('auto_run', True):
        run_task(app, task.id)
    return jsonify({'success': True, 'task': task.to_dict()}), 201
