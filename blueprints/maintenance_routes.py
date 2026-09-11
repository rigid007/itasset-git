# blueprints/maintenance.py - 运维管理蓝图

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, make_response

from flask_login import login_required, current_user

from models.maintenance_models  import  InspectionTask, InspectionTemplate, InspectionResult, WorkOrder, ChangeRequest,WorkOrderTemplate, ChangeAffectedDevice, ChangeApproval, CABConfig, MaintenanceTask, SparePart, SparePartRequest, SparePartUsage, Supplier

from forms import InspectionTemplateForm, DailyInspectionTemplateForm, WorkOrderForm, ChangeRequestForm,InspectionTaskForm

from datetime import datetime, timedelta

import json
import uuid

from types import SimpleNamespace

from sqlalchemy import func

from extensions import db

from models.models import User, Device

from utils.audit import log_audit

from utils.permission import permission_required

maintenance_bp = Blueprint('maintenance', __name__, url_prefix='/maintenance')

# 添加上下文处理器，为所有模板提供 pending_inspections 变量

@maintenance_bp.context_processor

def inject_inspection_counts():

    """为模板注入巡检相关计数"""

    if current_user.is_authenticated:

        # 计算待处理的巡检任务

        pending_inspections = InspectionTask.query.filter_by(

            status='pending'

        ).count()

        # 计算活跃的维护任务

        active_maintenance = InspectionTask.query.filter(

            InspectionTask.status.in_(['in_progress', 'scheduled'])

        ).count()

        # 计算未完成的工单

        open_work_orders = WorkOrder.query.filter_by(

            status='open'

        ).count()

        return {

            'pending_inspections': pending_inspections,

            'active_maintenance': active_maintenance,

            'open_work_orders': open_work_orders

        }

    return {}

def _parse_inspection_items(raw):

    """把巡检模板/任务里的检查项字符串解析为可渲染的项目列表。"""

    if not raw:

        return []

    try:

        data = json.loads(raw)

    except Exception:

        return [{'name': line.strip(), 'standard': ''} for line in str(raw).splitlines() if line.strip()]

    if isinstance(data, dict):

        data = data.get('items') or data.get('checklist') or []

    if not isinstance(data, list):

        return [{'name': str(data), 'standard': ''}]

    items = []

    for i, item in enumerate(data):

        if isinstance(item, str):

            items.append({'name': item, 'standard': '', 'result': '', 'remark': ''})

        elif isinstance(item, dict):

            items.append({

                'name': item.get('name') or item.get('item') or item.get('title') or f'检查项{i+1}',

                'standard': item.get('standard') or item.get('requirement') or '',

                'result': item.get('result') or '',

                'remark': item.get('remark') or item.get('note') or '',

            })

        else:

            items.append({'name': str(item), 'standard': '', 'result': '', 'remark': ''})

    return items

def _inspection_items_for_task(task):

    raw = task.checklist_items or (task.template.items if task.template else None)

    return _parse_inspection_items(raw)

@maintenance_bp.route('/inspection/tasks')

@login_required

@permission_required('maintenance:view')

def inspection_tasks():

    """巡检任务"""

    status_filter = request.args.get('status', 'all')

    query = InspectionTask.query

    if status_filter != 'all':

        query = query.filter_by(status=status_filter)

    page = request.args.get('page', 1, type=int)

    pagination = query.order_by(InspectionTask.scheduled_date.asc(), InspectionTask.id.desc()).paginate(

        page=page, per_page=20, error_out=False

    )

    tasks = pagination.items

    # 自动将已过期的待处理/进行中任务标记为逾期

    today = datetime.now().date()

    changed_overdue = False

    for task in tasks:

        effective_due = task.due_date or task.scheduled_date

        if task.status in ('pending', 'in_progress') and effective_due and effective_due < today:

            task.status = 'overdue'

            task.updated_at = datetime.utcnow()

            changed_overdue = True

    if changed_overdue:

        db.session.commit()

    # 统计信息

    total_tasks = InspectionTask.query.count()

    pending_tasks = InspectionTask.query.filter_by(status='pending').count()

    in_progress_tasks = InspectionTask.query.filter_by(status='in_progress').count()

    completed_tasks = InspectionTask.query.filter_by(status='completed').count()

    return render_template('maintenance/inspection_tasks.html',

                         tasks=tasks,

                         status_filter=status_filter,

                         total_tasks=total_tasks,

                         pending_tasks=pending_tasks,

                         in_progress_tasks=in_progress_tasks,

                         completed_tasks=completed_tasks,

                         pagination=pagination)

@maintenance_bp.route('/daily_inspection/template', methods=['GET', 'POST'])

@login_required

@permission_required('maintenance:edit')

def daily_inspection_template():

    """日巡检模板"""

    form = DailyInspectionTemplateForm()

    if form.validate_on_submit():

        # 检查模板名称是否已存在

        existing_template = InspectionTemplate.query.filter_by(

            name=form.name.data,

            template_type='daily'

        ).first()

        if existing_template:

            flash('日巡检模板名称已存在！', 'danger')

            return render_template('maintenance/daily_inspection_template.html', form=form)

        template = InspectionTemplate(

            name=form.name.data,

            template_type='daily',

            description=form.description.data,

            items=form.items.data,

            created_by=current_user.username,

            is_active=True

        )

        try:

            db.session.add(template)

            db.session.commit()

            log_audit('create', 'inspection_template', template.id, f"创建日巡检模板: {template.name}", user_id=current_user.id if current_user.is_authenticated else None)

            flash('日巡检模板创建成功！', 'success')

            return redirect(url_for('maintenance.inspection_templates'))

        except Exception as e:

            db.session.rollback()

            flash(f'创建失败: {str(e)}', 'danger')

    return render_template('maintenance/daily_inspection_template.html', form=form)

@maintenance_bp.route('/inspection/templates', methods=['GET'])

@login_required

@permission_required('maintenance:view')

def inspection_templates():

    templates = InspectionTemplate.query.filter_by(is_active=True).order_by(

        InspectionTemplate.template_type,

        InspectionTemplate.name

    ).all()

    templates_by_type = {}

    for template in templates:

        if template.template_type not in templates_by_type:

            templates_by_type[template.template_type] = []

        templates_by_type[template.template_type].append(template)

    return render_template('maintenance/inspection_templates.html',

                           templates=templates,          # 新增这一行

                           templates_by_type=templates_by_type)

#

@maintenance_bp.route('/inspection/templates', methods=['POST'])

@login_required

@permission_required('maintenance:edit')

def create_template():

    """创建新的巡检模板"""

    if not request.is_json:

        return jsonify({'success': False, 'error': '请求必须为 JSON 格式'}), 415

    data = request.get_json()

    try:

        # 1. 获取前端发送的 JSON 数据

        data = request.get_json()

        if not data:

            return jsonify({'success': False, 'error': '请求数据格式错误，需要 JSON'}), 400

        # 2. 必填字段验证

        required_fields = ['name', 'template_type', 'items']

        for field in required_fields:

            if field not in data or not data[field]:

                return jsonify({'success': False, 'error': f'缺少必填字段: {field}'}), 400

        # 检查模板名称是否已存在

        existing = InspectionTemplate.query.filter_by(name=data['name']).first()

        if existing:

            return jsonify({'success': False, 'error': f'模板名称 "{data["name"]}" 已存在'}), 400

        # 3. 处理 items 字段：确保存储为字符串

        items_data = data['items']

        if isinstance(items_data, (list, dict)):

            # 如果前端发送的是数组或对象，转换为 JSON 字符串

            items_str = json.dumps(items_data, ensure_ascii=False)

        else:

            # 否则按原字符串存储（可能是纯文本）

            items_str = str(items_data)

        # 4. 创建模板实例

        new_template = InspectionTemplate(

            name=data['name'].strip(),

            description=data.get('description', ''),

            template_type=data['template_type'],

            category=data.get('category', ''),

            applicable_to=data.get('applicable_to', ''),

            device_type=data.get('device_type', ''),

            items=items_str,

            standards=data.get('standards', ''),

            pass_criteria=data.get('pass_criteria', ''),

            estimated_time_minutes=data.get('estimated_time_minutes', 30),

            frequency_days=data.get('frequency_days'),

            reminder_days=data.get('reminder_days', 1),

            is_active=data.get('is_active', True),

            is_default=data.get('is_default', False),

            created_by=current_user.username if current_user.is_authenticated else 'system',

            updated_by=current_user.username if current_user.is_authenticated else 'system'

        )

        # 5. 计算项目数量

        new_template.update_item_count()

        # 6. 保存到数据库

        db.session.add(new_template)

        db.session.commit()

        log_audit('create', 'inspection_template', new_template.id, f"创建巡检模板: {new_template.name}", user_id=current_user.id if current_user.is_authenticated else None)

        # 7. 返回成功响应（包含新模板 ID）

        return jsonify({

            'success': True,

            'id': new_template.id,

            'message': '模板创建成功'

        }), 201

    except Exception as e:

        # 发生任何异常时，回滚数据库并返回 JSON 错误

        db.session.rollback()

        # 在开发环境中可以记录详细日志

        # current_app.logger.error(f"创建模板失败: {str(e)}", exc_info=True)

        return jsonify({

            'success': False,

            'error': f'创建模板失败: {str(e)}'

        }), 500

@maintenance_bp.route('/inspection/schedule')

@login_required

@permission_required('maintenance:view')

def inspection_schedule():

    """巡检计划"""

    # 获取当前时间（用于模板显示）

    now = datetime.now()  # 添加这一行

    # 获取时间范围

    time_range = request.args.get('range', 'month')

    today = datetime.now().date()

    if time_range == 'week':

        start_date = today - timedelta(days=7)

        end_date = today + timedelta(days=30)

    elif time_range == 'month':

        start_date = today - timedelta(days=30)

        end_date = today + timedelta(days=90)

    else:  # year

        start_date = today - timedelta(days=365)

        end_date = today + timedelta(days=365)

    # 获取巡检任务

    scheduled_tasks = InspectionTask.query.filter(

        InspectionTask.scheduled_date.between(start_date, end_date)

    ).order_by(InspectionTask.scheduled_date).all()

    # 按日期分组

    tasks_by_date = {}

    for task in scheduled_tasks:

        date_str = task.scheduled_date.strftime('%Y-%m-%d')

        if date_str not in tasks_by_date:

            tasks_by_date[date_str] = []

        tasks_by_date[date_str].append(task)

    date_list = []

    delta = end_date - start_date

    for i in range(delta.days + 1):

        date = start_date + timedelta(days=i)

        date_list.append(date)

    return render_template('maintenance/inspection_schedule.html',

                         tasks_by_date=tasks_by_date,

                         start_date=start_date,

                         end_date=end_date,

                         time_range=time_range,

                         now=now,

                         today=today, # 添加 now 到上下文中

                         date_list=date_list)  # 新增

@maintenance_bp.route('/inspection/results')

@login_required

@permission_required('maintenance:view')

