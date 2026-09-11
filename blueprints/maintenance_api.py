# -*- coding: utf-8 -*-

"""Maintenance JSON API for large maintenance templates.



这些接口为 templates/maintenance/* 中较大的运维页面提供数据与操作能力。

路径统一挂在 /api/maintenance 下，页面模板中的 fetch() 可直接使用。

"""

from datetime import datetime

from flask import Blueprint, request, jsonify

from flask_login import login_required, current_user

from sqlalchemy import func



from extensions import db

from models.models import User, Device

from models.maintenance_models import (

    MaintenanceTask, SparePart, SparePartRequest, SparePartUsage, Supplier,

    WorkOrder, InspectionTask, InspectionTemplate, InspectionResult,

)

from utils.audit import log_audit

from utils.permission import permission_required



maintenance_api_bp = Blueprint('maintenance_api', __name__, url_prefix='/api/maintenance')





def _now():

    return datetime.utcnow()





def _parse_json():

    return request.get_json(silent=True) or request.form.to_dict()





def _user_name(user_id):

    if not user_id:

        return None

    user = User.query.get(user_id)

    return user.username if user else None





def _int_or_none(value):

    try:

        return int(value)

    except (TypeError, ValueError):

        return None





def _maintenance_task_dict(task):

    device_ids = task.device_ids or '[]'

    try:

        import json as _json

        if isinstance(device_ids, str):

            device_ids = _json.loads(device_ids)

    except Exception:

        device_ids = []

    return {

        'id': task.id,

        'name': task.name,

        'description': task.description,

        'maintenance_type': task.maintenance_type,

        'status': task.status,

        'priority': task.priority,

        'scheduled_date': task.scheduled_date.isoformat() if task.scheduled_date else None,

        'estimated_duration': task.estimated_duration,

        'actual_duration': task.actual_duration,

        'device_ids': device_ids,

        'device_count': len(device_ids) if isinstance(device_ids, list) else 0,

        'assigned_to': task.assigned_to,

        'assigned_to_user': {'name': _user_name(task.assigned_to)} if task.assigned_to else None,

        'approval_required': bool(task.approval_required),

        'approved_by': task.approved_by,

        'approved_at': task.approved_at.isoformat() if task.approved_at else None,

        'completed_by': task.completed_by,

        'completed_at': task.completed_at.isoformat() if task.completed_at else None,

        'notes': task.notes,

        'created_at': task.created_at.isoformat() if task.created_at else None,

    }





def _save_maintenance_task(task, data):

    task.name = data.get('name') or task.name

    task.description = data.get('description', task.description)

    task.maintenance_type = data.get('maintenance_type') or task.maintenance_type

    task.status = data.get('status') or task.status

    task.priority = data.get('priority', task.priority)

    if data.get('scheduled_date'):

        try:

            task.scheduled_date = datetime.fromisoformat(data['scheduled_date'])

        except Exception:

            pass

    if data.get('estimated_duration') not in (None, ''):

        try:

            task.estimated_duration = int(data.get('estimated_duration'))

        except Exception:

            pass

    if data.get('assigned_to') not in (None, ''):

        try:

            task.assigned_to = int(data.get('assigned_to'))

        except Exception:

            pass

    else:

        task.assigned_to = None

    if data.get('device_ids') is not None:

        import json as _json

        ids = data.get('device_ids')

        if isinstance(ids, list):

            task.device_ids = _json.dumps([int(i) for i in ids])

        elif isinstance(ids, str):

            try:

                task.device_ids = _json.dumps([int(i) for i in _json.loads(ids)])

            except Exception:

                task.device_ids = _json.dumps([i.strip() for i in ids.split(',') if i.strip()])

    task.approval_required = bool(data.get('approval_required')) if data.get('approval_required') not in (None, '') else task.approval_required

    task.notes = data.get('notes', task.notes)

    return task





# ---------- 通用下拉数据 ----------

@maintenance_api_bp.route('/tasks')

@maintenance_api_bp.route('/maintenance_tasks')

@login_required

@permission_required('maintenance:view')

def api_maintenance_tasks():

    tasks = MaintenanceTask.query.order_by(MaintenanceTask.scheduled_date.desc()).all()

    return jsonify({'success': True, 'tasks': [_maintenance_task_dict(t) for t in tasks]})





@maintenance_api_bp.route('/tasks', methods=['POST'])

