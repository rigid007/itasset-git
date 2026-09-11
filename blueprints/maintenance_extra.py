"""

maintenance_extra.py - 运维管理扩展

问题管理 / 已知错误 / 服务目录 / 知识库

"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify

from flask_login import login_required, current_user

from datetime import datetime
import uuid

from extensions import db

from models.maintenance_models import ProblemRecord, KnownError, ServiceCatalog, KnowledgeArticle, SLAPolicy

from utils.audit import log_audit

from utils.permission import permission_required



maintenance_extra_bp = Blueprint('maintenance_extra', __name__, url_prefix='/maintenance')





# ==================== 问题管理 ====================



@maintenance_extra_bp.route('/problems')

@login_required

@permission_required('maintenance:view')

def problem_list():

    """问题列表"""

    page = request.args.get('page', 1, type=int)

    status = request.args.get('status', '')

    query = ProblemRecord.query

    if status:

        query = query.filter_by(status=status)

    problems = query.order_by(ProblemRecord.identified_date.desc()).paginate(page=page, per_page=20)



    counts = {

        'identified': ProblemRecord.query.filter_by(status='identified').count(),

        'investigating': ProblemRecord.query.filter_by(status='investigating').count(),

        'resolved': ProblemRecord.query.filter_by(status='resolved').count(),

        'closed': ProblemRecord.query.filter_by(status='closed').count(),

    }

    return render_template('maintenance/problem_list.html', problems=problems, counts=counts, status=status)





@maintenance_extra_bp.route('/problem/create', methods=['GET', 'POST'])

@login_required

@permission_required('maintenance:edit')

def problem_create():

    """创建问题"""

    if request.method == 'POST':

        from models.maintenance_models import WorkOrder

        try:

            work_order_ids = request.form.getlist('work_order_ids')

            problem = ProblemRecord(

                problem_number=f'PR{datetime.utcnow().strftime("%Y%m%d%H%M%S")}{uuid.uuid4().hex[:4].upper()}',

                title=(request.form.get('title') or '').strip(),

                description=request.form.get('description', ''),

                category=request.form.get('category', ''),

                severity=request.form.get('severity', 'medium'),

                priority=request.form.get('priority', 'medium'),

                status='identified',

                related_work_order_ids=str([int(w) for w in work_order_ids]) if work_order_ids else '[]',

                identified_date=datetime.utcnow(),

                assigned_to=request.form.get('assigned_to', type=int),

                device_id=request.form.get('device_id', type=int) or None,

                asset_id=request.form.get('asset_id', type=int) or None,

                created_by=current_user.id,

            )

            db.session.add(problem)

            db.session.commit()

            log_audit('create', 'problem', problem.id, f"创建问题: {problem.title}", user_id=current_user.id if current_user.is_authenticated else None)

            flash('问题已创建', 'success')

            return redirect(url_for('maintenance_extra.problem_list'))

        except Exception as e:

            db.session.rollback()

            flash(f'创建失败: {str(e)}', 'danger')



    from models.models import User, Device

    from models.maintenance_models import WorkOrder, Asset

    users = User.query.filter_by(is_active=True).all()

    work_orders = WorkOrder.query.filter(WorkOrder.status.in_(['open', 'in_progress'])).all()

    devices = Device.query.order_by(Device.name).all()

    assets = Asset.query.order_by(Asset.asset_name).all()

    return render_template('maintenance/problem_form.html', problem=None, users=users,

                           work_orders=work_orders, devices=devices, assets=assets)





@maintenance_extra_bp.route('/problem/<int:id>')

@login_required

@permission_required('maintenance:view')

def problem_detail(id):

    """问题详情"""

    problem = ProblemRecord.query.get_or_404(id)

    return render_template('maintenance/problem_detail.html', problem=problem)





@maintenance_extra_bp.route('/problem/<int:id>/update-status', methods=['POST'])

@login_required

@permission_required('maintenance:edit')

def problem_update_status(id):

    """更新问题状态"""

    problem = ProblemRecord.query.get_or_404(id)

    new_status = request.form.get('status')

    if new_status in ('identified', 'investigating', 'resolved', 'closed'):

        problem.status = new_status

        if new_status == 'resolved':

            problem.resolved_date = datetime.utcnow()

            problem.root_cause = request.form.get('root_cause', problem.root_cause)

            problem.resolution = request.form.get('resolution', problem.resolution)

        db.session.commit()

        log_audit('update', 'problem', id, f"更新问题状态: {problem.title} -> {new_status}", user_id=current_user.id if current_user.is_authenticated else None)

        flash(f'状态已更新为: {new_status}', 'success')

    return redirect(url_for('maintenance_extra.problem_detail', id=problem.id))





@maintenance_extra_bp.route('/problem/<int:id>/edit', methods=['GET', 'POST'])

@login_required

@permission_required('maintenance:edit')

def problem_edit(id):

    """编辑问题"""

    problem = ProblemRecord.query.get_or_404(id)

    if request.method == 'POST':

        from models.maintenance_models import WorkOrder

        try:

            work_order_ids = request.form.getlist('work_order_ids')

            problem.title = (request.form.get('title') or '').strip()

            problem.description = request.form.get('description', '')

            problem.category = request.form.get('category', '')

            problem.severity = request.form.get('severity', 'medium')

            problem.priority = request.form.get('priority', 'medium')

            problem.related_work_order_ids = str([int(w) for w in work_order_ids]) if work_order_ids else '[]'

            problem.assigned_to = request.form.get('assigned_to', type=int)

            problem.device_id = request.form.get('device_id', type=int) or None

            problem.asset_id = request.form.get('asset_id', type=int) or None

            new_status = request.form.get('status', problem.status)

            if new_status in ('identified', 'investigating', 'resolved', 'closed'):

                if new_status == 'resolved' and problem.status != 'resolved':

                    problem.resolved_date = datetime.utcnow()

                problem.status = new_status

            if new_status == 'resolved':

                problem.root_cause = request.form.get('root_cause', problem.root_cause)

                problem.resolution = request.form.get('resolution', problem.resolution)

            db.session.commit()

            log_audit('update', 'problem', id, f"编辑问题: {problem.title}", user_id=current_user.id)

            flash('问题已更新', 'success')

            return redirect(url_for('maintenance_extra.problem_detail', id=problem.id))

        except Exception as e:

            db.session.rollback()

            flash(f'更新失败: {str(e)}', 'danger')



    from models.models import User, Device

    from models.maintenance_models import WorkOrder, Asset

    users = User.query.filter_by(is_active=True).all()

    work_orders = WorkOrder.query.all()

    devices = Device.query.order_by(Device.name).all()

    assets = Asset.query.order_by(Asset.asset_name).all()

    import json

    try:

        linked_ids = json.loads(problem.related_work_order_ids) if problem.related_work_order_ids else []

    except (json.JSONDecodeError, TypeError):

        linked_ids = []

    return render_template('maintenance/problem_form.html', problem=problem, users=users,

                           work_orders=work_orders, linked_ids=linked_ids,

                           devices=devices, assets=assets)





@maintenance_extra_bp.route('/problem/<int:id>/delete', methods=['POST'])

@login_required

@permission_required('maintenance:edit')

def problem_delete(id):

    """删除问题"""

    problem = ProblemRecord.query.get_or_404(id)

    title = problem.title

    try:

        db.session.delete(problem)

        db.session.commit()

        log_audit('delete', 'problem', id, f"删除问题: {title}", user_id=current_user.id)

        flash(f'问题 "{title}" 已删除', 'success')

    except Exception as e:

        db.session.rollback()

        flash(f'删除失败: {str(e)}', 'danger')

    return redirect(url_for('maintenance_extra.problem_list'))





# ==================== 已知错误 ====================



@maintenance_extra_bp.route('/known-errors')

@login_required

@permission_required('maintenance:view')

def known_errors():

    """已知错误列表"""

    errors = KnownError.query.order_by(KnownError.created_at.desc()).all()

    problems = ProblemRecord.query.filter(ProblemRecord.status.in_(['identified', 'investigating'])).all()

    return render_template('maintenance/known_errors.html', errors=errors, problems=problems)





@maintenance_extra_bp.route('/known-error/add', methods=['POST'])

@login_required

@permission_required('maintenance:edit')

def known_error_add():

    """添加已知错误"""

    try:

        ke = KnownError(

            ke_number=f'KE{datetime.utcnow().strftime("%Y%m%d%H%M%S")}{uuid.uuid4().hex[:4].upper()}',

            title=(request.form.get('title') or '').strip(),

            description=request.form.get('description', ''),

            symptom=request.form.get('symptom', ''),

            root_cause=request.form.get('root_cause', ''),

            workaround=request.form.get('workaround', ''),

            severity=request.form.get('severity', 'medium'),

            status='active',

            linked_problem_id=request.form.get('linked_problem_id', type=int),

        )

        db.session.add(ke)

        db.session.commit()

        log_audit('create', 'known_error', ke.id, f"添加已知错误: {ke.title}", user_id=current_user.id if current_user.is_authenticated else None)

        flash('已知错误已记录', 'success')

    except Exception as e:

        db.session.rollback()

        flash(f'添加失败: {str(e)}', 'danger')

    return redirect(url_for('maintenance_extra.known_errors'))





# ==================== 服务目录 ====================



@maintenance_extra_bp.route('/service-catalog')

@login_required

@permission_required('maintenance:view')

def service_catalog():

    """服务目录"""

    catalogs = ServiceCatalog.query.order_by(ServiceCatalog.display_order).all()

    sla_policies = SLAPolicy.query.filter_by(is_active=True).all()

    # 服务级 CSAT 概览

    csat_map = {}

    for s in catalogs:

        surveys = s.csat_surveys.all()

        ratings = [x.rating for x in surveys if x.rating]

        csat_map[s.id] = {

            'avg': round(sum(ratings) / len(ratings), 2) if ratings else None,

            'count': len(ratings),

        }

    from models.models import Device

    devices = Device.query.order_by(Device.name).all()

    return render_template('maintenance/service_catalog.html', catalogs=catalogs,

                           sla_policies=sla_policies, csat_map=csat_map, devices=devices)





@maintenance_extra_bp.route('/service-catalog/add', methods=['POST'])

@login_required

@permission_required('maintenance:edit')

def service_catalog_add():

    """添加服务"""

    try:

        sc = ServiceCatalog(

            name=request.form['name'],

            description=request.form.get('description', ''),

            category=request.form.get('category', 'request'),

            service_type=request.form.get('service_type', 'request'),

            estimated_fulfillment_time=request.form.get('estimated_fulfillment_time', 60, type=int),

            enabled=True,

            created_by=current_user.id,

        )

        db.session.add(sc)

        db.session.commit()

        log_audit('create', 'service_catalog', sc.id, f"添加服务: {sc.name}", user_id=current_user.id if current_user.is_authenticated else None)

        flash('服务已添加', 'success')

    except Exception as e:

        db.session.rollback()

        flash(f'添加失败: {str(e)}', 'danger')

    return redirect(url_for('maintenance_extra.service_catalog'))





# ==================== 知识库 ====================



@maintenance_extra_bp.route('/knowledge-base')

@login_required

@permission_required('maintenance:view')

def knowledge_base():

    """知识库 (仅已发布)"""

    page = request.args.get('page', 1, type=int)

    search = request.args.get('search', '')

    query = KnowledgeArticle.query.filter_by(status='published')

    if search:

        query = query.filter(

            db.or_(KnowledgeArticle.title.ilike(f'%{search}%'),

                   KnowledgeArticle.content.ilike(f'%{search}%'))

        )

    articles = query.order_by(KnowledgeArticle.created_at.desc()).paginate(page=page, per_page=20)

    return render_template('maintenance/knowledge_base.html', articles=articles, search=search)





@maintenance_extra_bp.route('/knowledge-base/manage')

@login_required

@permission_required('maintenance:edit')

def kb_manage():

    """知识库管理 (含草稿/归档)"""

    page = request.args.get('page', 1, type=int)

    status = request.args.get('status', '')

    search = request.args.get('search', '')

    query = KnowledgeArticle.query

    if status:

        query = query.filter_by(status=status)

    if search:

        query = query.filter(

            db.or_(KnowledgeArticle.title.ilike(f'%{search}%'),

                   KnowledgeArticle.content.ilike(f'%{search}%'))

        )

    articles = query.order_by(KnowledgeArticle.updated_at.desc()).paginate(page=page, per_page=20)

    counts = {

        'draft': KnowledgeArticle.query.filter_by(status='draft').count(),

        'published': KnowledgeArticle.query.filter_by(status='published').count(),

        'archived': KnowledgeArticle.query.filter_by(status='archived').count(),

    }

    return render_template('maintenance/knowledge_base.html', articles=articles, search=search,

                           manage=True, counts=counts, current_status=status)





@maintenance_extra_bp.route('/kb/create', methods=['GET', 'POST'])

@login_required

@permission_required('maintenance:edit')

def kb_create():

    """创建知识文章"""

    if request.method == 'POST':

        try:

            article = KnowledgeArticle(

                title=(request.form.get('title') or '').strip(),

                content=request.form.get('content', ''),

                category=request.form.get('category', ''),

                tags=request.form.get('tags', ''),

                device_type=request.form.get('device_type', ''),

                vendor=request.form.get('vendor', ''),

                model=request.form.get('model', ''),

                author_id=current_user.id,

                status=request.form.get('status', 'draft'),

                is_featured=request.form.get('is_featured') == 'on',

            )

            if article.status == 'published':

                article.published_at = datetime.utcnow()

            db.session.add(article)

            db.session.commit()

            log_audit('create', 'knowledge_article', article.id,

                      f"创建知识文章: {article.title}", user_id=current_user.id)

            flash('文章已创建', 'success')

            return redirect(url_for('maintenance_extra.kb_article', id=article.id))

        except Exception as e:

            db.session.rollback()

            flash(f'创建失败: {str(e)}', 'danger')



    return render_template('maintenance/kb_form.html', article=None)





@maintenance_extra_bp.route('/kb/<int:id>/edit', methods=['GET', 'POST'])

@login_required

@permission_required('maintenance:edit')

def kb_edit(id):

    """编辑知识文章"""

    article = KnowledgeArticle.query.get_or_404(id)

    if request.method == 'POST':

        try:

            article.title = (request.form.get('title') or '').strip()

            article.content = request.form.get('content', '')

            article.category = request.form.get('category', '')

            article.tags = request.form.get('tags', '')

            article.device_type = request.form.get('device_type', '')

            article.vendor = request.form.get('vendor', '')

            article.model = request.form.get('model', '')

            article.is_featured = request.form.get('is_featured') == 'on'

            new_status = request.form.get('status', article.status)

            if new_status == 'published' and article.status != 'published':

                article.published_at = datetime.utcnow()

            article.status = new_status

            db.session.commit()

            log_audit('update', 'knowledge_article', id,

                      f"编辑知识文章: {article.title}", user_id=current_user.id)

            flash('文章已更新', 'success')

            return redirect(url_for('maintenance_extra.kb_article', id=article.id))

        except Exception as e:

            db.session.rollback()

            flash(f'更新失败: {str(e)}', 'danger')



    return render_template('maintenance/kb_form.html', article=article)





@maintenance_extra_bp.route('/kb/<int:id>/delete', methods=['POST'])

@login_required

@permission_required('maintenance:edit')

def kb_delete(id):

    """删除知识文章"""

    article = KnowledgeArticle.query.get_or_404(id)

    title = article.title

    try:

        db.session.delete(article)

        db.session.commit()

        log_audit('delete', 'knowledge_article', id,

                  f"删除知识文章: {title}", user_id=current_user.id)

        flash(f'文章 "{title}" 已删除', 'success')

    except Exception as e:

        db.session.rollback()

        flash(f'删除失败: {str(e)}', 'danger')

    return redirect(url_for('maintenance_extra.kb_manage'))





@maintenance_extra_bp.route('/kb/<int:id>/feedback', methods=['POST'])

@login_required

@permission_required('maintenance:view')

def kb_feedback(id):

    """Record helpful/not-helpful feedback for a knowledge article."""

    article = KnowledgeArticle.query.get_or_404(id)

    feedback = request.form.get('feedback', 'helpful')

    if feedback == 'helpful':

        article.helpful_count = int(article.helpful_count or 0) + 1

    elif feedback == 'not_helpful':

        article.not_helpful_count = int(article.not_helpful_count or 0) + 1

    else:

        flash('Invalid feedback type', 'warning')

        return redirect(url_for('maintenance_extra.kb_article', id=article.id))

    db.session.commit()

    flash('Thank you for your feedback', 'success')

    return redirect(url_for('maintenance_extra.kb_article', id=article.id))





@maintenance_extra_bp.route('/kb/article/<int:id>')

@login_required

@permission_required('maintenance:view')

def kb_article(id):

    """文章详情"""

    article = KnowledgeArticle.query.get_or_404(id)

    if article.view_count is None:

        article.view_count = 0

    article.view_count += 1

    db.session.commit()

    return render_template('maintenance/kb_article.html', article=article)