def inspection_results():

    """巡检结果"""

    page = request.args.get('page', 1, type=int)

    per_page = 20

    # 获取过滤条件

    start_date = request.args.get('start_date')

    end_date = request.args.get('end_date')

    inspector = request.args.get('inspector')

    result_filter = request.args.get('result', 'all')

    query = InspectionResult.query

    if start_date:

        query = query.filter(InspectionResult.inspection_date >= start_date)

    if end_date:

        query = query.filter(InspectionResult.inspection_date <= end_date)

    if inspector:

        query = query.filter(InspectionResult.inspector_name.ilike(f'%{inspector}%'))

    if result_filter != 'all':

        query = query.filter_by(overall_result=result_filter)

    results = query.order_by(InspectionResult.inspection_date.desc()).paginate(

        page=page, per_page=per_page, error_out=False

    )

    # 统计信息

    total_inspections = InspectionResult.query.count()

    passed_inspections = InspectionResult.query.filter_by(overall_result='passed').count()

    failed_inspections = InspectionResult.query.filter_by(overall_result='failed').count()

    warning_inspections = InspectionResult.query.filter_by(overall_result='warning').count()

    return render_template('maintenance/inspection_results.html',

                         results=results,

                         total_inspections=total_inspections,

                         passed_inspections=passed_inspections,

                         failed_inspections=failed_inspections,

                         warning_inspections=warning_inspections,

                         start_date=start_date,

                         end_date=end_date,

                         inspector=inspector,

                         result_filter=result_filter)

@maintenance_bp.route('/inspection/results/<int:result_id>')

@login_required

@permission_required('maintenance:view')

def inspection_result_detail(result_id):

    """巡检结果详情。"""

    result = InspectionResult.query.get_or_404(result_id)

    task = InspectionTask.query.get(result.task_id)

    checklist = []

    if result.checklist_results:

        try:

            checklist = json.loads(result.checklist_results)

        except Exception:

            checklist = []

    return render_template('maintenance/inspection_result_detail.html',

                           result=result, task=task, checklist=checklist)

@maintenance_bp.route('/inspection/results/<int:result_id>/export')

@login_required

@permission_required('maintenance:view')

def export_inspection_result(result_id):

    """导出巡检结果为 JSON 文件，便于归档或接入自动化。"""

    result = InspectionResult.query.get_or_404(result_id)

    task = InspectionTask.query.get(result.task_id)

    payload = {

        'result_number': result.result_number,

        'inspection_date': result.inspection_date.isoformat() if result.inspection_date else None,

        'inspection_time': result.inspection_time,

        'inspector_name': result.inspector_name,

        'overall_result': result.overall_result,

        'score': result.score,

        'total_items': result.total_items,

        'passed_items': result.passed_items,

        'failed_items': result.failed_items,

        'warning_items': result.warning_items,

        'skipped_items': result.skipped_items,

        'issues_found': result.issues_found or '',

        'recommendations': result.recommendations or '',

        'actions_taken': result.actions_taken or '',

        'follow_up_actions': result.follow_up_actions or '',

        'task': {

            'task_number': task.task_number if task else None,

            'title': task.title if task else None,

        },

    }

    response = make_response(json.dumps(payload, ensure_ascii=False, indent=2))

    response.mimetype = 'application/json'

    response.headers['Content-Disposition'] = f"attachment; filename=inspection_{result.result_number}.json"

    return response

@maintenance_bp.route('/work_order/create', methods=['GET', 'POST'])

@login_required

@permission_required('maintenance:edit')

def create_work_order():

    form = WorkOrderForm()

    template = None

    if request.method == 'GET':

        template_id = request.args.get('template_id', type=int)

        if template_id:

            template = WorkOrderTemplate.query.get(template_id)

            if template:

                form.title.data = template.name

                form.description.data = template.description or template.content or ''

                form.category.data = template.category or form.category.default

                form.priority.data = template.default_priority or form.priority.default

                if template.default_assignee:

                    form.assigned_to.data = template.default_assignee

    # 为指派工程师下拉框注入用户选项

    users = User.query.order_by(User.username).all()

    form.assigned_to.choices = [(0, '未指派')] + [(u.id, u.username) for u in users]

    if form.validate_on_submit():

        # 处理指派用户（form.assigned_to 返回用户ID）

        assigned_to_id = form.assigned_to.data if form.assigned_to.data and form.assigned_to.data != 0 else None

        assigned_user = User.query.get(assigned_to_id) if assigned_to_id else None

        # 创建工单实例（注意：使用外键字段 assigned_to_id，而不是关系字段 assigned_to）

        work_order = WorkOrder(

            title=form.title.data,

            description=form.description.data,

            priority=form.priority.data,

            category=form.category.data,

            # 指派信息

            assigned_to_id=assigned_to_id,

            assigned_to_name=assigned_user.username if assigned_user else None,

            # 请求人信息

            requester_id=current_user.id,

            requester_name=current_user.username,

            requester_department=current_user.department,   # 如有

            requester_contact=current_user.email,           # 如有

            # 工单类型（必填）

            work_order_type=form.category.data,              # 或根据业务逻辑映射

            # 状态与时间

            status='open',

            is_major=form.is_major.data,

            requested_at=datetime.utcnow(),

            due_date=form.deadline.data,                     # ✅ 关键修改：使用 due_date

            created_by=current_user.username,

        )

        # 生成工单编号（必须）

        work_order.generate_work_order_number()

        work_order.apply_sla_policy()

        try:

            db.session.add(work_order)

            db.session.commit()

            log_audit('create', 'work_order', work_order.id, f"创建工单: {work_order.title}", user_id=current_user.id if current_user.is_authenticated else None)

            flash('工单创建成功！', 'success')

            return redirect(url_for('maintenance.work_order_list'))

        except Exception as e:

            db.session.rollback()

            flash(f'创建失败: {str(e)}', 'danger')

    return render_template('maintenance/create_work_order.html', form=form, template=template)

@maintenance_bp.route('/work_order/templates')

@login_required

@permission_required('maintenance:view')

def work_order_templates():

    """工单模板"""

    templates = WorkOrderTemplate.query.filter_by(is_active=True).all()

    users = User.query.order_by(User.username).all()

    users_by_id = {u.id: u.username for u in users}

    return render_template('maintenance/work_order_templates.html',

                           templates=templates, users=users,

                           users_by_id=users_by_id)

@maintenance_bp.route('/work_order/templates/create', methods=['POST'])

@login_required

@permission_required('maintenance:edit')

def create_work_order_template():

    """创建工单模板。"""

    name = request.form.get('name', '').strip()

    if not name:

        flash('模板名称不能为空', 'danger')

        return redirect(url_for('maintenance.work_order_templates'))

    template = WorkOrderTemplate(

        name=name,

        description=request.form.get('description', '').strip(),

        category=request.form.get('category', '').strip(),

        subcategory=request.form.get('subcategory', '').strip(),

        content=request.form.get('content', '').strip(),

        default_priority=request.form.get('default_priority', 'medium'),

        default_assignee=request.form.get('default_assignee', type=int) or None,

        is_active=request.form.get('is_active') == 'on',

        created_by=current_user.id,

    )

    db.session.add(template)

    db.session.commit()

    log_audit('create', 'work_order_template', template.id,

              f"创建工单模板: {template.name}",

              user_id=current_user.id if current_user.is_authenticated else None)

    flash(f'工单模板「{template.name}」已创建', 'success')

    return redirect(url_for('maintenance.work_order_templates'))

@maintenance_bp.route('/work_order/templates/<int:template_id>/edit', methods=['POST'])

@login_required

@permission_required('maintenance:edit')

def edit_work_order_template(template_id):

    """编辑工单模板。"""

    template = WorkOrderTemplate.query.get_or_404(template_id)

    name = request.form.get('name', '').strip()

    if not name:

        flash('模板名称不能为空', 'danger')

        return redirect(url_for('maintenance.work_order_templates'))

    template.name = name

    template.description = request.form.get('description', '').strip()

    template.category = request.form.get('category', '').strip()

    template.subcategory = request.form.get('subcategory', '').strip()

    template.content = request.form.get('content', '').strip()

    template.default_priority = request.form.get('default_priority', 'medium')

    template.default_assignee = request.form.get('default_assignee', type=int) or None

    template.is_active = request.form.get('is_active') == 'on'

    db.session.commit()

    log_audit('update', 'work_order_template', template.id,

              f"编辑工单模板: {template.name}",

              user_id=current_user.id if current_user.is_authenticated else None)

    flash(f'工单模板「{template.name}」已更新', 'success')

    return redirect(url_for('maintenance.work_order_templates'))

@maintenance_bp.route('/work_order/templates/<int:template_id>/delete', methods=['POST'])

@login_required

@permission_required('maintenance:edit')

def delete_work_order_template(template_id):

    """删除工单模板（软删除）。"""

    template = WorkOrderTemplate.query.get_or_404(template_id)

    template.is_active = False

    db.session.commit()

    log_audit('delete', 'work_order_template', template.id,

              f"停用工单模板: {template.name}",

              user_id=current_user.id if current_user.is_authenticated else None)

    flash(f'工单模板「{template.name}」已停用', 'success')

    return redirect(url_for('maintenance.work_order_templates'))

@maintenance_bp.route('/work_order/templates/<int:template_id>/use')

@login_required

@permission_required('maintenance:edit')

def use_template(template_id):

    """使用模板创建工单。"""

    WorkOrderTemplate.query.get_or_404(template_id)

    return redirect(url_for('maintenance.create_work_order', template_id=template_id))

@maintenance_bp.route('/work_order/categories')

@login_required

@permission_required('maintenance:view')

def work_order_categories():

    """工单分类"""

    categories = db.session.query(

        WorkOrder.category,

        func.count(WorkOrder.id).label('count'),

        func.avg(WorkOrder.resolution_time).label('avg_resolution_time')

    ).group_by(WorkOrder.category).all()

    return render_template('maintenance/work_order_categories.html', categories=categories)

@maintenance_bp.route('/change/requests')

@login_required

@permission_required('maintenance:view')

def change_requests():

    """变更请求"""

    status_filter = request.args.get('status', 'all')

    query = ChangeRequest.query

    if status_filter != 'all':

        query = query.filter_by(status=status_filter)

    # 修改为按 created_at 排序（或您期望的其他日期字段）

    change_requests = query.order_by(ChangeRequest.created_at.desc()).all()

    # 统计信息保持不变

    total_requests = ChangeRequest.query.count()

    pending_requests = ChangeRequest.query.filter_by(status='pending').count()

    approved_requests = ChangeRequest.query.filter_by(status='approved').count()

    rejected_requests = ChangeRequest.query.filter_by(status='rejected').count()

    return render_template('maintenance/change_requests.html',

                         change_requests=change_requests,

                         status_filter=status_filter,

                         total_requests=total_requests,

                         pending_requests=pending_requests,

                         approved_requests=approved_requests,

                         rejected_requests=rejected_requests)

@maintenance_bp.route('/change/calendar')

@login_required

@permission_required('maintenance:view')