@maintenance_api_bp.route('/maintenance_tasks', methods=['POST'])

@login_required

@permission_required('maintenance:edit')

def api_create_maintenance_task():

    data = _parse_json()

    if not data.get('name'):

        return jsonify({'success': False, 'error': '任务名称不能为空'}), 400

    task = MaintenanceTask(name=data['name'])

    _save_maintenance_task(task, data)

    task.created_by = current_user.id

    db.session.add(task)

    db.session.commit()

    log_audit('create', 'maintenance_task', task.id, f"创建维护任务: {task.name}",

              user_id=current_user.id)

    return jsonify({'success': True, 'id': task.id, 'task': _maintenance_task_dict(task)}), 201





@maintenance_api_bp.route('/tasks/<int:task_id>', methods=['GET'])

@maintenance_api_bp.route('/maintenance_tasks/<int:task_id>', methods=['GET'])

@login_required

@permission_required('maintenance:view')

def api_get_maintenance_task(task_id):

    task = MaintenanceTask.query.get_or_404(task_id)

    return jsonify({'success': True, 'task': _maintenance_task_dict(task)})





@maintenance_api_bp.route('/tasks/<int:task_id>', methods=['PUT'])

@maintenance_api_bp.route('/maintenance_tasks/<int:task_id>', methods=['PUT'])

@login_required

@permission_required('maintenance:edit')

def api_update_maintenance_task(task_id):

    task = MaintenanceTask.query.get_or_404(task_id)

    _save_maintenance_task(task, _parse_json())

    db.session.commit()

    log_audit('update', 'maintenance_task', task.id, f"更新维护任务: {task.name}",

              user_id=current_user.id)

    return jsonify({'success': True, 'task': _maintenance_task_dict(task)})





@maintenance_api_bp.route('/tasks/<int:task_id>', methods=['DELETE'])

@maintenance_api_bp.route('/maintenance_tasks/<int:task_id>', methods=['DELETE'])

@login_required

@permission_required('maintenance:edit')

def api_delete_maintenance_task(task_id):

    task = MaintenanceTask.query.get_or_404(task_id)

    name = task.name

    db.session.delete(task)

    db.session.commit()

    log_audit('delete', 'maintenance_task', task_id, f"删除维护任务: {name}",

              user_id=current_user.id)

    return jsonify({'success': True, 'message': '任务已删除'})





@maintenance_api_bp.route('/tasks/<int:task_id>/status', methods=['POST'])

@login_required

@permission_required('maintenance:edit')

def api_maintenance_task_status(task_id):

    task = MaintenanceTask.query.get_or_404(task_id)

    data = _parse_json()

    status = data.get('status')

    if status not in ('scheduled', 'in_progress', 'completed', 'cancelled'):

        return jsonify({'success': False, 'error': '无效状态'}), 400

    task.status = status

    if status == 'completed':

        task.completed_at = _now()

        task.completed_by = current_user.id

    db.session.commit()

    return jsonify({'success': True, 'task': _maintenance_task_dict(task)})





@maintenance_api_bp.route('/tasks/<int:task_id>/approve', methods=['POST'])

@login_required

@permission_required('maintenance:edit')

def api_maintenance_task_approve(task_id):

    task = MaintenanceTask.query.get_or_404(task_id)

    task.approved_by = current_user.id

    task.approved_at = _now()

    db.session.commit()

    return jsonify({'success': True, 'task': _maintenance_task_dict(task)})





@maintenance_api_bp.route('/tasks/<int:task_id>/start', methods=['POST'])

@login_required

@permission_required('maintenance:edit')

def api_maintenance_task_start(task_id):

    task = MaintenanceTask.query.get_or_404(task_id)

    task.status = 'in_progress'

    db.session.commit()

    return jsonify({'success': True, 'task': _maintenance_task_dict(task)})





@maintenance_api_bp.route('/tasks/<int:task_id>/complete', methods=['POST'])

@login_required

@permission_required('maintenance:edit')

def api_maintenance_task_complete(task_id):

    task = MaintenanceTask.query.get_or_404(task_id)

    task.status = 'completed'

    task.completed_at = _now()

    task.completed_by = current_user.id

    db.session.commit()

    return jsonify({'success': True, 'task': _maintenance_task_dict(task)})





# ---------- 备件 ----------

