"""ITIL 增强：自动化 CAB 审批链 + 变更冲突检测

作为 maintenance_bp 的路由扩展模块，在应用启动注册 blueprint 时导入即可。
包含：
- 审批链构建/重算（build_approval_chain / recompute_change_approval / get_active_stage）
- 阶段化审批通过/拒绝（approve_change_stage / reject_change_stage）
- CAB 阶段配置管理（cab_config）
- 变更冲突检测（detect_change_conflicts / change_conflicts API）
"""
from flask import (
    Blueprint, request, jsonify, flash, redirect, url_for, render_template
)
from flask_login import login_required, current_user

from utils.permission import permission_required
from extensions import db
from models.models import User, Device
from models.maintenance_models import ChangeRequest, ChangeApproval, CABConfig

# 复用已注册的 maintenance_bp，避免新增蓝图前缀
from blueprints.maintenance_routes import maintenance_bp
from utils.audit import log_audit

import json
from datetime import datetime


# ---------------------------------------------------------------------------
# 配置与审批链核心
# ---------------------------------------------------------------------------
def get_active_cab_config():
    """返回当前启用的 CAB 配置；若不存在则创建默认单阶段配置。"""
    cfg = CABConfig.query.filter_by(is_active=True).order_by(CABConfig.id).first()
    if not cfg:
        cfg = CABConfig(name='默认CAB', description='系统自动创建的默认审批链')
        cfg.set_stages([{'name': 'CAB评审', 'approver_ids': [], 'mode': 'any'}])
        cfg.is_active = True
        db.session.add(cfg)
        db.session.commit()
    return cfg


def build_approval_chain(change):
    """根据活动的 CAB 配置为变更生成审批链记录。"""
    cfg = get_active_cab_config()
    stages = cfg.get_stages()
    if not stages:
        stages = [{'name': 'CAB评审', 'approver_ids': [], 'mode': 'any'}]
    # 清掉旧链
    for a in change.approval_chain.all():
        db.session.delete(a)
    for idx, st in enumerate(stages, start=1):
        approver_ids = st.get('approver_ids') or []
        stage_name = st.get('name') or f'阶段{idx}'
        if approver_ids:
            for uid in approver_ids:
                u = User.query.get(uid)
                db.session.add(ChangeApproval(
                    change_id=change.id, stage=idx, stage_name=stage_name,
                    approver_id=uid, approver_name=u.username if u else None, status='pending'))
        else:
            # 开放槽位：任意具备 change:cab:approve 权限者均可审批
            db.session.add(ChangeApproval(
                change_id=change.id, stage=idx, stage_name=stage_name,
                approver_id=None, approver_name=None, status='pending'))
    change.approval_status = 'pending'
    change.current_stage = 1


def get_active_stage(change):
    """返回当前需审批的最低阶段号；若已全通过或已拒绝则返回 None。"""
    chain = change.approval_chain.all()
    if not chain:
        return None
    for stage in sorted(set(a.stage for a in chain)):
        rows = [a for a in chain if a.stage == stage]
        if any(r.status == 'rejected' for r in rows):
            return None
        if any(r.status == 'pending' for r in rows):
            return stage
    return None


def recompute_change_approval(change):
    """根据审批链重新计算阶段与变更整体审批状态。"""
    chain = change.approval_chain.all()
    if not chain:
        return
    cfg = get_active_cab_config()
    stages_def = cfg.get_stages()
    for stage in sorted(set(a.stage for a in chain)):
        rows = [a for a in chain if a.stage == stage]
        mode = 'all'
        if 1 <= stage <= len(stages_def):
            mode = stages_def[stage - 1].get('mode', 'all')
        approved = [a for a in rows if a.status == 'approved']
        rejected = [a for a in rows if a.status == 'rejected']
        if rejected:
            change.approval_status = 'rejected'
            change.status = 'rejected'
            change.approval_date = datetime.utcnow()
            change.approver_name = 'CAB'
            return
        satisfied = (mode == 'any' and len(approved) >= 1) or \
                   (mode == 'all' and len(approved) == len(rows))
        if not satisfied:
            change.approval_status = 'pending'
            change.current_stage = stage
            return
    # 所有阶段均满足
    change.approval_status = 'approved'
    change.status = 'approved'
    change.approval_date = datetime.utcnow()
    change.approver_name = 'CAB'