def change_calendar():

    """变更日历"""

    # 获取时间范围

    time_range = request.args.get('range', 'month')

    today = datetime.now().date()

    if time_range == 'week':

        start_date = today - timedelta(days=7)

        end_date = today + timedelta(days=30)

    elif time_range == 'month':

        start_date = today - timedelta(days=30)

        end_date = today + timedelta(days=90)

    else:  # year

        start_date = today - timedelta(days=365)

        end_date = today + timedelta(days=365)

    # 获取变更请求

    scheduled_changes = ChangeRequest.query.filter(

        ChangeRequest.scheduled_date.between(start_date, end_date),

        ChangeRequest.status.in_(['approved', 'scheduled'])

    ).order_by(ChangeRequest.scheduled_date).all()

    # 按日期分组

    changes_by_date = {}

    for change in scheduled_changes:

        date_str = change.scheduled_date.strftime('%Y-%m-%d')

        if date_str not in changes_by_date:

            changes_by_date[date_str] = []

        changes_by_date[date_str].append(change)

    return render_template('maintenance/change_calendar.html',

                         changes_by_date=changes_by_date,

                         start_date=start_date,

                         end_date=end_date,

                         time_range=time_range)

@maintenance_bp.route('/change/approval')

@login_required

@permission_required('maintenance:view')

def change_approval():

    # 查询状态为 submitted 或 pending 的变更（根据您的实际状态定义调整）

    pending_approvals = ChangeRequest.query.filter(

        ChangeRequest.status.in_(['submitted', 'pending'])

    ).order_by(ChangeRequest.created_at).all()

    return render_template('maintenance/change_approval.html', approvals=pending_approvals)

@maintenance_bp.route('/inspection/tasks/create', methods=['GET', 'POST'])

@login_required

@permission_required('maintenance:edit')

def create_inspection_task():

    """新建巡检任务"""

    form = InspectionTaskForm()

    if form.validate_on_submit():

        # 创建任务实例

        task = InspectionTask()

        task.title = form.title.data

        task.inspection_type = form.inspection_type.data

        task.template_id = form.template_id.data if form.template_id.data != 0 else None

        task.device_id = form.device_id.data if form.device_id.data != 0 else None

        task.location_id = form.location_id.data if form.location_id.data != 0 else None

        task.cabinet_id = form.cabinet_id.data if form.cabinet_id.data != 0 else None

        task.scheduled_date = form.scheduled_date.data

        task.scheduled_time = form.scheduled_time.data.strftime('%H:%M') if form.scheduled_time.data else None

        task.due_date = form.due_date.data

        task.assigned_to_id = form.assigned_to_id.data if form.assigned_to_id.data != 0 else None

        # 设置负责人姓名（方便显示，可根据assigned_to_id自动填充）

        if task.assigned_to_id:

            user = User.query.get(task.assigned_to_id)

            task.assigned_to_name = user.username if user else None

        task.team_members = form.team_members.data

        task.reminder_days = form.reminder_days.data

        task.notes = form.notes.data

        # 默认值

        task.status = 'pending'

        task.completion_percentage = 0.0

        task.reminder_sent = False

        # 生成任务编号

        task.generate_task_number()

        # 记录创建人

        task.created_by = current_user.username if current_user.is_authenticated else 'system'

        db.session.add(task)

        db.session.commit()

        log_audit('create', 'inspection_task', task.id, f"创建巡检任务: {task.title}", user_id=current_user.id if current_user.is_authenticated else None)

        flash('巡检任务创建成功！', 'success')

        return redirect(url_for('maintenance.inspection_tasks'))

    # GET 请求或验证失败时渲染表单

    return render_template('maintenance/create_inspection_task.html', form=form)

#from flask import render_template, request, redirect, url_for, flash, abort

#from flask_login import login_required, current_user

#from datetime import datetime

#from . import maintenance_bp

#from app.models import WorkOrder, User, db

#from app.forms import csrf  # 假设已配置 Flask-WTF 的 CSRF 保护

# ---------- 工单列表页面 ----------

@maintenance_bp.route('/work_order/list')

@login_required

@permission_required('maintenance:view')

def work_order_list():

    """工单列表（含筛选和统计）"""

    status_filter = request.args.get('status', 'all')

    priority_filter = request.args.get('priority', 'all')

    category_filter = request.args.get('category', 'all')

    major_filter = request.args.get('major', 'all')

    query = WorkOrder.query

    if status_filter != 'all':

        query = query.filter_by(status=status_filter)

    if priority_filter != 'all':

        query = query.filter_by(priority=priority_filter)

    if category_filter != 'all':

        query = query.filter_by(category=category_filter)

    if major_filter == '1':

        query = query.filter(WorkOrder.is_major.is_(True))

    page = request.args.get('page', 1, type=int)

    pagination = query.order_by(WorkOrder.created_at.desc()).paginate(

        page=page, per_page=20, error_out=False

    )

    work_orders = pagination.items

    # 统计信息

    total_orders = WorkOrder.query.count()

    open_orders = WorkOrder.query.filter_by(status='open').count()

    in_progress_orders = WorkOrder.query.filter_by(status='in_progress').count()

    closed_orders = WorkOrder.query.filter_by(status='closed').count()

    major_orders = WorkOrder.query.filter_by(is_major=True).count()

    # 获取所有用户（用于分配下拉框）

    engineers = User.query.order_by(User.username).all()

    return render_template('maintenance/work_order_list.html',

                         work_orders=work_orders,

                         status_filter=status_filter,

                         priority_filter=priority_filter,

                         category_filter=category_filter,

                         major_filter=major_filter,

                         total_orders=total_orders,

                         open_orders=open_orders,

                         in_progress_orders=in_progress_orders,

                         closed_orders=closed_orders,

                         major_orders=major_orders,

                         engineers=engineers,

                         pagination=pagination)

# ---------- 工单详情页面（查看） ----------

@maintenance_bp.route('/work_order/<int:id>')

@login_required

@permission_required('maintenance:view')

def view_work_order(id):

    """查看工单详情"""

    work_order = WorkOrder.query.get_or_404(id)

    users = User.query.order_by(User.username).all()

    # 知识库联动推荐（按设备类型/厂商/工单分类匹配）

    recommended_kb = []

    device = work_order.device

    if device:

        from models.maintenance_models import KnowledgeArticle

        conditions = []

        if device.type:

            conditions.append(KnowledgeArticle.device_type == device.type)

        if device.vendor:

            conditions.append(KnowledgeArticle.vendor == device.vendor)

        if work_order.category:

            conditions.append(KnowledgeArticle.category == work_order.category)

        if conditions:

            recommended_kb = KnowledgeArticle.query.filter_by(status='published') \
                .filter(db.or_(*conditions)) \
                .order_by(KnowledgeArticle.view_count.desc()).limit(5).all()

    return render_template('maintenance/work_order_detail.html', work_order=work_order,

                           users=users, recommended_kb=recommended_kb)

# ---------- 工单操作：分配 ----------

@maintenance_bp.route('/work_order/<int:id>/assign', methods=['POST'])

@login_required

@permission_required('maintenance:edit')

def assign_work_order(id):

    """分配工单给工程师"""

    work_order = WorkOrder.query.get_or_404(id)

    # 检查状态是否允许分配（通常只有 open 状态可以分配）

    if work_order.status != 'open':

        flash('只能分配状态为“开放”的工单', 'danger')

        return redirect(url_for('maintenance.work_order_list'))

    engineer_id = request.form.get('engineer_id')

    notes = request.form.get('notes', '')

    if not engineer_id:

        flash('请选择工程师', 'danger')

        return redirect(url_for('maintenance.work_order_list'))

    engineer = User.query.get(engineer_id)

    if not engineer:

        flash('所选工程师不存在', 'danger')

        return redirect(url_for('maintenance.work_order_list'))

    # 更新工单分配信息

    work_order.assigned_to_id = engineer.id

    work_order.assigned_to_name = engineer.username

    work_order.assigned_department = engineer.department  # 假设有 department 字段

    work_order.status = 'assigned'

    work_order.updated_at = datetime.utcnow()

    work_order.updated_by = current_user.username

    # SLA：首次响应计时

    if work_order.actual_response_time is None:

        work_order.actual_response_time = round((datetime.utcnow() - work_order.requested_at).total_seconds() / 3600, 2)

    work_order.compute_sla_status()

    # 可选的备注字段（工单模型没有专门备注字段，可以存在 resolution_notes 或其他）

    if notes:

        work_order.resolution_notes = notes

    db.session.commit()

    log_audit('update', 'work_order', work_order.id, f"分配工单: {work_order.work_order_number} -> {engineer.username}", user_id=current_user.id if current_user.is_authenticated else None)

    flash(f'工单 {work_order.work_order_number} 已分配给 {engineer.username}', 'success')

    return redirect(url_for('maintenance.work_order_list'))

# ---------- 工单操作：处理（开始处理） ----------

@maintenance_bp.route('/work_order/<int:id>/process', methods=['POST'])

@login_required

@permission_required('maintenance:edit')

def process_work_order(id):

    """开始处理工单（状态变为进行中）"""

    work_order = WorkOrder.query.get_or_404(id)

    # 允许从 assigned 或 open 状态进入处理（若未分配也可直接处理）

    if work_order.status not in ['assigned', 'open']:

        flash('只有“已分配”或“开放”的工单才能开始处理', 'danger')

        return redirect(url_for('maintenance.work_order_list'))

    notes = request.form.get('notes', '')

    actual_start_str = request.form.get('actual_start_date')

    # 更新状态和实际开始时间

    work_order.status = 'in_progress'

    work_order.updated_at = datetime.utcnow()

    work_order.updated_by = current_user.username

    if actual_start_str:

        try:

            work_order.actual_start_date = datetime.fromisoformat(actual_start_str)

        except ValueError:

            flash('开始时间格式错误', 'danger')

            return redirect(url_for('maintenance.work_order_list'))

    else:

        work_order.actual_start_date = datetime.utcnow()  # 默认当前时间

    if notes:

        work_order.resolution_notes = notes

    # SLA：首次响应计时（若分配时未记录）

    if work_order.actual_response_time is None:

        work_order.actual_response_time = round((datetime.utcnow() - work_order.requested_at).total_seconds() / 3600, 2)

    work_order.compute_sla_status()

    db.session.commit()

    log_audit('update', 'work_order', work_order.id, f"开始处理工单: {work_order.work_order_number}", user_id=current_user.id if current_user.is_authenticated else None)

    flash(f'工单 {work_order.work_order_number} 开始处理', 'success')

    return redirect(url_for('maintenance.work_order_list'))

# ---------- 工单操作：解决 ----------

@maintenance_bp.route('/work_order/<int:id>/resolve', methods=['POST'])

@login_required

@permission_required('maintenance:edit')