def _spare_part_dict(part):

    return {

        'id': part.id,

        'asset_number': part.asset_number,

        'part_number': part.asset_number,

        'name': part.part_name or part.model or part.asset_number,

        'part_name': part.part_name,

        'model': part.model,

        'vendor': part.manufacturer,

        'manufacturer': part.manufacturer,

        'category': part.part_type,

        'description': part.notes,

        'unit_price': float(part.unit_price or 0),

        'current_stock': int(part.current_stock or 0),

        'min_stock_level': int(part.min_stock_level or 0),

        'max_stock_level': int(part.max_stock_level or 0),

        'location': part.warehouse_location,

        'supplier_id': part.supplier_id,

        'supplier': {'id': part.supplier.id if part.supplier else None, 'name': part.supplier.name if part.supplier else (part.manufacturer or '-')},

        'installed_device_id': part.installed_device_id,

        'installed_device': {'hostname': part.installed_device.name if part.installed_device else None},

        'status': part.status,

        'is_active': bool(part.is_active),

    }





@maintenance_api_bp.route('/spare_parts')

@login_required

@permission_required('maintenance:view')

def api_spare_parts():

    parts = SparePart.query.order_by(SparePart.part_name.asc()).all()

    return jsonify({'success': True, 'parts': [_spare_part_dict(p) for p in parts]})





@maintenance_api_bp.route('/spare_parts', methods=['POST'])

@login_required

@permission_required('maintenance:edit')

def api_create_spare_part():

    data = _parse_json()

    if not data.get('name') and not data.get('part_number'):

        return jsonify({'success': False, 'error': '零件名称/编号不能为空'}), 400

    part = SparePart(

        asset_number=data.get('part_number') or data.get('asset_number'),

        part_name=data.get('name') or data.get('part_name'),

        part_type=data.get('category') or data.get('part_type'),

        manufacturer=data.get('vendor') or data.get('manufacturer'),

        model=data.get('model'),

        warehouse_location=data.get('location'),

        notes=data.get('description'),

        unit_price=data.get('unit_price'),

        current_stock=_int_or_none(data.get('current_stock')) or 0,

        min_stock_level=_int_or_none(data.get('min_stock_level')) or 0,

        max_stock_level=_int_or_none(data.get('max_stock_level')) or 0,

        supplier_id=_int_or_none(data.get('supplier_id')),

        installed_device_id=data.get('installed_device_id') or None,

        status='in_stock',

    )

    db.session.add(part)

    db.session.commit()

    log_audit('create', 'spare_part', part.id, f"创建备件: {part.part_name}",

              user_id=current_user.id)

    return jsonify({'success': True, 'id': part.id, 'part': _spare_part_dict(part)}), 201





@maintenance_api_bp.route('/spare_parts/<int:part_id>', methods=['GET'])

@login_required

@permission_required('maintenance:view')

def api_get_spare_part(part_id):

    part = SparePart.query.get_or_404(part_id)

    return jsonify({'success': True, 'part': _spare_part_dict(part)})





@maintenance_api_bp.route('/spare_parts/<int:part_id>', methods=['PUT'])

@login_required

@permission_required('maintenance:edit')

def api_update_spare_part(part_id):

    part = SparePart.query.get_or_404(part_id)

    data = _parse_json()

    if data.get('part_number'):

        part.asset_number = data['part_number']

    if data.get('name') or data.get('part_name'):

        part.part_name = data.get('name') or data.get('part_name')

    part.part_type = data.get('category', part.part_type)

    part.manufacturer = data.get('vendor', data.get('manufacturer', part.manufacturer))

    part.model = data.get('model', part.model)

    part.warehouse_location = data.get('location', part.warehouse_location)

    part.notes = data.get('description', part.notes)

    if data.get('unit_price') not in (None, ''):

        part.unit_price = data.get('unit_price')

    if data.get('current_stock') not in (None, ''):

        part.current_stock = _int_or_none(data.get('current_stock'))

    if data.get('min_stock_level') not in (None, ''):

        part.min_stock_level = _int_or_none(data.get('min_stock_level'))

    if data.get('max_stock_level') not in (None, ''):

        part.max_stock_level = _int_or_none(data.get('max_stock_level'))

    if data.get('supplier_id') not in (None, ''):

        part.supplier_id = _int_or_none(data.get('supplier_id'))

    if data.get('installed_device_id') not in (None, ''):

        part.installed_device_id = data.get('installed_device_id')

    if data.get('is_active') is not None:

        part.is_active = data.get('is_active') in (True, 'on', 'true', '1')

    db.session.commit()

    log_audit('update', 'spare_part', part.id, f"更新备件: {part.part_name}",

              user_id=current_user.id)

    return jsonify({'success': True, 'part': _spare_part_dict(part)})





