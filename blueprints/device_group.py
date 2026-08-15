from flask import Blueprint, request, jsonify, render_template, redirect, url_for, flash
from flask_login import login_required, current_user
from extensions import db
from models.device_group_models import DeviceGroup, device_group_members
from models.models import Device
from forms import DeviceGroupForm
from services.device_group_service import (
    classify_single_device, remove_device_from_group,
    auto_classify_by_ip_subnet, auto_classify_by_name_pattern,
    get_group_tree, get_all_groups_flat
)
from utils.permission import permission_required
from utils.audit import log_audit

device_group_bp = Blueprint('device_group', __name__, url_prefix='/device-groups')


def _get_parent_choices():
    """获取父级分组下拉选项"""
    groups = get_all_groups_flat()
    return [(0, '无（顶级分组）')] + [(g.id, g.name) for g in groups]


def _build_breadcrumb(group):
    """构建分组面包屑导航"""
    crumbs = []
    current = group
    while current:
        crumbs.insert(0, current)
        current = current.parent
    return crumbs


# ==================== 页面路由 ====================

@device_group_bp.route('/')
@login_required
@permission_required('device_group:view')
def list_view():
    """分组管理首页"""
    groups = get_all_groups_flat()
    tree = get_group_tree()
    ungrouped_count = Device.query.filter(
        ~Device.groups.any()
    ).count()
    total_grouped = sum(len(g.devices) if g.devices else 0 for g in groups)
    return render_template('device_group/list.html',
                           groups=groups,
                           tree=tree,
                           ungrouped_count=ungrouped_count,
                           total_grouped=total_grouped)


@device_group_bp.route('/add', methods=['GET', 'POST'])
@login_required
@permission_required('device_group:edit')
def add():
    """新增分组"""
    form = DeviceGroupForm()
    form.parent_id.choices = _get_parent_choices()

    if form.validate_on_submit():
        group = DeviceGroup(
            name=form.name.data,
            description=form.description.data,
            color=form.color.data or '#007bff',
            icon=form.icon.data or 'fa-folder',
            sort_order=form.sort_order.data or 0,
            parent_id=form.parent_id.data if form.parent_id.data and form.parent_id.data > 0 else None,
            auto_rule_type=form.auto_rule_type.data or None,
            auto_rule_value=form.auto_rule_value.data or None,
        )
        db.session.add(group)
        try:
            db.session.commit()
            log_audit('create', 'device_group', group.id,
                      f"创建设备分组: {group.name}",
                      user_id=current_user.id if current_user.is_authenticated else None)
            flash(f'分组 "{group.name}" 创建成功', 'success')
            return redirect(url_for('device_group.list_view'))
        except Exception as e:
            db.session.rollback()
            flash(f'创建失败: {str(e)}', 'danger')
    return render_template('device_group/form.html', form=form, title='新增分组')


@device_group_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@permission_required('device_group:edit')
def edit(id):
    """编辑分组"""
    group = DeviceGroup.query.get_or_404(id)
    form = DeviceGroupForm(obj=group)
    form.parent_id.choices = _get_parent_choices()
    # 不能选择自己作为父级
    valid_choices = [(v, l) for v, l in form.parent_id.choices if v != group.id]
    form.parent_id.choices = valid_choices

    if form.validate_on_submit():
        group.name = form.name.data
        group.description = form.description.data
        group.color = form.color.data
        group.icon = form.icon.data
        group.sort_order = form.sort_order.data or 0
        group.parent_id = form.parent_id.data if form.parent_id.data and form.parent_id.data > 0 else None
        group.auto_rule_type = form.auto_rule_type.data or None
        group.auto_rule_value = form.auto_rule_value.data or None
        try:
            db.session.commit()
            log_audit('update', 'device_group', group.id,
                      f"编辑设备分组: {group.name}",
                      user_id=current_user.id if current_user.is_authenticated else None)
            flash(f'分组 "{group.name}" 更新成功', 'success')
            return redirect(url_for('device_group.list_view'))
        except Exception as e:
            db.session.rollback()
            flash(f'更新失败: {str(e)}', 'danger')

    return render_template('device_group/form.html', form=form, title='编辑分组', group=group)


@device_group_bp.route('/<int:id>/delete', methods=['POST'])
@login_required
@permission_required('device_group:edit')
def delete(id):
    """删除分组"""
    group = DeviceGroup.query.get_or_404(id)
    name = group.name
    try:
        # 将子分组的 parent_id 置空
        DeviceGroup.query.filter_by(parent_id=id).update({'parent_id': None})
        db.session.delete(group)
        db.session.commit()
        log_audit('delete', 'device_group', id,
                  f"删除设备分组: {name}",
                  user_id=current_user.id if current_user.is_authenticated else None)
        flash(f'分组 "{name}" 已删除', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'删除失败: {str(e)}', 'danger')
    return redirect(url_for('device_group.list_view'))