def resolve_work_order(id):

    """解决工单（状态变为已解决）"""

    work_order = WorkOrder.query.get_or_404(id)

    # 允许从 in_progress 或 assigned 状态解决

    if work_order.status not in ['in_progress', 'assigned']:

        flash('只有“进行中”或“已分配”的工单才能解决', 'danger')

        return redirect(url_for('maintenance.work_order_list'))

    resolution = request.form.get('resolution')

    actual_hours = request.form.get('actual_hours', type=float)

    notes = request.form.get('notes', '')

    if not resolution:

        flash('请填写解决方案', 'danger')

        return redirect(url_for('maintenance.work_order_list'))

    work_order.resolution = resolution

    work_order.status = 'resolved'

    work_order.actual_end_date = datetime.utcnow()

    work_order.updated_at = datetime.utcnow()

    work_order.updated_by = current_user.username

    # 计算解决时间（小时）

    if work_order.actual_start_date:

        delta = work_order.actual_end_date - work_order.actual_start_date

        work_order.resolution_time = round(delta.total_seconds() / 3600, 2)

    if actual_hours is not None:

        work_order.actual_hours = actual_hours

    if notes:

        work_order.resolution_notes = notes

    # SLA：解决后结算达标情况

    work_order.compute_sla_status()

    db.session.commit()

    log_audit('update', 'work_order', work_order.id, f"解决工单: {work_order.work_order_number}", user_id=current_user.id if current_user.is_authenticated else None)

    flash(f'工单 {work_order.work_order_number} 已解决', 'success')

    return redirect(url_for('maintenance.work_order_list'))

# ---------- 工单操作：挂起 ----------

@maintenance_bp.route('/work_order/<int:id>/hold', methods=['POST'])

@login_required

@permission_required('maintenance:edit')

def hold_work_order(id):

    """挂起工单（状态变为挂起）"""

    work_order = WorkOrder.query.get_or_404(id)

    if work_order.status != 'in_progress':

        flash('只有“进行中”的工单才能挂起', 'danger')

        return redirect(url_for('maintenance.work_order_list'))

    work_order.status = 'on_hold'

    work_order.updated_at = datetime.utcnow()

    work_order.updated_by = current_user.username

    db.session.commit()

    log_audit('update', 'work_order', work_order.id, f"挂起工单: {work_order.work_order_number}", user_id=current_user.id if current_user.is_authenticated else None)

    flash(f'工单 {work_order.work_order_number} 已挂起', 'success')

    return redirect(url_for('maintenance.work_order_list'))

# ---------- 工单操作：恢复（从挂起恢复） ----------

@maintenance_bp.route('/work_order/<int:id>/resume', methods=['POST'])

@login_required

@permission_required('maintenance:edit')

def resume_work_order(id):

    """恢复被挂起的工单（回到进行中）"""

    work_order = WorkOrder.query.get_or_404(id)

    if work_order.status != 'on_hold':

        flash('只有“挂起”的工单才能恢复', 'danger')

        return redirect(url_for('maintenance.work_order_list'))

    work_order.status = 'in_progress'

    work_order.updated_at = datetime.utcnow()

    work_order.updated_by = current_user.username

    db.session.commit()

    log_audit('update', 'work_order', work_order.id, f"恢复工单: {work_order.work_order_number}", user_id=current_user.id if current_user.is_authenticated else None)

    flash(f'工单 {work_order.work_order_number} 已恢复处理', 'success')

    return redirect(url_for('maintenance.work_order_list'))


# ---------- 工单操作：重新打开 ----------

@maintenance_bp.route('/work_order/<int:id>/reopen', methods=['POST'])

@login_required

@permission_required('maintenance:edit')

def reopen_work_order(id):

    """重新打开已关闭的工单（状态变为开放）"""

    work_order = WorkOrder.query.get_or_404(id)

    if work_order.status != 'closed':

        flash('只有“已关闭”的工单才能重新打开', 'danger')

        return redirect(url_for('maintenance.work_order_list'))

    work_order.status = 'open'

    work_order.closed_at = None

    work_order.closed_by = None

    work_order.updated_at = datetime.utcnow()

    work_order.updated_by = current_user.username

    db.session.commit()

    log_audit('update', 'work_order', work_order.id, f"重新打开工单: {work_order.work_order_number}", user_id=current_user.id if current_user.is_authenticated else None)

    flash(f'工单 {work_order.work_order_number} 已重新打开', 'success')

    return redirect(url_for('maintenance.work_order_list'))

@maintenance_bp.route('/work_order/<int:id>/delete', methods=['POST'])

@login_required

@permission_required('maintenance:edit')

def delete_work_order(id):

    work_order = WorkOrder.query.get_or_404(id)

    db.session.delete(work_order)

    db.session.commit()

    log_audit('delete', 'work_order', id, f"删除工单: {work_order.work_order_number}", user_id=current_user.id if current_user.is_authenticated else None)

    flash('工单已删除', 'success')

    return redirect(url_for('maintenance.work_order_list'))

@maintenance_bp.route('/work_order/<int:id>/edit', methods=['GET', 'POST'])

@login_required

@permission_required('maintenance:edit')

def edit_work_order(id):

    """编辑工单"""

    work_order = WorkOrder.query.get_or_404(id)

    form = WorkOrderForm(obj=work_order)

    # 为指派工程师下拉框注入用户选项

    users = User.query.order_by(User.username).all()

    form.assigned_to.choices = [(0, '未指派')] + [(u.id, u.username) for u in users]

    # 预填充指派工程师下拉框

    form.assigned_to.data = work_order.assigned_to_id or 0

    if form.validate_on_submit():

        # 手动更新字段（避免 populate_obj 将 int 赋给 relationship）

        work_order.title = form.title.data

        work_order.description = form.description.data

        work_order.priority = form.priority.data

        work_order.category = form.category.data

        # 工单类型保持与分类一致，并重新匹配 SLA 策略，避免分类/优先级修改后 SLA 失真

        work_order.work_order_type = form.category.data

        work_order.due_date = form.deadline.data

        work_order.is_major = form.is_major.data

        work_order.apply_sla_policy()

        work_order.compute_sla_status()

        # 指派信息

        assigned_to_id = form.assigned_to.data if form.assigned_to.data and form.assigned_to.data != 0 else None

        work_order.assigned_to_id = assigned_to_id

        if assigned_to_id:

            assigned_user = User.query.get(assigned_to_id)

            work_order.assigned_to_name = assigned_user.username if assigned_user else None

        else:

            work_order.assigned_to_name = None

        work_order.updated_by = current_user.username

        work_order.updated_at = datetime.utcnow()

        db.session.commit()

        log_audit('update', 'work_order', work_order.id, f"编辑工单: {work_order.work_order_number}", user_id=current_user.id if current_user.is_authenticated else None)

        flash('工单已更新', 'success')

        return redirect(url_for('maintenance.view_work_order', id=work_order.id))

    return render_template('maintenance/edit_work_order.html', form=form, work_order=work_order)

@maintenance_bp.route('/work_order/<int:id>/toggle-major', methods=['POST'])

@login_required

@permission_required('maintenance:edit')

def toggle_major_work_order(id):

    """标记 / 取消重大事件"""

    work_order = WorkOrder.query.get_or_404(id)

    work_order.is_major = not work_order.is_major

    work_order.updated_by = current_user.username

    db.session.commit()

    log_audit('update', 'work_order', work_order.id,

              f"{'标记' if work_order.is_major else '取消'}重大事件: {work_order.work_order_number}",

              user_id=current_user.id if current_user.is_authenticated else None)

    flash('已标记为重大事件' if work_order.is_major else '已取消重大事件标记', 'success')

    return redirect(url_for('maintenance.view_work_order', id=work_order.id))

@maintenance_bp.route('/work_order/<int:id>/cancel', methods=['POST'])

@login_required

@permission_required('maintenance:edit')

def cancel_work(id):

    """取消工单"""

    work_order = WorkOrder.query.get_or_404(id)

    # 检查状态是否允许取消（例如只有 open、assigned 等状态可取消）

    if work_order.status in ['open', 'assigned', 'in_progress']:

        work_order.status = 'cancelled'

        work_order.closed_by = current_user.username

        work_order.closed_at = datetime.utcnow()

        work_order.updated_by = current_user.username

        db.session.commit()

        log_audit('update', 'work_order', work_order.id, f"取消工单: {work_order.work_order_number}", user_id=current_user.id if current_user.is_authenticated else None)

        flash('工单已取消', 'success')

    else:

        flash('当前状态的工单无法取消', 'danger')

    return redirect(url_for('maintenance.view_work_order', id=work_order.id))

@maintenance_bp.route('/work_order/<int:id>/close', methods=['POST'])

@login_required

@permission_required('maintenance:edit')

def close_work_order(id):

    """关闭工单（从已解决状态关闭）"""

    work_order = WorkOrder.query.get_or_404(id)

    if work_order.status == 'resolved':

        work_order.status = 'closed'

        work_order.closed_by = current_user.username

        work_order.closed_at = datetime.utcnow()

        work_order.updated_by = current_user.username

        db.session.commit()

        log_audit('update', 'work_order', work_order.id, f"关闭工单: {work_order.work_order_number}", user_id=current_user.id if current_user.is_authenticated else None)

        flash('工单已关闭', 'success')

    else:

        flash('只有已解决的工单才能关闭', 'danger')

    return redirect(url_for('maintenance.view_work_order', id=work_order.id))


@maintenance_bp.route('/change/request/new', methods=['GET', 'POST'])

@login_required

@permission_required('maintenance:edit')

def create_change_request():

    """创建新的变更请求"""

    form = ChangeRequestForm()

    users = User.query.filter_by(is_active=True).all()

    form.implementer_id.choices = [(0, '-- 请选择实施人 --')] + [(u.id, u.username) for u in users]

    if form.validate_on_submit():

        # 创建变更请求对象

        change_request = ChangeRequest(

            title=form.title.data,

            description=form.description.data,

            change_type=form.change_type.data,

            category=form.category.data,

            impact_level=form.impact_level.data,

            risk_level=form.risk_level.data,

            impact_description=form.impact_description.data,

            risk_description=form.risk_description.data,

            scheduled_date=form.scheduled_date.data,

            scheduled_start_time=form.scheduled_start_time.data,

            scheduled_end_time=form.scheduled_end_time.data,

            estimated_duration_hours=form.estimated_duration_hours.data,

            affected_devices=form.affected_devices.data,

            affected_services=form.affected_services.data,

            affected_users=form.affected_users.data,

            implementation_plan=form.implementation_plan.data,

            rollback_plan=form.rollback_plan.data,

            test_plan=form.test_plan.data,

            cab_review_required=form.cab_review_required.data,

            requester_id=current_user.id,

            requester_name=current_user.username,

            created_by=current_user.username,

            status='draft'

        )

        # 处理实施人

        if form.implementer_id.data and form.implementer_id.data != 0:

            implementer = User.query.get(form.implementer_id.data)

            if implementer:

                change_request.implementer_id = implementer.id

                change_request.implementer_name = implementer.username

        # === 关键修改：设置临时编号 ===

        # 使用UUID确保临时编号唯一，且不为NULL

        change_request.change_number = f"TEMP-{uuid.uuid4()}"

        # 添加到会话并 flush，以获取数据库自增ID

        db.session.add(change_request)

        db.session.flush()   # 此时 change_request.id 被赋值，临时编号已插入

        # 用真实的ID生成最终编号，并覆盖临时编号

        change_request.generate_change_number()   # 该方法应基于 self.id 生成正式编号

        # 同步受影响设备关联（影响分析）

        for did in (form.affected_devices_ids.data or []):

            if did:

                db.session.add(ChangeAffectedDevice(change_id=change_request.id, device_id=did))

        # 提交事务（此时会发出UPDATE语句更新 change_number）

        db.session.commit()

        log_audit('create', 'change_request', change_request.id, f"创建变更请求: {change_request.change_number}", user_id=current_user.id if current_user.is_authenticated else None)

        flash(f'变更请求 {change_request.change_number} 创建成功！', 'success')

        return redirect(url_for('maintenance.change_detail', change_id=change_request.id))

    return render_template('maintenance/create_change_request.html', form=form)