@maintenance_api_bp.route('/spare_parts/<int:part_id>', methods=['DELETE'])

@login_required

@permission_required('maintenance:edit')

def api_delete_spare_part(part_id):

    part = SparePart.query.get_or_404(part_id)

    name = part.part_name

    db.session.delete(part)

    db.session.commit()

    log_audit('delete', 'spare_part', part_id, f"删除备件: {name}",

              user_id=current_user.id)

    return jsonify({'success': True, 'message': '备件已删除'})





@maintenance_api_bp.route('/spare_parts/<int:part_id>/stock', methods=['POST'])

@login_required

@permission_required('maintenance:edit')

def api_update_spare_part_stock(part_id):

    part = SparePart.query.get_or_404(part_id)

    data = _parse_json()

    delta = int(data.get('delta', 0))

    if delta:

        part.current_stock = max(0, int(part.current_stock or 0) + delta)

        db.session.commit()

    log_audit('update', 'spare_part', part.id,

              f"Stock adjustment: {part.part_name} delta={delta} current={part.current_stock}",

              user_id=current_user.id)

    return jsonify({'success': True, 'message': 'Stock adjustment persisted', 'part': _spare_part_dict(part)})





# ---------- 供应商 ----------

@maintenance_api_bp.route('/suppliers')

@login_required

@permission_required('maintenance:view')

def api_suppliers():

    suppliers = Supplier.query.filter_by(is_active=True).order_by(Supplier.name.asc()).all()

    return jsonify({'success': True, 'suppliers': [{

        'id': s.id, 'name': s.name, 'contact_person': s.contact_person,

        'email': s.email, 'phone': s.phone, 'address': s.address,

        'website': s.website, 'rating': s.rating, 'lead_time': s.lead_time,

        'payment_terms': s.payment_terms, 'notes': s.notes,

    } for s in suppliers]})





# ---------- 备件申请 ----------

def _spare_part_request_dict(r):

    return {

        'id': r.id,

        'request_number': r.request_number,

        'spare_part_id': r.spare_part_id,

        'part': {

            'name': r.spare_part.part_name if r.spare_part else '-',

            'part_number': r.spare_part.asset_number if r.spare_part else '-',

            'model': r.spare_part.model if r.spare_part else '',

            'unit_price': float(r.spare_part.unit_price or 0) if r.spare_part else 0,

            'current_stock': int(r.spare_part.current_stock or 0) if r.spare_part else 0, 'min_stock_level': int(r.spare_part.min_stock_level or 0) if r.spare_part else 0,

        },

        'quantity': r.quantity,

        'purpose': r.reason,

        'usage_description': r.usage_description,

        'requester_name': r.requester_name,

        'requested_by_user': {'name': r.requester_name},

        'department': r.department,

        'urgency': r.urgency,

        'status': r.status,

        'approval_status': r.approval_status,

        'approval_notes': r.approval_notes,

        'approved_by': r.approved_by,

        'approved_at': r.approved_at.isoformat() if r.approved_at else None,

        'issued_quantity': r.issued_quantity,

        'request_date': r.requested_at.isoformat() if r.requested_at else None,

        'notes': r.approval_notes or '',

        'device': None,

        'maintenance_task': None,

    }





@maintenance_api_bp.route('/spare_part_requests')

@login_required

@permission_required('maintenance:view')

def api_spare_part_requests():

    rows = SparePartRequest.query.order_by(SparePartRequest.requested_at.desc()).all()

    return jsonify({'success': True, 'requests': [_spare_part_request_dict(r) for r in rows]})





@maintenance_api_bp.route('/spare_part_requests', methods=['POST'])

@login_required

@permission_required('maintenance:edit')

