"""
asset_extra.py - 资产管理扩展蓝图
合同管理 / 软件许可管理 / 资产盘点 路由
"""
import json, os
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
from datetime import datetime, date
from sqlalchemy import func
from extensions import db
from models.maintenance_models import Asset, Supplier
from models.contract_models import Contract, contract_assets
from models.license_models import SoftwareLicense, license_devices
from models.audit_models import AssetAudit, AssetAuditItem
from models.models import Device, User
from utils.audit import log_audit
from utils.permission import permission_required

asset_extra_bp = Blueprint('asset_extra', __name__, url_prefix='/asset')


# ==================== 合同管理 ====================

@asset_extra_bp.route('/contracts')
@login_required
@permission_required('asset:view')
def contract_list():
    """合同列表"""
    page = request.args.get('page', 1, type=int)
    per_page = 20
    search = request.args.get('search', '')
    status_filter = request.args.get('status', '')
    type_filter = request.args.get('type', '')

    query = Contract.query
    if search:
        query = query.filter(
            db.or_(Contract.name.ilike(f'%{search}%'), Contract.contract_no.ilike(f'%{search}%'))
        )
    if status_filter:
        query = query.filter(Contract.status == status_filter)
    if type_filter:
        query = query.filter(Contract.contract_type == type_filter)

    contracts = query.order_by(Contract.end_date.asc()).paginate(page=page, per_page=per_page)

    # 统计
    total = Contract.query.count()
    active_count = Contract.query.filter_by(status='active').count()
    expiring_soon = sum(1 for c in Contract.query.filter_by(status='active').all() if c.is_expiring_soon())

    return render_template('asset/contract_list.html',
                           contracts=contracts, search=search,
                           status_filter=status_filter, type_filter=type_filter,
                           total=total, active_count=active_count, expiring_soon=expiring_soon)


@asset_extra_bp.route('/contract/add', methods=['GET', 'POST'])
@login_required
@permission_required('asset:edit')
def contract_add():
    """添加合同"""
    if request.method == 'POST':
        try:
            contract = Contract(
                contract_no=request.form['contract_no'],
                name=request.form['name'],
                contract_type=request.form['contract_type'],
                supplier_id=request.form.get('supplier_id', type=int),
                start_date=datetime.strptime(request.form['start_date'], '%Y-%m-%d').date(),
                end_date=datetime.strptime(request.form['end_date'], '%Y-%m-%d').date(),
                renewal_date=datetime.strptime(request.form['renewal_date'], '%Y-%m-%d').date() if request.form.get('renewal_date') else None,
                total_value=request.form.get('total_value', 0, type=float),
                payment_terms=request.form.get('payment_terms', ''),
                payment_status=request.form.get('payment_status', 'pending'),
                description=request.form.get('description', ''),
                status='active',
                notification_days=request.form.get('notification_days', 30, type=int),
                created_by=current_user.id,
            )
            db.session.add(contract)
            db.session.commit()

            # 关联资产
            asset_ids = request.form.getlist('asset_ids')
            if asset_ids:
                assets = Asset.query.filter(Asset.id.in_([int(a) for a in asset_ids])).all()
                contract.assets.extend(assets)
                db.session.commit()
                log_audit('update', 'contract', contract.id, f"合同关联资产: {contract.name}", user_id=current_user.id if current_user.is_authenticated else None)

            log_audit('create', 'contract', contract.id, f"添加合同: {contract.name}", user_id=current_user.id if current_user.is_authenticated else None)
            flash('合同添加成功', 'success')
            return redirect(url_for('asset_extra.contract_list'))
        except Exception as e:
            db.session.rollback()
            flash(f'添加失败: {str(e)}', 'danger')

    suppliers = Supplier.query.filter_by(is_active=True).all()
    assets = Asset.query.filter_by(is_active=True).all()
    return render_template('asset/contract_form.html', contract=None, suppliers=suppliers, assets=assets)


@asset_extra_bp.route('/contract/<int:id>')
@login_required
@permission_required('asset:view')
def contract_detail(id):
    """合同详情"""
    contract = Contract.query.get_or_404(id)
    return render_template('asset/contract_detail.html', contract=contract)