@maintenance_bp.route('/change/request/<int:change_id>/delete', methods=['POST'])

@login_required

@permission_required('maintenance:edit')

def delete_change_request(change_id):

    """删除变更请求"""

    change_request = ChangeRequest.query.get_or_404(change_id)

    # 可选：检查权限（例如只有创建者或管理员可删除）

    if current_user.id != change_request.requester_id:

        flash('您没有权限删除此变更请求', 'danger')

        return redirect(url_for('maintenance.change_requests'))

    # 软删除或硬删除？根据业务需求，通常建议软删除（添加 deleted_at 字段）

    # 此处示例为硬删除

    db.session.delete(change_request)

    db.session.commit()

    log_audit('delete', 'change_request', change_id, f"删除变更请求: {change_request.change_number}", user_id=current_user.id if current_user.is_authenticated else None)

    flash(f'变更请求 {change_request.change_number} 已删除', 'success')

    return redirect(url_for('maintenance.change_requests'))

@maintenance_bp.route('/change/request/<int:change_id>/edit', methods=['GET', 'POST'])

@login_required

@permission_required('maintenance:edit')

def edit_change_request(change_id):

    """编辑变更请求"""

    change_request = ChangeRequest.query.get_or_404(change_id)

    form = ChangeRequestForm(obj=change_request)  # 预填充表单

    # 填充实施人选择框

    users = User.query.filter_by(is_active=True).all()

    form.implementer_id.choices = [(0, '-- 请选择实施人 --')] + [(u.id, u.username) for u in users]

    if change_request.implementer_id:

        form.implementer_id.data = change_request.implementer_id

    form.affected_devices_ids.data = [link.device_id for link in change_request.affected_device_links]

    if form.validate_on_submit():

        # 更新字段

        form.populate_obj(change_request)

        # 处理实施人

        if form.implementer_id.data and form.implementer_id.data != 0:

            implementer = User.query.get(form.implementer_id.data)

            change_request.implementer_id = implementer.id

            change_request.implementer_name = implementer.username

        else:

            change_request.implementer_id = None

            change_request.implementer_name = None

        # 更新操作人

        change_request.updated_by = current_user.username

        # 同步受影响设备关联（影响分析）

        selected = set(form.affected_devices_ids.data or [])

        existing = {link.device_id for link in change_request.affected_device_links}

        for did in selected - existing:

            if did:

                db.session.add(ChangeAffectedDevice(change_id=change_request.id, device_id=did))

        for link in list(change_request.affected_device_links):

            if link.device_id not in selected:

                db.session.delete(link)

        db.session.commit()

        log_audit('update', 'change_request', change_id, f"编辑变更请求: {change_request.change_number}", user_id=current_user.id if current_user.is_authenticated else None)

        flash('变更请求已更新', 'success')

        return redirect(url_for('maintenance.view_change_request', change_id=change_request.id))

    return render_template('maintenance/edit_change_request.html', form=form, cr=change_request)

# 变更详情快捷动作（补齐变更详情页按钮引用的端点）

@maintenance_bp.route('/change/<int:change_id>/edit')

@login_required

@permission_required('maintenance:edit')

def edit_change(change_id):

    """变更详情页编辑按钮：跳转到现有编辑页。"""

    return redirect(url_for('maintenance.edit_change_request', change_id=change_id))

@maintenance_bp.route('/change/<int:change_id>/submit', methods=['GET', 'POST'])

@login_required

@permission_required('maintenance:edit')

def submit_change(change_id):

    """提交变更审批。兼容详情页按钮；生产环境建议改用 POST 表单。"""

    change = ChangeRequest.query.get_or_404(change_id)

    if change.status != 'draft':

        flash('只有草稿状态的变更才能提交审批', 'warning')

    else:

        change.status = 'submitted'

        change.updated_by = current_user.username

        change.updated_at = datetime.utcnow()

        db.session.commit()

        log_audit('update', 'change_request', change.id,

                  f"提交变更审批: {change.change_number}",

                  user_id=current_user.id if current_user.is_authenticated else None)

        flash(f'变更 {change.change_number} 已提交审批', 'success')

    return redirect(url_for('maintenance.change_detail', change_id=change.id))

@maintenance_bp.route('/change/<int:change_id>/schedule', methods=['GET', 'POST'])

@login_required

@permission_required('maintenance:edit')

def schedule_change(change_id):

    """将已批准变更标记为已排期。"""

    change = ChangeRequest.query.get_or_404(change_id)

    if change.status not in ('approved', 'scheduled'):

        flash('只有已批准变更才能排期', 'warning')

    else:

        change.status = 'scheduled'

        change.updated_by = current_user.username

        change.updated_at = datetime.utcnow()

        db.session.commit()

        log_audit('update', 'change_request', change.id,

                  f"变更排期: {change.change_number}",

                  user_id=current_user.id if current_user.is_authenticated else None)

        flash(f'变更 {change.change_number} 已排期', 'success')

    return redirect(url_for('maintenance.change_detail', change_id=change.id))

@maintenance_bp.route('/change/<int:change_id>/start', methods=['GET', 'POST'])

@login_required

@permission_required('maintenance:edit')

def start_change(change_id):

    """开始实施变更。"""

    change = ChangeRequest.query.get_or_404(change_id)

    if change.status not in ('scheduled', 'approved'):

        flash('只有已排期或已批准变更才能开始实施', 'warning')

    else:

        change.status = 'in_progress'

        change.actual_start_date = datetime.utcnow()

        change.updated_by = current_user.username

        change.updated_at = datetime.utcnow()

        db.session.commit()

        log_audit('update', 'change_request', change.id,

                  f"开始实施变更: {change.change_number}",

                  user_id=current_user.id if current_user.is_authenticated else None)

        flash(f'变更 {change.change_number} 已开始实施', 'success')

    return redirect(url_for('maintenance.change_detail', change_id=change.id))

@maintenance_bp.route('/change/<int:change_id>/complete', methods=['GET', 'POST'])

@login_required

@permission_required('maintenance:edit')

def complete_change(change_id):

    """Complete change implementation and persist post-implementation review."""

    change = ChangeRequest.query.get_or_404(change_id)

    if change.status != 'in_progress':

        flash('Only in-progress changes can be completed', 'warning')

    else:

        now = datetime.utcnow()

        change.status = 'completed'

        change.actual_end_date = now

        change.actual_duration_hours = round((now - (change.actual_start_date or now)).total_seconds() / 3600, 2)

        change.closed_by = current_user.username

        change.closed_date = now

        change.updated_by = current_user.username

        change.updated_at = now

        change.implementation_result = request.form.get('implementation_result', change.implementation_result)

        change.issues_encountered = request.form.get('issues_encountered', change.issues_encountered)

        change.post_implementation_review = request.form.get('post_implementation_review', change.post_implementation_review)

        change.lessons_learned = request.form.get('lessons_learned', change.lessons_learned)

        success_value = request.form.get('success_criteria_met')

        if success_value in ('yes', 'on', 'true', '1'):

            change.success_criteria_met = True

        elif success_value in ('no', 'false', '0'):

            change.success_criteria_met = False

        db.session.commit()

        log_audit('update', 'change_request', change.id,

                  f"Complete change: {change.change_number}",

                  user_id=current_user.id if current_user.is_authenticated else None)

        flash(f'Change {change.change_number} completed', 'success')

    return redirect(url_for('maintenance.change_detail', change_id=change.id))

@maintenance_bp.route('/change/<int:change_id>/print')

@login_required

@permission_required('maintenance:view')

def print_change(change_id):

    """打印变更报告（复用详情页，隐藏非打印内容由模板控制）。"""

    change = ChangeRequest.query.get_or_404(change_id)

    from blueprints.cab_chain import detect_change_conflicts, get_active_stage

    conflicts = detect_change_conflicts(change)

    active_stage = get_active_stage(change)

    return render_template('maintenance/change_detail.html', change=change,

                           conflicts=conflicts, active_stage=active_stage,

                           print_mode=True)

# 变更详情页

@maintenance_bp.route('/change/<int:change_id>')

@login_required

@permission_required('maintenance:view')

def change_detail(change_id):

    """查看变更详情"""

    change = ChangeRequest.query.get_or_404(change_id)

    from blueprints.cab_chain import detect_change_conflicts, get_active_stage

    conflicts = detect_change_conflicts(change)

    active_stage = get_active_stage(change)

    return render_template('maintenance/change_detail.html', change=change,

                           conflicts=conflicts, active_stage=active_stage)

# 批准变更

@maintenance_bp.route('/change/<int:change_id>/approve', methods=['POST'])

@login_required

@permission_required('maintenance:edit')

def approve_change(change_id):

    change = ChangeRequest.query.get_or_404(change_id)

    # 若已生成 CAB 审批链，必须走分阶段审批，禁止单人直接批准

    if change.approval_chain.count() > 0:

        flash('该变更已启用 CAB 审批链，请在变更详情中按阶段审批。', 'warning')

        return redirect(url_for('maintenance.change_detail', change_id=change.id))

    # 根据您的业务状态调整，待审批可能是 'pending' 或 'submitted'

    if change.status not in ['pending', 'submitted']:

        flash('该变更当前状态不允许批准。', 'warning')

        return redirect(url_for('maintenance.change_approval'))

    notes = request.form.get('notes', '').strip()

    try:

        change.status = 'approved'

        change.approval_status = 'approved'

        change.approver_id = current_user.id

        change.approver_name = current_user.username

        change.approval_date = datetime.utcnow()

        change.approval_notes = notes if notes else None

        db.session.commit()

        log_audit('update', 'change_request', change_id, f"批准变更: {change.change_number}", user_id=current_user.id if current_user.is_authenticated else None)

        flash(f'变更 {change.change_number} 已批准。', 'success')

    except Exception as e:

        db.session.rollback()

        flash(f'批准失败：{str(e)}', 'danger')

    return redirect(url_for('maintenance.change_approval'))

# 拒绝变更

@maintenance_bp.route('/change/<int:change_id>/reject', methods=['POST'])

@login_required

@permission_required('maintenance:edit')

def reject_change(change_id):

    change = ChangeRequest.query.get_or_404(change_id)

    if change.approval_chain.count() > 0:

        flash('该变更已启用 CAB 审批链，请在变更详情中按阶段驳回。', 'warning')

        return redirect(url_for('maintenance.change_detail', change_id=change.id))

    if change.status not in ['pending', 'submitted']:

        flash('该变更当前状态不允许拒绝。', 'warning')

        return redirect(url_for('maintenance.change_approval'))

    notes = request.form.get('notes', '').strip()

    if not notes:

        flash('拒绝变更时必须填写审批意见。', 'warning')

        return redirect(url_for('maintenance.change_approval'))

    try:

        change.status = 'rejected'

        change.approval_status = 'rejected'

        change.approver_id = current_user.id

        change.approver_name = current_user.username

        change.approval_date = datetime.utcnow()

        change.approval_notes = notes

        db.session.commit()

        log_audit('update', 'change_request', change_id, f"拒绝变更: {change.change_number}", user_id=current_user.id if current_user.is_authenticated else None)

        flash(f'变更 {change.change_number} 已拒绝。', 'success')

    except Exception as e:

        db.session.rollback()

        flash(f'拒绝失败：{str(e)}', 'danger')

    return redirect(url_for('maintenance.change_approval'))