def api_create_spare_part_request():

    data = _parse_json()

    if not data.get('part_id') or not data.get('quantity'):

        return jsonify({'success': False, 'error': '备件和数量不能为空'}), 400

    import uuid

    req = SparePartRequest(

        request_number=f'SPR{_now().strftime("%Y%m%d%H%M%S")}{uuid.uuid4().hex[:4].upper()}',

        spare_part_id=int(data.get('part_id')),

        quantity=int(data.get('quantity')),

        reason=data.get('purpose') or data.get('reason') or '',

        urgency=data.get('urgency') or 'medium',

        usage_description=data.get('notes') or '',

        requester_id=current_user.id,

        requester_name=current_user.username,

        department=getattr(current_user, 'department', None),

        status='pending',

        approval_status='pending',

    )

    db.session.add(req)

    db.session.commit()

    log_audit('create', 'spare_part_request', req.id, f"创建备件申请: {req.request_number}",

              user_id=current_user.id)

    return jsonify({'success': True, 'id': req.id, 'request': _spare_part_request_dict(req)}), 201





@maintenance_api_bp.route('/spare_part_requests/<int:req_id>', methods=['GET'])

@login_required

@permission_required('maintenance:view')

def api_get_spare_part_request(req_id):

    req = SparePartRequest.query.get_or_404(req_id)

    return jsonify({'success': True, 'request': _spare_part_request_dict(req)})





@maintenance_api_bp.route('/spare_part_requests/<int:req_id>', methods=['PUT'])

@login_required

@permission_required('maintenance:edit')

def api_update_spare_part_request(req_id):

    req = SparePartRequest.query.get_or_404(req_id)

    data = _parse_json()

    if data.get('part_id'):

        req.spare_part_id = int(data['part_id'])

    if data.get('quantity'):

        req.quantity = int(data['quantity'])

    if data.get('purpose'):

        req.reason = data['purpose']

    req.usage_description = data.get('notes', req.usage_description)

    req.urgency = data.get('urgency', req.urgency)

    db.session.commit()

    return jsonify({'success': True, 'request': _spare_part_request_dict(req)})





@maintenance_api_bp.route('/spare_part_requests/<int:req_id>', methods=['DELETE'])

@login_required

@permission_required('maintenance:edit')

def api_delete_spare_part_request(req_id):

    req = SparePartRequest.query.get_or_404(req_id)

    number = req.request_number

    db.session.delete(req)

    db.session.commit()

    log_audit('delete', 'spare_part_request', req_id, f"删除备件申请: {number}",

              user_id=current_user.id)

    return jsonify({'success': True, 'message': '申请已删除'})





@maintenance_api_bp.route('/spare_part_requests/<int:req_id>/action', methods=['POST'])

@login_required

@permission_required('maintenance:edit')

def api_spare_part_request_action(req_id):

    req = SparePartRequest.query.get_or_404(req_id)

    data = _parse_json()

    action = data.get('action')

    if action == 'approve':

        req.approval_status = 'approved'

        req.status = 'approved'

        req.approved_by = current_user.username

        req.approved_at = _now()

        req.approval_notes = data.get('notes', req.approval_notes)

    elif action == 'reject':

        req.approval_status = 'rejected'

        req.status = 'cancelled'

        req.approved_by = current_user.username

        req.approved_at = _now()

        req.approval_notes = data.get('notes', req.approval_notes)

    elif action == 'issue':

        req.status = 'issued'

        req.issued_by = current_user.username

        req.issued_at = _now()

        req.issued_quantity = req.quantity

    elif action == 'complete':

        req.status = 'completed'

    elif action == 'cancel':

        req.status = 'cancelled'

    else:

        return jsonify({'success': False, 'error': '无效操作'}), 400

    db.session.commit()

    return jsonify({'success': True, 'request': _spare_part_request_dict(req)})





# ---------- 巡检计划页 JSON API ----------

def _inspection_task_dict(task):

    items = []

    raw_items = task.checklist_items or (task.template.items if task.template else None)

    if raw_items:

        try:

            import json as _json

            parsed = _json.loads(raw_items)

            if isinstance(parsed, list):

                items = [{'name': (i.get('name') if isinstance(i, dict) else str(i))} for i in parsed]

        except Exception:

            items = [{'name': line} for line in str(raw_items).splitlines() if line.strip()]

    return {

        'id': task.id,

        'name': task.title,

        'title': task.title,

        'description': task.notes or '',

        'status': task.status,

        'priority': task.reminder_days or 0,

        'due_date': task.due_date.isoformat() if task.due_date else None,

        'scheduled_date': task.scheduled_date.isoformat() if task.scheduled_date else None,

        'assigned_to_name': task.assigned_to_name,

        'inspection_items': items,

        'completion_percentage': task.completion_percentage or 0,

    }





@maintenance_api_bp.route('/inspection_tasks')