@device_group_bp.route('/<int:id>')
@login_required
@permission_required('device_group:view')
def detail(id):
    """分组详情"""
    group = DeviceGroup.query.get_or_404(id)
    breadcrumb = _build_breadcrumb(group)
    devices = group.devices if group.devices else []
    # 获取未分组的设备（用于添加）
    ungrouped_devices = Device.query.filter(~Device.groups.any()).order_by(Device.name).all()
    return render_template('device_group/detail.html',
                           group=group,
                           breadcrumb=breadcrumb,
                           devices=devices,
                           ungrouped_devices=ungrouped_devices)


# ==================== API 路由 ====================

@device_group_bp.route('/api/list')
@login_required
@permission_required('device_group:view')
def api_list():
    """JSON: 返回树形分组列表"""
    tree = get_group_tree()
    return jsonify({'success': True, 'tree': tree})


@device_group_bp.route('/api/<int:id>/devices')
@login_required
@permission_required('device_group:view')
def api_group_devices(id):
    """JSON: 返回分组内的设备列表"""
    group = DeviceGroup.query.get_or_404(id)
    devices = []
    for d in (group.devices or []):
        devices.append({
            'id': d.id,
            'name': d.name,
            'management_ip': d.management_ip or '',
            'device_type': d.device_type or '',
            'model': d.model or '',
            'status': d.status or '',
            'brand': d.brand or '',
        })
    return jsonify({'success': True, 'devices': devices, 'count': len(devices)})


@device_group_bp.route('/api/assign', methods=['POST'])
@login_required
@permission_required('device_group:edit')
def api_assign():
    """JSON: 批量分配设备到分组"""
    data = request.get_json()
    device_ids = data.get('device_ids', [])
    group_id = data.get('group_id')
    action = data.get('action', 'assign')  # assign or remove

    if not group_id or not device_ids:
        return jsonify({'success': False, 'message': '参数不完整'})

    group = DeviceGroup.query.get(group_id)
    if not group:
        return jsonify({'success': False, 'message': '分组不存在'})

    count = 0
    for did in device_ids:
        try:
            if action == 'assign':
                if classify_single_device(did, group_id):
                    count += 1
            else:
                remove_device_from_group(did, group_id)
                count += 1
        except Exception:
            pass

    action_label = '分配到' if action == 'assign' else '移出'
    log_audit('assign', 'device_group', group_id,
              f"批量{action_label}分组 {group.name}: {count} 台设备",
              user_id=current_user.id if current_user.is_authenticated else None)

    return jsonify({'success': True, 'message': f'成功{action_label} {count} 台设备', 'count': count})


@device_group_bp.route('/api/auto-classify', methods=['POST'])
@login_required
@permission_required('device_group:edit')
def api_auto_classify():
    """JSON: 执行自动归类"""
    data = request.get_json() or {}
    rule_type = data.get('rule_type', 'ip_subnet')  # ip_subnet or name_pattern

    try:
        if rule_type == 'ip_subnet':
            result = auto_classify_by_ip_subnet()
            msg = f"按IP网段归类完成: 新建 {result['created']} 个分组, 归类 {result['assigned']} 台设备"
        elif rule_type == 'name_pattern':
            result = auto_classify_by_name_pattern()
            msg = f"按名称匹配归类完成: 匹配 {result['matched_groups']} 个分组, 归类 {result['assigned']} 台设备"
        else:
            return jsonify({'success': False, 'message': '未知的归类类型'})

        log_audit('auto_classify', 'device_group', 0, msg,
                  user_id=current_user.id if current_user.is_authenticated else None)
        return jsonify({'success': True, 'message': msg, 'result': result})
    except Exception as e:
        return jsonify({'success': False, 'message': f'自动归类失败: {str(e)}'})


@device_group_bp.route('/api/ungrouped-devices')
@login_required
@permission_required('device_group:view')
def api_ungrouped_devices():
    """JSON: 返回未分组的设备列表"""
    devices = Device.query.filter(~Device.groups.any()).order_by(Device.name).all()
    result = [{
        'id': d.id,
        'name': d.name,
        'management_ip': d.management_ip or '',
        'device_type': d.device_type or '',
        'status': d.status or '',
    } for d in devices]
    return jsonify({'success': True, 'devices': result, 'count': len(result)})