@maintenance_bp.route('/change/request/<int:change_id>/submit', methods=['POST'])

@login_required

@permission_required('maintenance:edit')

def submit_change_for_approval(change_id):

    """提交变更请求进行审批"""

    change_request = ChangeRequest.query.get_or_404(change_id)

    # 权限检查：只有请求人可以提交审批

    if current_user.id != change_request.requester_id:

        flash('您没有权限提交此变更', 'danger')

        return redirect(url_for('maintenance.change_requests'))

    # 状态检查：只有草稿状态才能提交

    if change_request.status != 'draft':

        flash('只有草稿状态的变更才能提交审批', 'warning')

        return redirect(url_for('maintenance.change_requests'))

    # 更新状态为 'submitted' 或 'review'（根据流程选择）

    change_request.status = 'submitted'  # 或者 'review'

    change_request.updated_by = current_user.username

    # 自动构建 CAB 审批链（按活动 CAB 配置生成分阶段审批记录）

    from blueprints.cab_chain import build_approval_chain

    build_approval_chain(change_request)

    # 先算影响再实施：提交即持久化一次影响模拟快照

    from utils.change_impact import run_and_persist

    try:

        run_and_persist(change_request, db.session)

    except Exception:

        pass

    db.session.commit()

    log_audit('update', 'change_request', change_id, f"提交变更审批: {change_request.change_number}", user_id=current_user.id if current_user.is_authenticated else None)

    flash(f'变更请求 {change_request.change_number} 已成功提交审批', 'success')

    return redirect(url_for('maintenance.change_requests'))

@maintenance_bp.route('/change/<int:change_id>/delete', methods=['POST'])

@login_required

@permission_required('maintenance:edit')

def delete_change(change_id):

    change = ChangeRequest.query.get_or_404(change_id)

    # 仅允许删除特定状态的变更（例如草稿）

    if change.status not in ['draft', 'rejected']:

        flash('只能删除草稿或已拒绝的变更。', 'warning')

        return redirect(url_for('maintenance.change_detail', change_id=change.id))

    try:

        change_number = change.change_number

        db.session.delete(change)

        db.session.commit()

        log_audit('delete', 'change_request', change_id, f"删除变更: {change_number}", user_id=current_user.id if current_user.is_authenticated else None)

        flash(f'变更 {change_number} 已成功删除。', 'success')

    except Exception as e:

        db.session.rollback()

        flash(f'删除失败：{str(e)}', 'danger')

    return redirect(url_for('maintenance.change_requests'))

@maintenance_bp.route('/change/<int:change_id>/view')

@login_required

@permission_required('maintenance:view')

def view_change_request(change_id):

    """兼容旧端点的重定向"""

    return redirect(url_for('maintenance.change_detail', change_id=change_id))

def generate_change_number(self):

    """生成正式变更编号，基于自增ID"""

    # 如果已经有正式编号且不是临时格式，则跳过（防止重复生成）

    if self.change_number and not self.change_number.startswith("TEMP-"):

        return self.change_number

    if self.id:

        date_str = datetime.now().strftime('%Y%m%d')

        self.change_number = f'CR{date_str}{self.id:04d}'

    else:

        # 理论上不会走到这里，因为 flush 后已有 id

        raise ValueError("无法生成变更编号：对象尚未获得自增ID")

    return self.change_number

# -------------------- 巡检模板 API --------------------

@maintenance_bp.route('/api/inspection_templates', methods=['GET'])

@login_required

@permission_required('maintenance:view')

def get_inspection_templates():

    """获取所有巡检模板（JSON格式）"""

    try:

        templates = InspectionTemplate.query.filter_by(is_active=True).all()

        result = []

        for t in templates:

            # 处理 items 字段，尝试解析 JSON

            items_data = t.items

            try:

                items = json.loads(items_data) if items_data.startswith('[') else items_data.split('\n')

            except:

                items = items_data.split('\n') if items_data else []

            result.append({

                'id': t.id,

                'name': t.name,

                'description': t.description,

                'template_type': t.template_type,

                'category': t.category,

                'applicable_to': t.applicable_to,

                'device_type': t.device_type,

                'items': items,

                'item_count': t.item_count,

                'standards': t.standards,

                'pass_criteria': t.pass_criteria,

                'estimated_time_minutes': t.estimated_time_minutes,

                'frequency_days': t.frequency_days,

                'reminder_days': t.reminder_days,

                'is_active': t.is_active,

                'is_default': t.is_default,

                'created_at': t.created_at.isoformat() if t.created_at else None,

                'updated_at': t.updated_at.isoformat() if t.updated_at else None,

                'created_by': t.created_by,

                'updated_by': t.updated_by

            })

        return jsonify({'success': True, 'data': result}), 200

    except Exception as e:

        return jsonify({'success': False, 'error': str(e)}), 500

@maintenance_bp.route('/api/inspection_templates', methods=['POST'])

@login_required

@permission_required('maintenance:edit')

def create_inspection_template():

    """创建新巡检模板"""

    if not request.is_json:

        return jsonify({'success': False, 'error': '请求必须为 JSON 格式'}), 415

    try:

        data = request.get_json()

        # 必填字段验证

        required_fields = ['name', 'template_type', 'items']

        for field in required_fields:

            if field not in data or not data[field]:

                return jsonify({'success': False, 'error': f'缺少必填字段: {field}'}), 400

        # 名称唯一性检查

        if InspectionTemplate.query.filter_by(name=data['name']).first():

            return jsonify({'success': False, 'error': f'模板名称 "{data["name"]}" 已存在'}), 400

        # 处理 items 字段（存储为字符串）

        items_data = data['items']

        if isinstance(items_data, (list, dict)):

            items_str = json.dumps(items_data, ensure_ascii=False)

        else:

            items_str = str(items_data)

        # 创建实例

        new_template = InspectionTemplate(

            name=data['name'].strip(),

            description=data.get('description', ''),

            template_type=data['template_type'],

            category=data.get('category', ''),

            applicable_to=data.get('applicable_to', ''),

            device_type=data.get('device_type', ''),

            items=items_str,

            standards=data.get('standards', ''),

            pass_criteria=data.get('pass_criteria', ''),

            estimated_time_minutes=data.get('estimated_time_minutes', 30),

            frequency_days=data.get('frequency_days'),

            reminder_days=data.get('reminder_days', 1),

            is_active=data.get('is_active', True),

            is_default=data.get('is_default', False),

            created_by=current_user.username if current_user.is_authenticated else 'system',

            updated_by=current_user.username if current_user.is_authenticated else 'system'

        )

        new_template.update_item_count()

        db.session.add(new_template)

        db.session.commit()

        log_audit('create', 'inspection_template', new_template.id, f"创建巡检模板(API): {new_template.name}", user_id=current_user.id if current_user.is_authenticated else None)

        return jsonify({'success': True, 'id': new_template.id, 'message': '模板创建成功'}), 201

    except Exception as e:

        db.session.rollback()

        return jsonify({'success': False, 'error': str(e)}), 500

@maintenance_bp.route('/api/inspection_templates/<int:template_id>', methods=['GET'])

@login_required

@permission_required('maintenance:view')

def get_inspection_template(template_id):

    """获取单个巡检模板详情"""

    try:

        template = InspectionTemplate.query.get_or_404(template_id)

        # 处理 items

        items_data = template.items

        try:

            items = json.loads(items_data) if items_data.startswith('[') else items_data.split('\n')

        except:

            items = items_data.split('\n') if items_data else []

        result = {

            'id': template.id,

            'name': template.name,

            'description': template.description,

            'template_type': template.template_type,

            'category': template.category,

            'applicable_to': template.applicable_to,

            'device_type': template.device_type,

            'items': items,

            'item_count': template.item_count,

            'standards': template.standards,

            'pass_criteria': template.pass_criteria,

            'estimated_time_minutes': template.estimated_time_minutes,

            'frequency_days': template.frequency_days,

            'reminder_days': template.reminder_days,

            'is_active': template.is_active,

            'is_default': template.is_default,

            'created_at': template.created_at.isoformat() if template.created_at else None,

            'updated_at': template.updated_at.isoformat() if template.updated_at else None,

            'created_by': template.created_by,

            'updated_by': template.updated_by

        }

        return jsonify({'success': True, 'data': result}), 200

    except Exception as e:

        return jsonify({'success': False, 'error': str(e)}), 500

@maintenance_bp.route('/api/inspection_templates/<int:template_id>', methods=['PUT'])

@login_required

@permission_required('maintenance:edit')

def update_inspection_template(template_id):

    """更新巡检模板"""

    if not request.is_json:

        return jsonify({'success': False, 'error': '请求必须为 JSON 格式'}), 415

    try:

        template = InspectionTemplate.query.get_or_404(template_id)

        data = request.get_json()

        # 如果更新名称，检查唯一性

        if 'name' in data and data['name'] != template.name:

            if InspectionTemplate.query.filter_by(name=data['name']).first():

                return jsonify({'success': False, 'error': f'模板名称 "{data["name"]}" 已存在'}), 400

            template.name = data['name'].strip()

        # 更新其他字段

        if 'description' in data:

            template.description = data['description']

        if 'template_type' in data:

            template.template_type = data['template_type']

        if 'category' in data:

            template.category = data['category']

        if 'applicable_to' in data:

            template.applicable_to = data['applicable_to']

        if 'device_type' in data:

            template.device_type = data['device_type']

        if 'items' in data:

            items_data = data['items']

            if isinstance(items_data, (list, dict)):

                template.items = json.dumps(items_data, ensure_ascii=False)

            else:

                template.items = str(items_data)

        if 'standards' in data:

            template.standards = data['standards']

        if 'pass_criteria' in data:

            template.pass_criteria = data['pass_criteria']

        if 'estimated_time_minutes' in data:

            template.estimated_time_minutes = data['estimated_time_minutes']

        if 'frequency_days' in data:

            template.frequency_days = data['frequency_days']

        if 'reminder_days' in data:

            template.reminder_days = data['reminder_days']

        if 'is_active' in data:

            template.is_active = data['is_active']

        if 'is_default' in data:

            template.is_default = data['is_default']

        template.updated_by = current_user.username if current_user.is_authenticated else 'system'

        template.updated_at = datetime.utcnow()

        template.update_item_count()  # 重新计算项目数量

        db.session.commit()

        log_audit('update', 'inspection_template', template_id, f"更新巡检模板: {template.name}", user_id=current_user.id if current_user.is_authenticated else None)

        return jsonify({'success': True, 'message': '模板更新成功'}), 200

    except Exception as e:

        db.session.rollback()

        return jsonify({'success': False, 'error': str(e)}), 500

@maintenance_bp.route('/api/inspection_templates/<int:template_id>', methods=['DELETE'])

@login_required

@permission_required('maintenance:edit')