@asset_extra_bp.route('/contract/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@permission_required('asset:edit')
def contract_edit(id):
    """编辑合同"""
    contract = Contract.query.get_or_404(id)
    if request.method == 'POST':
        try:
            contract.contract_no = request.form['contract_no']
            contract.name = request.form['name']
            contract.contract_type = request.form['contract_type']
            contract.supplier_id = request.form.get('supplier_id', type=int)
            contract.start_date = datetime.strptime(request.form['start_date'], '%Y-%m-%d').date()
            contract.end_date = datetime.strptime(request.form['end_date'], '%Y-%m-%d').date()
            contract.renewal_date = datetime.strptime(request.form['renewal_date'], '%Y-%m-%d').date() if request.form.get('renewal_date') else None
            contract.total_value = request.form.get('total_value', 0, type=float)
            contract.payment_terms = request.form.get('payment_terms', '')
            contract.payment_status = request.form.get('payment_status', 'pending')
            contract.description = request.form.get('description', '')
            contract.status = request.form.get('status', 'active')
            contract.notification_days = request.form.get('notification_days', 30, type=int)

            # 更新关联资产
            asset_ids = [int(a) for a in request.form.getlist('asset_ids')]
            contract.assets = Asset.query.filter(Asset.id.in_(asset_ids)).all() if asset_ids else []

            db.session.commit()
            log_audit('update', 'contract', contract.id, f"编辑合同: {contract.name}", user_id=current_user.id if current_user.is_authenticated else None)
            flash('合同更新成功', 'success')
            return redirect(url_for('asset_extra.contract_detail', id=contract.id))
        except Exception as e:
            db.session.rollback()
            flash(f'更新失败: {str(e)}', 'danger')

    suppliers = Supplier.query.filter_by(is_active=True).all()
    assets = Asset.query.filter_by(is_active=True).all()
    return render_template('asset/contract_form.html', contract=contract, suppliers=suppliers, assets=assets)


@asset_extra_bp.route('/contract/<int:id>/delete', methods=['POST'])
@login_required
@permission_required('asset:edit')
def contract_delete(id):
    """删除合同"""
    contract = Contract.query.get_or_404(id)
    try:
        contract.assets = []
        db.session.delete(contract)
        db.session.commit()
        log_audit('delete', 'contract', id, f"删除合同: {contract.name}", user_id=current_user.id if current_user.is_authenticated else None)
        flash('合同已删除', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'删除失败: {str(e)}', 'danger')
    return redirect(url_for('asset_extra.contract_list'))


@asset_extra_bp.route('/contract/api/expiring')
@login_required
@permission_required('asset:view')
def contract_api_expiring():
    """即将到期合同API"""
    days = request.args.get('days', 30, type=int)
    contracts = Contract.query.filter(Contract.status == 'active').all()
    result = [c.to_dict() for c in contracts if c.is_expiring_soon()]
    return jsonify({'contracts': result, 'total': len(result)})


# ==================== 软件许可管理 ====================

@asset_extra_bp.route('/licenses')
@login_required
@permission_required('asset:view')
def license_list():
    """许可列表"""
    page = request.args.get('page', 1, type=int)
    per_page = 20
    search = request.args.get('search', '')

    query = SoftwareLicense.query
    if search:
        query = query.filter(SoftwareLicense.software_name.ilike(f'%{search}%'))

    licenses = query.order_by(SoftwareLicense.expiry_date.asc()).paginate(page=page, per_page=per_page)

    # 合规统计
    compliant = SoftwareLicense.query.filter_by(compliance_status='compliant').count()
    non_compliant = SoftwareLicense.query.filter_by(compliance_status='non-compliant').count()
    expiring = sum(1 for l in SoftwareLicense.query.all() if l.is_expiring_soon())

    return render_template('asset/license_list.html',
                           licenses=licenses, search=search,
                           compliant=compliant, non_compliant=non_compliant, expiring=expiring)


@asset_extra_bp.route('/license/add', methods=['GET', 'POST'])
@login_required
@permission_required('asset:edit')
def license_add():
    """添加许可"""
    if request.method == 'POST':
        try:
            lic = SoftwareLicense(
                license_key=request.form.get('license_key', ''),
                software_name=request.form['software_name'],
                version=request.form.get('version', ''),
                edition=request.form.get('edition', ''),
                license_type=request.form['license_type'],
                vendor=request.form.get('vendor', ''),
                publisher=request.form.get('publisher', ''),
                total_quantity=request.form.get('total_quantity', 1, type=int),
                purchase_date=datetime.strptime(request.form['purchase_date'], '%Y-%m-%d').date() if request.form.get('purchase_date') else None,
                expiry_date=datetime.strptime(request.form['expiry_date'], '%Y-%m-%d').date() if request.form.get('expiry_date') else None,
                purchase_cost=request.form.get('purchase_cost', 0, type=float),
                unit_cost=request.form.get('unit_cost', 0, type=float),
                contract_id=request.form.get('contract_id', type=int),
                description=request.form.get('description', ''),
                status='active',
                compliance_status='compliant',
                created_by=current_user.id,
            )
            lic.available_quantity = lic.total_quantity
            db.session.add(lic)
            db.session.commit()
            log_audit('create', 'license', lic.id, f"添加许可证: {lic.software_name}", user_id=current_user.id if current_user.is_authenticated else None)
            flash('许可添加成功', 'success')
            return redirect(url_for('asset_extra.license_list'))
        except Exception as e:
            db.session.rollback()
            flash(f'添加失败: {str(e)}', 'danger')

    contracts = Contract.query.filter_by(status='active').all()
    devices = Device.query.all()
    return render_template('asset/license_form.html', license=None, contracts=contracts, devices=devices)


@asset_extra_bp.route('/license/<int:id>')
@login_required
@permission_required('asset:view')
def license_detail(id):
    """许可详情"""
    lic = SoftwareLicense.query.get_or_404(id)
    devices = Device.query.order_by(Device.name).all()
    return render_template('asset/license_detail.html', license=lic, devices=devices)


@asset_extra_bp.route('/license/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@permission_required('asset:edit')
def license_edit(id):
    """编辑许可"""
    lic = SoftwareLicense.query.get_or_404(id)
    if request.method == 'POST':
        try:
            lic.license_key = request.form.get('license_key', '')
            lic.software_name = request.form['software_name']
            lic.version = request.form.get('version', '')
            lic.edition = request.form.get('edition', '')
            lic.license_type = request.form['license_type']
            lic.vendor = request.form.get('vendor', '')
            lic.publisher = request.form.get('publisher', '')
            lic.total_quantity = request.form.get('total_quantity', 1, type=int)
            lic.purchase_cost = request.form.get('purchase_cost', 0, type=float)
            lic.unit_cost = request.form.get('unit_cost', 0, type=float)
            lic.contract_id = request.form.get('contract_id', type=int)
            lic.description = request.form.get('description', '')
            lic.status = request.form.get('status', 'active')
            lic.compliance_status = request.form.get('compliance_status', 'compliant')
            lic.update_quantities()
            db.session.commit()
            log_audit('update', 'license', lic.id, f"编辑许可证: {lic.software_name}", user_id=current_user.id if current_user.is_authenticated else None)
            flash('许可更新成功', 'success')
            return redirect(url_for('asset_extra.license_detail', id=lic.id))
        except Exception as e:
            db.session.rollback()
            flash(f'更新失败: {str(e)}', 'danger')

    contracts = Contract.query.filter_by(status='active').all()
    devices = Device.query.all()
    return render_template('asset/license_form.html', license=lic, contracts=contracts, devices=devices)


@asset_extra_bp.route('/license/<int:id>/delete', methods=['POST'])
@login_required
@permission_required('asset:edit')
def license_delete(id):
    """删除许可"""
    lic = SoftwareLicense.query.get_or_404(id)
    try:
        lic.devices = []
        db.session.delete(lic)
        db.session.commit()
        log_audit('delete', 'license', id, f"删除许可证: {lic.software_name}", user_id=current_user.id if current_user.is_authenticated else None)
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
            return jsonify({'success': True, 'message': '许可已删除'})
        flash('许可已删除', 'success')
    except Exception as e:
        db.session.rollback()
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
            return jsonify({'success': False, 'message': str(e)})
        flash(f'删除失败: {str(e)}', 'danger')
    return redirect(url_for('asset_extra.license_list'))


@asset_extra_bp.route('/license/<int:id>/allocate', methods=['POST'])
@login_required
@permission_required('asset:edit')
def license_allocate(id):
    """分配许可到设备"""
    lic = SoftwareLicense.query.get_or_404(id)
    device_ids = request.form.getlist('device_ids')

    try:
        if device_ids:
            devices = Device.query.filter(Device.id.in_([int(d) for d in device_ids])).all()
            # 检查数量
            if len(devices) + lic.allocated_quantity > lic.total_quantity:
                flash(f'超出许可数量限制(总数{lic.total_quantity}，已分配{lic.allocated_quantity})', 'warning')
                return redirect(url_for('asset_extra.license_detail', id=lic.id))
            lic.devices.extend(devices)
            lic.update_quantities()
            db.session.commit()
            log_audit('execute', 'license', lic.id, f"分配许可到设备: {lic.software_name}",
                      details={'device_count': len(devices)},
                      user_id=current_user.id if current_user.is_authenticated else None)
            flash(f'已分配{len(devices)}台设备', 'success')
        else:
            flash('请选择设备', 'warning')
    except Exception as e:
        db.session.rollback()
        flash(f'分配失败: {str(e)}', 'danger')

    return redirect(url_for('asset_extra.license_detail', id=lic.id))


@asset_extra_bp.route('/license/<int:id>/deallocate/<int:device_id>', methods=['POST'])
@login_required
@permission_required('asset:edit')
def license_deallocate(id, device_id):
    """取消设备许可分配"""
    lic = SoftwareLicense.query.get_or_404(id)
    device = Device.query.get_or_404(device_id)
    try:
        lic.devices.remove(device)
        lic.update_quantities()
        db.session.commit()
        log_audit('execute', 'license', lic.id, f"取消许可分配: {lic.software_name}",
                  details={'device_id': device_id},
                  user_id=current_user.id if current_user.is_authenticated else None)
        flash('已取消分配', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'操作失败: {str(e)}', 'danger')
    return redirect(url_for('asset_extra.license_detail', id=lic.id))


# ==================== 资产盘点 ====================

@asset_extra_bp.route('/audits')
@login_required
@permission_required('asset:view')
def audit_list():
    """盘点列表"""
    page = request.args.get('page', 1, type=int)
    audits = AssetAudit.query.order_by(AssetAudit.created_at.desc()).paginate(page=page, per_page=20)

    # 统计
    in_progress_count = AssetAudit.query.filter_by(status='in_progress').count()
    completed_count = AssetAudit.query.filter_by(status='completed').count()
    draft_count = AssetAudit.query.filter_by(status='draft').count()

    return render_template('asset/audit_list.html',
                           audits=audits,
                           in_progress_count=in_progress_count,
                           completed_count=completed_count,
                           draft_count=draft_count)


@asset_extra_bp.route('/audit/create', methods=['GET', 'POST'])
@login_required
@permission_required('asset:edit')
def audit_create():
    """创建盘点任务"""
    if request.method == 'POST':
        try:
            # 确定盘点范围
            scope_location_ids = request.form.get('scope_location_ids', '')
            scope_department = request.form.get('scope_department', '')

            # 计算范围内的资产数量
            query = Asset.query.filter_by(is_active=True)
            if scope_location_ids:
                loc_ids = [int(x) for x in scope_location_ids.split(',') if x.strip()]
                if loc_ids:
                    query = query.filter(Asset.location_id.in_(loc_ids))
            if scope_department:
                query = query.filter(Asset.owner_department == scope_department)

            total_assets = query.count()

            audit = AssetAudit(
                audit_no=f'AD{datetime.utcnow().strftime("%Y%m%d%H%M%S")}',
                name=request.form['name'],
                audit_type=request.form.get('audit_type', 'annual'),
                status='draft',
                scope_location_ids=scope_location_ids,
                scope_department=scope_department,
                scheduled_date=datetime.strptime(request.form['scheduled_date'], '%Y-%m-%d').date() if request.form.get('scheduled_date') else None,
                total_assets=total_assets,
                notes=request.form.get('notes', ''),
                created_by=current_user.id,
            )
            db.session.add(audit)
            db.session.commit()

            # 创建盘点明细
            assets = query.all()
            for asset in assets:
                item = AssetAuditItem(
                    audit_id=audit.id,
                    asset_id=asset.id,
                    asset_name=asset.asset_name,
                    asset_number=asset.asset_number,
                    expected_location=f"{asset.location.name if hasattr(asset, 'location') and asset.location else ''} / {asset.cabinet.name if hasattr(asset, 'cabinet') and asset.cabinet else ''}" if hasattr(asset, 'location') else '',
                    expected_status=asset.status,
                    status='pending',
                )
                db.session.add(item)

            db.session.commit()
            log_audit('create', 'audit', audit.id, f"创建盘点任务: {audit.name}",
                      details={'total_assets': total_assets},
                      user_id=current_user.id if current_user.is_authenticated else None)
            flash(f'盘点任务创建成功，共{total_assets}项资产', 'success')
            return redirect(url_for('asset_extra.audit_list'))
        except Exception as e:
            db.session.rollback()
            flash(f'创建失败: {str(e)}', 'danger')

    from models.models import Location
    locations = Location.query.all()
    departments = db.session.query(Asset.owner_department).filter(Asset.owner_department.isnot(None)).distinct().all()
    return render_template('asset/audit_create.html', locations=locations,
                           departments=[d[0] for d in departments if d[0]])


@asset_extra_bp.route('/audit/<int:id>')
@login_required
@permission_required('asset:view')
def audit_detail(id):
    """盘点详情"""
    audit = AssetAudit.query.get_or_404(id)
    page = request.args.get('page', 1, type=int)
    status_filter = request.args.get('status', '')

    query = AssetAuditItem.query.filter_by(audit_id=audit.id)
    if status_filter:
        query = query.filter(AssetAuditItem.status == status_filter)

    items = query.order_by(AssetAuditItem.id.asc()).paginate(page=page, per_page=50)
    return render_template('asset/audit_detail.html', audit=audit, items=items, status_filter=status_filter)


@asset_extra_bp.route('/audit/<int:id>/start', methods=['POST'])
@login_required
@permission_required('asset:edit')
def audit_start(id):
    """开始盘点"""
    audit = AssetAudit.query.get_or_404(id)
    audit.status = 'in_progress'
    db.session.commit()
    log_audit('execute', 'audit', audit.id, f"开始盘点: {audit.name}", user_id=current_user.id if current_user.is_authenticated else None)
    flash('盘点已开始', 'success')
    return redirect(url_for('asset_extra.audit_detail', id=audit.id))


@asset_extra_bp.route('/audit/<int:id>/scan', methods=['POST'])
@login_required
@permission_required('asset:edit')
def audit_scan(id):
    """扫描/录入盘点结果"""
    audit = AssetAudit.query.get_or_404(id)
    item_id = request.form.get('item_id', type=int)
    result_status = request.form.get('status', 'matched')
    actual_location = request.form.get('actual_location', '')
    notes = request.form.get('notes', '')

    item = AssetAuditItem.query.get_or_404(item_id)
    item.actual_location = actual_location or item.expected_location
    item.actual_status = result_status
    item.status = result_status
    item.scanned_by = current_user.id
    item.scanned_at = datetime.utcnow()
    item.notes = notes

    # 更新盘点计数
    audit.scanned_assets = AssetAuditItem.query.filter(
        AssetAuditItem.audit_id == audit.id,
        AssetAuditItem.status != 'pending'
    ).count()

    counts = db.session.query(
        AssetAuditItem.status, func.count(AssetAuditItem.id)
    ).filter(AssetAuditItem.audit_id == audit.id).group_by(AssetAuditItem.status).all()

    status_map = dict(counts)
    audit.matched_count = status_map.get('matched', 0)
    audit.discrepancy_count = status_map.get('mismatched', 0)
    audit.missing_count = status_map.get('missing', 0)
    audit.damaged_count = status_map.get('damaged', 0)

    db.session.commit()
    log_audit('execute', 'audit_item', item_id, f"录入盘点结果: {item_id}",
              details={'result_status': result_status},
              user_id=current_user.id if current_user.is_authenticated else None)
    flash('盘点项已更新', 'success')
    return redirect(url_for('asset_extra.audit_detail', id=audit.id))


@asset_extra_bp.route('/audit/<int:id>/complete', methods=['POST'])
@login_required
@permission_required('asset:edit')
def audit_complete(id):
    """完成盘点"""
    audit = AssetAudit.query.get_or_404(id)
    audit.status = 'completed'
    audit.completed_date = date.today()
    db.session.commit()
    log_audit('execute', 'audit', audit.id, f"完成盘点: {audit.name}", user_id=current_user.id if current_user.is_authenticated else None)
    flash('盘点已完成', 'success')
    return redirect(url_for('asset_extra.audit_detail', id=audit.id))


@asset_extra_bp.route('/audit/<int:id>/delete', methods=['POST'])
@login_required
@permission_required('asset:edit')
def audit_delete(id):
    """删除盘点任务（级联删除明细）"""
    audit = AssetAudit.query.get_or_404(id)
    name = audit.name
    try:
        db.session.delete(audit)
        db.session.commit()
        log_audit('delete', 'audit', id, f"删除盘点任务: {name}",
                  user_id=current_user.id if current_user.is_authenticated else None)
        flash(f'盘点任务 "{name}" 已删除', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'删除失败: {str(e)}', 'danger')
    return redirect(url_for('asset_extra.audit_list'))


@asset_extra_bp.route('/audit/<int:id>/report')
@login_required
@permission_required('asset:view')
def audit_report(id):
    """盘点报告"""
    audit = AssetAudit.query.get_or_404(id)
    items = AssetAuditItem.query.filter_by(audit_id=audit.id).all()

    # 统计
    status_counts = {}
    for item in items:
        status_counts[item.status] = status_counts.get(item.status, 0) + 1

    return render_template('asset/audit_report.html', audit=audit,
                           items=items, status_counts=status_counts)


# ==================== TCO API ====================

@asset_extra_bp.route('/api/tco')
@login_required
@permission_required('asset:view')
def api_tco():
    """TCO (总拥有成本) 计算API"""
    asset_id = request.args.get('asset_id', type=int)

    if asset_id:
        assets = Asset.query.filter_by(id=asset_id).all()
    else:
        assets = Asset.query.filter_by(is_active=True).all()

    from models.maintenance_models import MaintenanceRecord

    result = []
    for asset in assets:
        # 获取维护成本
        maint_records = MaintenanceRecord.query.filter_by(asset_id=asset.id).all()
        total_maint_cost = sum(float(r.labor_cost or 0) + float(r.material_cost or 0) for r in maint_records)

        tco = {
            'asset_id': asset.id,
            'asset_name': asset.asset_name,
            'asset_number': asset.asset_number,
            'purchase_cost': float(asset.purchase_price or 0),
            'maintenance_cost': round(total_maint_cost, 2),
            'current_value': float(asset.current_value or 0),
            'depreciation': float(asset.purchase_price or 0) - float(asset.current_value or 0),
            'tco': round(float(asset.purchase_price or 0) + total_maint_cost, 2),
            'age': asset.get_age() if hasattr(asset, 'get_age') else None,
        }
        result.append(tco)

    return jsonify({
        'assets': result,
        'total': len(result),
        'total_purchase_cost': sum(float(a.purchase_price or 0) for a in assets),
        'total_maintenance_cost': sum(r['maintenance_cost'] for r in result),
        'total_tco': sum(r['tco'] for r in result),
    })


# ==================== 资产管理仪表板 ====================

@asset_extra_bp.route('/dashboard')
@login_required
@permission_required('asset:view')
def asset_dashboard():
    """资产管理仪表板"""
    # 资产概览
    total_assets = Asset.query.filter_by(is_active=True).count()
    total_value = db.session.query(func.sum(Asset.current_value)).filter_by(is_active=True).scalar() or 0

    # 按类型统计
    type_stats = db.session.query(
        Asset.asset_type, func.count(Asset.id)
    ).filter_by(is_active=True).group_by(Asset.asset_type).all()

    # 按状态统计
    status_stats = db.session.query(
        Asset.status, func.count(Asset.id)
    ).filter_by(is_active=True).group_by(Asset.status).all()

    # 即将过期合同
    expiring_contracts = [c for c in Contract.query.filter_by(status='active').all() if c.is_expiring_soon()]

    # 即将过期许可
    expiring_licenses = [l for l in SoftwareLicense.query.filter_by(status='active').all() if l.is_expiring_soon(30)]

    # 合规问题
    non_compliant = SoftwareLicense.query.filter_by(compliance_status='non-compliant').count()

    # 最近盘点
    recent_audits = AssetAudit.query.order_by(AssetAudit.created_at.desc()).limit(5).all()

    # TCO汇总
    total_purchase = db.session.query(func.sum(Asset.purchase_price)).filter_by(is_active=True).scalar() or 0
    from models.maintenance_models import MaintenanceRecord
    total_maint = db.session.query(func.sum(MaintenanceRecord.labor_cost + MaintenanceRecord.material_cost)).scalar() or 0

    return render_template('asset/dashboard.html',
                           total_assets=total_assets,
                           total_value=round(float(total_value), 2),
                           type_stats=dict(type_stats),
                           status_stats=dict(status_stats),
                           expiring_contracts=expiring_contracts,
                           expiring_licenses=expiring_licenses,
                           non_compliant=non_compliant,
                           recent_audits=recent_audits,
                           total_purchase=round(float(total_purchase), 2),
                           total_maint=round(float(total_maint), 2))