@login_required

@permission_required('maintenance:view')

def api_inspection_tasks():

    rows = InspectionTask.query.order_by(InspectionTask.scheduled_date.asc()).all()

    return jsonify({'success': True, 'tasks': [_inspection_task_dict(t) for t in rows]})





@maintenance_api_bp.route('/inspection_tasks', methods=['POST'])

@login_required

@permission_required('maintenance:edit')

def api_create_inspection_task():

    data = _parse_json()

    if not data.get('name'):

        return jsonify({'success': False, 'error': '任务名称不能为空'}), 400

    import uuid

    task = InspectionTask(

        title=data['name'],

        notes=data.get('description', ''),

        inspection_type=data.get('inspection_type') or 'special',

        template_id=data.get('template_id') or None,

        device_id=data.get('device_id') or None,

        due_date=datetime.fromisoformat(data['due_date']).date() if data.get('due_date') else datetime.now().date(),

        scheduled_date=datetime.fromisoformat(data['scheduled_date']).date() if data.get('scheduled_date') else datetime.now().date(),

        status='pending',

        assigned_to_id=data.get('assigned_to') or None,

        created_by=current_user.username,

    )

    task.task_number = f"IT{datetime.now().strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:4].upper()}"

    db.session.add(task)

    db.session.commit()

    return jsonify({'success': True, 'id': task.id, 'task': _inspection_task_dict(task)}), 201





@maintenance_api_bp.route('/inspection_tasks/<int:task_id>')

@login_required

@permission_required('maintenance:view')

def api_get_inspection_task(task_id):

    task = InspectionTask.query.get_or_404(task_id)

    return jsonify(_inspection_task_dict(task))





@maintenance_api_bp.route('/inspection_tasks/<int:task_id>/status', methods=['PUT'])

@login_required

@permission_required('maintenance:edit')

def api_update_inspection_task_status(task_id):

    task = InspectionTask.query.get_or_404(task_id)

    status = (_parse_json() or {}).get('status')

    if status not in ('pending', 'in_progress', 'completed', 'cancelled', 'overdue'):

        return jsonify({'success': False, 'message': '无效状态'}), 400

    task.status = status

    if status == 'completed':

        task.completion_percentage = 100.0

    db.session.commit()

    return jsonify({'success': True, 'task': _inspection_task_dict(task)})





# ---------- 运维仪表盘统计 API ----------

@maintenance_api_bp.route('/dashboard_stats')

@login_required

@permission_required('maintenance:view')

def api_dashboard_stats():

    now = datetime.utcnow()

    open_wo = WorkOrder.query.filter(WorkOrder.status.in_(['open', 'assigned', 'in_progress'])).count()

    inspection_today = InspectionTask.query.filter(InspectionTask.scheduled_date == now.date()).count()

    maintenance_active = MaintenanceTask.query.filter(MaintenanceTask.status.in_(['scheduled', 'in_progress'])).count()

    return jsonify({'success': True, 'stats': {

        'open_work_orders': open_wo,

        'inspection_today': inspection_today,

        'active_maintenance_tasks': maintenance_active,

        'low_stock_parts': 0,

    }})





@maintenance_api_bp.route('/recent_activities')

@login_required

@permission_required('maintenance:view')

def api_recent_activities():

    recent = []

    for wo in WorkOrder.query.order_by(WorkOrder.updated_at.desc()).limit(5).all():

        recent.append({'title': wo.title, 'time': wo.updated_at.isoformat() if wo.updated_at else None, 'type': 'work_order'})

    return jsonify({'success': True, 'activities': recent})





@maintenance_api_bp.route('/upcoming_tasks')

@login_required

@permission_required('maintenance:view')

def api_upcoming_tasks():

    tasks = MaintenanceTask.query.filter(MaintenanceTask.status.in_(['scheduled', 'in_progress'])).order_by(MaintenanceTask.scheduled_date.asc()).limit(5).all()

    return jsonify({'success': True, 'tasks': [_maintenance_task_dict(t) for t in tasks]})





@maintenance_api_bp.route('/chart_data')

@login_required

@permission_required('maintenance:view')

def api_chart_data():

    statuses = db.session.query(MaintenanceTask.status, func.count(MaintenanceTask.id)).group_by(MaintenanceTask.status).all()

    return jsonify({'success': True, 'labels': [s or '未知' for s, _ in statuses], 'values': [c for _, c in statuses]})