def delete_inspection_template(template_id):

    """删除巡检模板（软删除，设置 is_active=False）"""

    try:

        template = InspectionTemplate.query.get_or_404(template_id)

        template.is_active = False

        template.updated_by = current_user.username if current_user.is_authenticated else 'system'

        template.updated_at = datetime.utcnow()

        db.session.commit()

        log_audit('delete', 'inspection_template', template_id, f"删除巡检模板: {template.name}", user_id=current_user.id if current_user.is_authenticated else None)

        return jsonify({'success': True, 'message': '模板已删除'}), 200

    except Exception as e:

        db.session.rollback()

        return jsonify({'success': False, 'error': str(e)}), 500

@maintenance_bp.route('/api/inspection_tasks', methods=['POST'])

@login_required

@permission_required('maintenance:edit')

def create_inspection_task_api():

    if not request.is_json:

        return jsonify({'success': False, 'error': '请求必须为 JSON 格式'}), 415

    try:

        data = request.get_json()

        # 必填字段验证

        required_fields = ['due_date', 'template_id']

        for field in required_fields:

            if field not in data or not data[field]:

                return jsonify({'success': False, 'error': f'缺少必填字段: {field}'}), 400

        title = data.get('name')

        if not title:

            return jsonify({'success': False, 'error': '缺少任务标题'}), 400

        template = InspectionTemplate.query.get(data['template_id'])

        if not template:

            return jsonify({'success': False, 'error': '模板不存在'}), 404

        try:

            from datetime import datetime

            due_date = datetime.strptime(data['due_date'], '%Y-%m-%d').date()

        except ValueError:

            return jsonify({'success': False, 'error': '日期格式错误，应为 YYYY-MM-DD'}), 400

        # 创建任务实例（将 description 存入 notes）

        task = InspectionTask(

            title=title,

            notes=data.get('description', ''),  # 关键修改

            template_id=template.id,

            scheduled_date=due_date,

            due_date=due_date,

            inspection_type=template.template_type,

            status='pending',

            created_by=current_user.username,

            updated_by=current_user.username

        )

        task.generate_task_number()

        db.session.add(task)

        db.session.commit()

        log_audit('create', 'inspection_task', task.id, f"创建巡检任务(API): {task.title}", user_id=current_user.id if current_user.is_authenticated else None)

        return jsonify({'success': True, 'id': task.id, 'message': '任务创建成功'}), 201

    except Exception as e:

        db.session.rollback()

        print(f"创建任务异常: {str(e)}")

        import traceback

        traceback.print_exc()

        return jsonify({'success': False, 'error': f'服务器内部错误: {str(e)}'}), 500

    except Exception as e:

        db.session.rollback()

        # 打印详细日志便于调试

        print(f"创建任务异常: {str(e)}")

        import traceback

        traceback.print_exc()

        return jsonify({'success': False, 'error': f'服务器内部错误: {str(e)}'}), 500

@maintenance_bp.route('/inspection/tasks/<int:task_id>/process', methods=['GET', 'POST'])

@login_required

@permission_required('maintenance:edit')

def process_inspection_task(task_id):

    """执行巡检任务，并把结果写入 InspectionResult。"""

    task = InspectionTask.query.get_or_404(task_id)

    # 权限检查：已指派任务只允许负责人处理；未指派任务允许有编辑权限的运维人员处理

    if task.assigned_to_id and task.assigned_to_id != current_user.id:

        flash('您无权处理此任务', 'danger')

        return redirect(url_for('maintenance.inspection_tasks'))

    if task.status in ('completed', 'cancelled'):

        flash('该任务已结束，不能重复处理', 'warning')

        return redirect(url_for('maintenance.inspection_task_detail', task_id=task.id))

    items = _inspection_items_for_task(task)

    if request.method == 'GET':

        return render_template('maintenance/process_inspection_task.html',

                               task=task, items=items)

    # POST：整理检查项结果

    checklist_results = []

    for idx, item in enumerate(items):

        result = request.form.get(f'item_{idx}_result') or 'skipped'

        remark = request.form.get(f'item_{idx}_remark', '').strip()

        checklist_results.append({

            'name': item.get('name', f'检查项{idx+1}'),

            'standard': item.get('standard', ''),

            'result': result,

            'remark': remark,

        })

    total_items = len(checklist_results)

    passed_items = sum(1 for r in checklist_results if r['result'] == 'passed')

    failed_items = sum(1 for r in checklist_results if r['result'] == 'failed')

    warning_items = sum(1 for r in checklist_results if r['result'] == 'warning')

    skipped_items = sum(1 for r in checklist_results if r['result'] == 'skipped')

    try:

        completion = float(request.form.get('completion_percentage') or 100)

    except ValueError:

        completion = 100

    completion_percentage = max(0.0, min(100.0, completion))

    # 有失败项时优先判定为 failed；没有失败但有警告则为 warning；否则 passed

    computed_result = request.form.get('overall_result', '').strip()

    if computed_result not in ('passed', 'warning', 'failed'):

        if failed_items > 0:

            computed_result = 'failed'

        elif warning_items > 0:

            computed_result = 'warning'

        else:

            computed_result = 'passed'

    now = datetime.utcnow()

    result = None

    if task.result_id:

        result = InspectionResult.query.get(task.result_id)

    if result is None:

        result = InspectionResult(task_id=task.id)

        result.generate_result_number()

    result.inspection_date = now.date()

    result.inspection_time = now.strftime('%H:%M')

    result.inspector_id = current_user.id

    result.inspector_name = current_user.username

    result.overall_result = computed_result

    result.checklist_items = json.dumps([{

        'name': item.get('name', f'检查项{i+1}'),

        'standard': item.get('standard', ''),

    } for i, item in enumerate(items)], ensure_ascii=False)

    result.checklist_results = json.dumps(checklist_results, ensure_ascii=False)

    result.total_items = total_items

    result.passed_items = passed_items

    result.failed_items = failed_items

    result.warning_items = warning_items

    result.skipped_items = skipped_items

    result.score = result.calculate_score()

    result.issues_found = request.form.get('issues_found', '').strip()

    result.recommendations = request.form.get('recommendations', '').strip()

    result.actions_taken = request.form.get('actions_taken', '').strip()

    result.follow_up_actions = request.form.get('follow_up_actions', '').strip()

    result.attachments = request.form.get('attachments', '').strip() or None

    result.photos = request.form.get('photos', '').strip() or None

    task.overall_result = result.overall_result

    task.checklist_items = result.checklist_items

    task.checklist_results = result.checklist_results

    task.issues_found = result.issues_found

    task.recommendations = result.recommendations

    task.completion_percentage = completion_percentage if completion_percentage < 100 else 100.0

    task.status = 'completed'

    task.actual_date = now.date()

    task.actual_time = now.strftime('%H:%M')

    task.updated_by = current_user.username

    task.updated_at = now

    if result.id is None:

        db.session.add(result)

    db.session.flush()

    task.result_id = result.id

    db.session.commit()

    log_audit('update', 'inspection_task', task.id,

              f"执行巡检任务: {task.task_number} -> {result.overall_result}",

              user_id=current_user.id if current_user.is_authenticated else None)

    flash(f'巡检结果已保存，总体结果：{result.overall_result}', 'success')

    return redirect(url_for('maintenance.inspection_result_detail', result_id=result.id))

@maintenance_bp.route('/inspection/tasks/<int:task_id>')

@login_required

@permission_required('maintenance:view')

def inspection_task_detail(task_id):

    """巡检任务详情"""

    task = InspectionTask.query.get_or_404(task_id)

    return render_template('maintenance/inspection_task_detail.html', task=task)

@maintenance_bp.route('/inspection/tasks/<int:task_id>/cancel', methods=['POST'])

@login_required

@permission_required('maintenance:edit')

def cancel_inspection_task(task_id):

    """取消巡检任务（处理表单提交）"""

    task = InspectionTask.query.get_or_404(task_id)

    # 权限检查：仅允许负责人取消；未指派任务允许有编辑权限的运维人员操作

    if task.assigned_to_id and task.assigned_to_id != current_user.id:

        flash('您无权取消此任务', 'danger')

        return redirect(url_for('maintenance.inspection_tasks'))

    # 状态检查：只允许在“待处理”或“进行中”状态下取消

    if task.status not in ['pending', 'in_progress']:

        flash(f'当前状态为 {task.status}，不允许取消', 'warning')

        return redirect(url_for('maintenance.inspection_tasks'))

    # 可选：从表单中获取取消原因（如果表单中有输入）

    # reason = request.form.get('reason', '')

    # task.cancel_reason = reason

    # 更新状态

    task.status = 'cancelled'

    db.session.commit()

    log_audit('update', 'inspection_task', task.id, f"取消巡检任务: {task.task_number}", user_id=current_user.id if current_user.is_authenticated else None)

    flash(f'任务 {task.task_number} 已成功取消', 'success')

    return redirect(url_for('maintenance.inspection_tasks'))

@maintenance_bp.route('/inspection/task/<int:task_id>/delete', methods=['POST'])

@login_required

@permission_required('maintenance:edit')

def delete_inspection_task(task_id):

    """删除巡检任务（级联删除关联的巡检结果）"""

    task = InspectionTask.query.get_or_404(task_id)

    number = task.task_number

    try:

        # 先解除 result 关联，再删除关联的 InspectionResult

        if task.result_id:

            result = InspectionResult.query.get(task.result_id)

            task.result_id = None

            if result:

                db.session.delete(result)

        db.session.delete(task)

        db.session.commit()

        log_audit('delete', 'inspection_task', task_id, f"删除巡检任务: {number}",

                  user_id=current_user.id if current_user.is_authenticated else None)

        flash(f'巡检任务 {number} 已删除', 'success')

    except Exception as e:

        db.session.rollback()

        flash(f'删除失败: {str(e)}', 'danger')

    return redirect(url_for('maintenance.inspection_tasks'))

# ============================================================

# 运维管理仪表板 / 维护计划 / 备件与供应商页面路由

# 这些页面模板原先存在但缺少后端 endpoint。

# ============================================================

def _parse_ids(raw):

    if not raw:

        return []

    try:

        data = json.loads(raw)

        return [int(i) for i in data]

    except Exception:

        return []

def _maintenance_task_view(task):

    user = User.query.get(task.assigned_to) if task.assigned_to else None

    device_ids = _parse_ids(task.device_ids)

    return SimpleNamespace(

        id=task.id,

        name=task.name,

        description=task.description,

        maintenance_type=task.maintenance_type,

        status=task.status,

        priority=task.priority,

        scheduled_date=task.scheduled_date,

        estimated_duration=task.estimated_duration,

        actual_duration=task.actual_duration,

        device_ids=json.dumps(device_ids),

        device_count=len(device_ids),

        assigned_to=task.assigned_to,

        assigned_to_user=SimpleNamespace(name=user.username if user else None),

        approval_required=bool(task.approval_required),

        approved_at=task.approved_at,

        completed_at=task.completed_at,

        notes=task.notes,

        created_at=task.created_at,

    )