def detect_change_conflicts(change):
    """检测与同一设备、排期时间窗口重叠的其他未关闭变更。"""
    conflicts = []
    my_devices = [l.device_id for l in change.affected_device_links.all()]
    if not my_devices or not change.scheduled_date:
        return conflicts

    def to_min(t):
        if not t:
            return None
        try:
            h, m = str(t).split(':')
            return int(h) * 60 + int(m)
        except Exception:
            return None

    ms = to_min(change.scheduled_start_time)
    me = to_min(change.scheduled_end_time)
    others = ChangeRequest.query.filter(
        ChangeRequest.id != change.id,
        ChangeRequest.status.in_(['submitted', 'approved', 'scheduled', 'in_progress']),
        ChangeRequest.scheduled_date == change.scheduled_date
    ).all()
    for o in others:
        o_devices = [l.device_id for l in o.affected_device_links.all()]
        shared = set(my_devices) & set(o_devices)
        if not shared:
            continue
        os = to_min(o.scheduled_start_time)
        oe = to_min(o.scheduled_end_time)
        if ms and me and os and oe:
            overlap = not (me <= os or ms >= oe)
        else:
            overlap = True  # 同日但时间未知，保守视为冲突
        if overlap:
            conflicts.append({
                'change_id': o.id,
                'change_number': o.change_number,
                'title': o.title,
                'status': o.status,
                'scheduled_date': o.scheduled_date.strftime('%Y-%m-%d') if o.scheduled_date else '',
                'start': o.scheduled_start_time,
                'end': o.scheduled_end_time,
                'shared_devices': [Device.query.get(d).name for d in shared if Device.query.get(d)],
            })
    return conflicts


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------
@maintenance_bp.route('/change/approval/<int:approval_id>/approve', methods=['POST'])
@login_required
@permission_required('change:cab:approve')
def approve_change_stage(approval_id):
    ca = ChangeApproval.query.get_or_404(approval_id)
    change = ca.change
    if change.status not in ['submitted', 'pending', 'review']:
        flash('当前变更状态不可审批', 'warning')
        return redirect(url_for('maintenance.change_detail', change_id=change.id))
    if ca.status != 'pending':
        flash('该审批已处理', 'info')
        return redirect(url_for('maintenance.change_detail', change_id=change.id))
    active = get_active_stage(change)
    if active is None or ca.stage != active:
        flash('当前不可审批该阶段', 'warning')
        return redirect(url_for('maintenance.change_detail', change_id=change.id))
    if ca.approver_id and ca.approver_id != current_user.id:
        flash('该审批未指派给您', 'danger')
        return redirect(url_for('maintenance.change_detail', change_id=change.id))
    notes = request.form.get('notes', '').strip()
    ca.status = 'approved'
    ca.comment = notes
    ca.decided_at = datetime.utcnow()
    ca.decided_by = current_user.username
    ca.approver_id = current_user.id
    ca.approver_name = current_user.username
    recompute_change_approval(change)
    db.session.commit()
    log_audit('update', 'change_request', change.id,
              f"CAB审批通过(阶段{ca.stage} {ca.stage_name})", user_id=current_user.id)
    flash(f'阶段「{ca.stage_name}」审批通过', 'success')
    return redirect(url_for('maintenance.change_detail', change_id=change.id))


@maintenance_bp.route('/change/approval/<int:approval_id>/reject', methods=['POST'])
@login_required
@permission_required('change:cab:approve')
def reject_change_stage(approval_id):
    ca = ChangeApproval.query.get_or_404(approval_id)
    change = ca.change
    if change.status not in ['submitted', 'pending', 'review']:
        flash('当前变更状态不可审批', 'warning')
        return redirect(url_for('maintenance.change_detail', change_id=change.id))
    active = get_active_stage(change)
    if active is None or ca.stage != active:
        flash('当前不可审批该阶段', 'warning')
        return redirect(url_for('maintenance.change_detail', change_id=change.id))
    if ca.approver_id and ca.approver_id != current_user.id:
        flash('该审批未指派给您', 'danger')
        return redirect(url_for('maintenance.change_detail', change_id=change.id))
    notes = request.form.get('notes', '').strip()
    if not notes:
        flash('拒绝必须填写意见', 'danger')
        return redirect(url_for('maintenance.change_detail', change_id=change.id))
    ca.status = 'rejected'
    ca.comment = notes
    ca.decided_at = datetime.utcnow()
    ca.decided_by = current_user.username
    ca.approver_id = current_user.id
    ca.approver_name = current_user.username
    change.approval_notes = notes
    recompute_change_approval(change)
    db.session.commit()
    log_audit('update', 'change_request', change.id,
              f"CAB审批拒绝(阶段{ca.stage} {ca.stage_name})", user_id=current_user.id)
    flash(f'阶段「{ca.stage_name}」已拒绝，变更被驳回', 'danger')
    return redirect(url_for('maintenance.change_detail', change_id=change.id))


@maintenance_bp.route('/change/cab-config', methods=['GET', 'POST'])
@login_required
@permission_required('maintenance:edit')
def cab_config():
    cfg = CABConfig.query.filter_by(is_active=True).order_by(CABConfig.id).first()
    if request.method == 'POST':
        raw = request.form.get('stages_json')
        if raw:
            try:
                stages = json.loads(raw)
            except Exception as e:
                flash(f'JSON 解析失败: {e}', 'danger')
                return redirect(url_for('maintenance.cab_config'))
        else:
            stages = []
            i = 1
            while True:
                name = request.form.get(f'stage_name_{i}')
                if not name:
                    break
                approver_ids = [int(x) for x in request.form.getlist(f'approver_ids_{i}') if str(x).strip().isdigit()]
                mode = request.form.get(f'mode_{i}', 'all')
                stages.append({'name': name, 'approver_ids': approver_ids, 'mode': mode})
                i += 1
        if not stages:
            flash('至少需要配置一个审批阶段', 'warning')
            return redirect(url_for('maintenance.cab_config'))
        if cfg is None:
            cfg = CABConfig()
        cfg.name = request.form.get('name') or '默认CAB'
        cfg.description = request.form.get('description', '')
        cfg.set_stages(stages)
        cfg.is_active = True
        cfg.updated_by = current_user.username
        db.session.add(cfg)
        db.session.commit()
        flash('CAB 审批配置已保存', 'success')
        return redirect(url_for('maintenance.cab_config'))
    users = User.query.order_by(User.username).all()
    stages = cfg.get_stages() if cfg else [{'name': 'CAB评审', 'approver_ids': [], 'mode': 'any'}]
    return render_template('maintenance/cab_config.html', cfg=cfg, stages=stages, users=users)


@maintenance_bp.route('/change/<int:change_id>/conflicts')
@login_required
@permission_required('maintenance:view')
def change_conflicts(change_id):
    change = ChangeRequest.query.get_or_404(change_id)
    return jsonify({'conflicts': detect_change_conflicts(change)})