def _spare_part_view(part):

    installed = part.installed_device

    supplier = part.supplier

    current_stock = int(part.current_stock or 0)

    min_stock = int(part.min_stock_level or 0)

    max_stock = int(part.max_stock_level or 0)

    if min_stock > 0:

        stock_status = 'low' if current_stock <= min_stock else ('excess' if (max_stock and current_stock > max_stock * 1.5) else 'normal')

    else:

        stock_status = 'normal'

    usage_percentage = 0

    if max_stock > 0:

        usage_percentage = min(100, int(current_stock / max_stock * 100))

    elif min_stock > 0:

        usage_percentage = min(100, int(current_stock / (min_stock * 3) * 100))

    return SimpleNamespace(

        id=part.id,

        asset_number=part.asset_number,

        part_number=part.asset_number,

        name=part.part_name or part.model or part.asset_number or f'SparePart {part.id}',

        part_name=part.part_name,

        model=part.model,

        vendor=part.manufacturer,

        description=part.notes,

        category=part.part_type,

        unit_price=float(part.unit_price or 0),

        current_stock=current_stock,

        min_stock_level=min_stock,

        max_stock_level=max_stock,

        stock_status=stock_status,

        is_low_stock=stock_status == 'low',

        usage_percentage=usage_percentage,

        location=part.warehouse_location,

        supplier_id=part.supplier_id,

        supplier=SimpleNamespace(id=supplier.id if supplier else None, name=supplier.name if supplier else (part.manufacturer or '-')),

        installed_device=SimpleNamespace(hostname=installed.name if installed else None),

        status=part.status,

        is_active=bool(part.is_active),

    )

def _spare_request_view(req):

    part = req.spare_part

    return SimpleNamespace(

        id=req.id,

        request_number=req.request_number,

        part=SimpleNamespace(

            id=part.id if part else None,

            name=part.part_name if part else '-',

            part_number=part.asset_number if part else '-',

            model=part.model if part else '',

            unit_price=float(part.unit_price or 0) if part else 0,

            current_stock=int(part.current_stock or 0) if part else 0,

            min_stock_level=int(part.min_stock_level or 0) if part else 0,

        ),

        quantity=req.quantity,

        purpose=req.reason,

        usage_description=req.usage_description,

        requested_by_user=SimpleNamespace(name=req.requester_name, username=req.requester_name),

        request_date=req.requested_at,

        urgency=req.urgency,

        status=req.status,

        approval_status=req.approval_status,

        approved_by=req.approved_by,

        approved_at=req.approved_at,

        notes=req.approval_notes or '',

        device=None,

        maintenance_task=None,

    )

@maintenance_bp.route('/dashboard')

@login_required

@permission_required('maintenance:view')

def maintenance_dashboard():

    """运维管理仪表板入口。"""

    return render_template('maintenance/dashboard.html')

@maintenance_bp.route('/maintenance_tasks')

@login_required

@permission_required('maintenance:view')

def maintenance_tasks():

    """维护任务列表页。"""

    tasks = MaintenanceTask.query.order_by(MaintenanceTask.scheduled_date.desc()).all()

    task_views = [_maintenance_task_view(t) for t in tasks]

    active_tasks = [t for t in task_views if t.status in ('scheduled', 'in_progress')]

    users = User.query.order_by(User.username).all()

    devices = Device.query.order_by(Device.name).all()

    return render_template('maintenance/maintenance_tasks.html',

                           tasks=task_views,

                           active_tasks=active_tasks,

                           users=users,

                           devices=devices,

                           status_class={

                               'scheduled': 'status-scheduled',

                               'in_progress': 'status-in-progress',

                               'completed': 'status-completed',

                               'cancelled': 'status-cancelled',

                           },

                           priority_class={

                               'low': 'priority-low',

                               'medium': 'priority-medium',

                               'high': 'priority-high',

                               'critical': 'priority-critical',

                           },

                           type_class={

                               'preventive': 'type-preventive',

                               'corrective': 'type-corrective',

                               'emergency': 'type-emergency',

                               'upgrade': 'type-upgrade',

                           })

@maintenance_bp.route('/maintenance_tasks/create', methods=['POST'])

@login_required

@permission_required('maintenance:edit')

def create_maintenance_task():

    """维护任务创建（表单提交）。"""

    try:

        device_ids = request.form.getlist('device_ids')

        task = MaintenanceTask(

            name=request.form.get('name', '').strip(),

            description=request.form.get('description', ''),

            maintenance_type=request.form.get('maintenance_type', 'preventive'),

            scheduled_date=datetime.fromisoformat(request.form.get('scheduled_date')),

            estimated_duration=int(request.form.get('estimated_duration') or 0),

            status=request.form.get('status', 'scheduled'),

            priority=request.form.get('priority', 'medium'),

            assigned_to=request.form.get('assigned_to', type=int) or None,

            approval_required=request.form.get('approval_required') == 'on',

            notes=request.form.get('notes', ''),

            device_ids=json.dumps([int(i) for i in device_ids]),

            created_by=current_user.id,

        )

        db.session.add(task)

        db.session.commit()

        log_audit('create', 'maintenance_task', task.id, f"创建维护任务: {task.name}",

                  user_id=current_user.id)

        flash(f'维护任务「{task.name}」已创建', 'success')

    except Exception as e:

        db.session.rollback()

        flash(f'创建失败: {str(e)}', 'danger')

    return redirect(url_for('maintenance.maintenance_tasks'))

@maintenance_bp.route('/maintenance_schedule')

@login_required

@permission_required('maintenance:view')

def maintenance_schedule():

    """维护计划/日历页。"""

    tasks = [_maintenance_task_view(t).__dict__ for t in MaintenanceTask.query.order_by(MaintenanceTask.scheduled_date.asc()).all()]

    return render_template('maintenance/maintenance_schedule.html', tasks=tasks)

@maintenance_bp.route('/spare_parts/inventory')

@login_required

@permission_required('maintenance:view')

def spare_parts_inventory():

    """备件库存页。"""

    parts = SparePart.query.order_by(SparePart.part_name.asc()).all()

    part_views = [_spare_part_view(p) for p in parts]

    low_stock_parts = [p for p in part_views if p.current_stock <= p.min_stock_level]

    total_value = sum(p.current_stock * p.unit_price for p in part_views)

    suppliers = Supplier.query.filter_by(is_active=True).order_by(Supplier.name.asc()).all()

    return render_template('maintenance/spare_parts_inventory.html',

                           parts=part_views,

                           low_stock_parts=low_stock_parts,

                           total_value=total_value,

                           suppliers=suppliers)

@maintenance_bp.route('/spare_parts/requests')

@login_required

@permission_required('maintenance:view')

def spare_parts_requests():

    """备件申请页。"""

    rows = SparePartRequest.query.order_by(SparePartRequest.requested_at.desc()).all()

    requests = [_spare_request_view(r) for r in rows]

    pending_requests = [r for r in requests if r.status in ('pending',)]

    parts = SparePart.query.filter_by(is_active=True).all()

    return render_template('maintenance/spare_parts_requests.html',

                           requests=requests,

                           pending_requests=pending_requests,

                           parts=[_spare_part_view(p) for p in parts])

@maintenance_bp.route('/spare_parts/usage')

@login_required

@permission_required('maintenance:view')

def spare_parts_usage():

    """备件使用统计页。"""

    usage_stats = []

    rows = db.session.query(

        SparePartUsage.spare_part_name,

        func.count(SparePartUsage.id).label('request_count'),

        func.coalesce(func.sum(SparePartUsage.quantity), 0).label('total_used'),

    ).group_by(SparePartUsage.spare_part_name).order_by(func.sum(SparePartUsage.quantity).desc()).all()

    for name, request_count, total_used in rows:

        usage_stats.append({

            'name': name or '-',

            'request_count': int(request_count or 0),

            'total_used': float(total_used or 0),

        })

    return render_template('maintenance/spare_parts_usage.html', usage_stats=usage_stats)

@maintenance_bp.route('/suppliers')

@login_required

@permission_required('maintenance:view')

def supplier_management():

    """供应商管理页。"""

    suppliers = Supplier.query.order_by(Supplier.name.asc()).all()

    return render_template('maintenance/supplier_management.html', suppliers=suppliers)

@maintenance_bp.route('/supplier/<int:supplier_id>/get')

@login_required

@permission_required('maintenance:view')

def get_supplier(supplier_id):

    supplier = Supplier.query.get_or_404(supplier_id)

    return jsonify({'success': True, 'supplier': supplier.to_dict()})

@maintenance_bp.route('/supplier/add', methods=['POST'])

@login_required

@permission_required('maintenance:edit')

def add_supplier():

    supplier = Supplier(

        name=request.form.get('name', '').strip(),

        contact_person=request.form.get('contact_person', '').strip(),

        email=request.form.get('email', '').strip(),

        phone=request.form.get('phone', '').strip(),

        address=request.form.get('address', '').strip(),

        website=request.form.get('website', '').strip(),

        rating=request.form.get('rating', type=int),

        lead_time=request.form.get('lead_time', type=int),

        payment_terms=request.form.get('payment_terms', '').strip(),

        notes=request.form.get('notes', '').strip(),

        is_active=request.form.get('is_active', 'true') == 'true',

    )

    if not supplier.name:

        return jsonify({'success': False, 'error': '供应商名称不能为空'}), 400

    db.session.add(supplier)

    db.session.commit()

    log_audit('create', 'supplier', supplier.id, f"创建供应商: {supplier.name}",

              user_id=current_user.id)

    return jsonify({'success': True, 'supplier': supplier.to_dict()})

@maintenance_bp.route('/supplier/edit', methods=['POST'])

@login_required

@permission_required('maintenance:edit')

def edit_supplier():

    supplier_id = request.form.get('id', type=int)

    supplier = Supplier.query.get_or_404(supplier_id)

    supplier.name = request.form.get('name', supplier.name).strip()

    supplier.contact_person = request.form.get('contact_person', supplier.contact_person)

    supplier.email = request.form.get('email', supplier.email)

    supplier.phone = request.form.get('phone', supplier.phone)

    supplier.address = request.form.get('address', supplier.address)

    supplier.website = request.form.get('website', supplier.website)

    supplier.rating = request.form.get('rating', type=int) if request.form.get('rating') not in (None, '') else supplier.rating

    supplier.lead_time = request.form.get('lead_time', type=int) if request.form.get('lead_time') not in (None, '') else supplier.lead_time

    supplier.payment_terms = request.form.get('payment_terms', supplier.payment_terms)

    supplier.notes = request.form.get('notes', supplier.notes)

    supplier.is_active = request.form.get('is_active', 'true') == 'true'

    db.session.commit()

    log_audit('update', 'supplier', supplier.id, f"更新供应商: {supplier.name}",

              user_id=current_user.id)

    return jsonify({'success': True, 'supplier': supplier.to_dict()})

@maintenance_bp.route('/supplier/<int:supplier_id>/delete', methods=['POST'])

@login_required

@permission_required('maintenance:edit')

def delete_supplier(supplier_id):

    supplier = Supplier.query.get_or_404(supplier_id)

    name = supplier.name

    db.session.delete(supplier)

    db.session.commit()

    log_audit('delete', 'supplier', supplier_id, f"删除供应商: {name}",

              user_id=current_user.id)

    return jsonify({'success': True, 'message': '供应商已删除'})
