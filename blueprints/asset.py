# asset.py - 资产管理蓝图

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_file,Response,current_app
from flask_login import current_user,login_required
from models.models import Device,Location,Cabinet,User
from forms import (
    AssetForm, AssetImportForm, SupplierForm, SparePartForm, 
    SparePartRequestForm, DepreciationForm, AssetReportForm
)
from models.maintenance_models import Supplier, SparePart, Asset,  SparePart, AssetDepreciation, AssetLedger,SparePartRequest,SparePartUsage
import pandas as pd
from io import BytesIO
from datetime import datetime, timedelta
from sqlalchemy import func
from extensions import db
from werkzeug.utils import secure_filename
from utils.email import send_approval_notification, send_new_request_notification
import csv
import io
from utils.audit import log_audit
from utils.permission import permission_required


asset_bp = Blueprint('asset', __name__, url_prefix='/asset')

@asset_bp.route('/inventory')
@login_required
@permission_required('asset:view')
def asset_inventory():
    """资产清单"""
    assets = Asset.query.filter_by(is_active=True).all()
    total_value = sum(asset.current_value for asset in assets if asset.current_value)
    return render_template('asset/inventory.html', assets=assets, total_value=total_value)

@asset_bp.route('/ledger')
@login_required
@permission_required('asset:view')
def asset_ledger():
    """资产台账"""
    page = request.args.get('page', 1, type=int)
    per_page = 20
    
    query = AssetLedger.query
    
    # 搜索过滤
    search = request.args.get('search', '')
    if search:
        query = query.filter(
            db.or_(
                AssetLedger.asset_name.ilike(f'%{search}%'),
                AssetLedger.asset_code.ilike(f'%{search}%')
            )
        )
    
    ledgers = query.order_by(AssetLedger.transaction_date.desc()).paginate(page=page, per_page=per_page)
    
    return render_template('asset/ledger.html', ledgers=ledgers, search=search)

@asset_bp.route('/depreciation/calculate', methods=['GET', 'POST'])
@login_required
@permission_required('asset:edit')
def depreciation_calculation():
    """折旧计算"""
    form = DepreciationForm()
    
    if form.validate_on_submit():
        asset_id = form.asset_id.data
        method = form.method.data  # 直线法、双倍余额递减法等
        
        # 获取资产
        asset = Asset.query.get(asset_id)
        if not asset:
            flash('资产不存在！', 'error')
            return redirect(url_for('asset.depreciation_calculation'))
        
        # 计算折旧
        depreciation_records = calculate_depreciation(asset, method)
        
        return render_template('asset/depreciation_result.html', 
                             asset=asset, 
                             records=depreciation_records,
                             method=method)
    
    # 获取资产列表用于选择
    assets = Asset.query.filter_by(is_active=True).all()
    return render_template('asset/depreciation.html', form=form, asset=assets)

def calculate_depreciation(asset, method):
    """计算折旧"""
    records = []
    
    if method == 'straight_line':  # 直线法
        annual_depreciation = (asset.purchase_price - asset.residual_value) / asset.useful_life
        
        for year in range(1, asset.useful_life + 1):
            accumulated_depreciation = annual_depreciation * year
            current_value = asset.purchase_price - accumulated_depreciation
            
            records.append({
                'year': year,
                'annual_depreciation': annual_depreciation,
                'accumulated_depreciation': accumulated_depreciation,
                'current_value': current_value,
                'depreciation_rate': annual_depreciation / asset.purchase_price * 100
            })
    
    elif method == 'double_declining':  # 双倍余额递减法
        rate = 2 / asset.useful_life
        book_value = asset.purchase_price
        
        for year in range(1, asset.useful_life + 1):
            depreciation = book_value * rate
            
            # 最后一年调整，确保残值
            if year == asset.useful_life:
                depreciation = book_value - asset.residual_value
            
            accumulated_depreciation = sum(r['depreciation'] for r in records) + depreciation
            current_value = asset.purchase_price - accumulated_depreciation
            
            records.append({
                'year': year,
                'depreciation': depreciation,
                'accumulated_depreciation': accumulated_depreciation,
                'current_value': current_value,
                'depreciation_rate': rate * 100
            })
            
            book_value = current_value
    
    return records

@asset_bp.route('/reports')
@login_required
@permission_required('asset:view')
def asset_reports():
    """资产报表"""
    # 按资产类型统计，并将可能的 NULL 值转为 0
    type_stats = db.session.query(
        Asset.asset_type,
        func.count(Asset.id).label('count'),
        func.coalesce(func.sum(Asset.current_value), 0).label('total_value')
    ).group_by(Asset.asset_type).all()

    # 按资产状态统计
    status_stats = db.session.query(
        Asset.status,
        func.count(Asset.id).label('count')
    ).group_by(Asset.status).all()

    # 从资产台账中获取累计折旧（按资产分组），同样处理 NULL
    depreciation_summary = db.session.query(
        AssetLedger.asset_id,
        func.coalesce(func.sum(AssetLedger.credit_amount), 0).label('total_depreciation')
    ).filter(AssetLedger.transaction_type == 'depreciation') \
     .group_by(AssetLedger.asset_id).all()

    # 如果定义了 AssetReportForm 可以传入，否则传入 None 或省略
    form = AssetReportForm()  # 若未定义请注释此行

    return render_template('asset/reports.html',
                         form=form,
                         type_stats=type_stats,
                         status_stats=status_stats,
                         depreciation_summary=depreciation_summary)

@asset_bp.route('/supplier/management')
@login_required
@permission_required('asset:view')
def supplier_management():
    """供应商管理"""
    suppliers = Supplier.query.all()
    return render_template('asset/supplier_management.html', suppliers=suppliers)


@asset_bp.route('/spare_parts/inventory')
@login_required
@permission_required('asset:view')
def spare_parts_inventory():
    spare_parts = SparePart.query.all()
    suppliers = Supplier.query.all()   # 修正：从 Supplier 查询
    low_stock = [p for p in spare_parts if p.current_stock <= p.min_stock_level]
    return render_template('asset/spare_parts_inventory.html',
                           spare_parts=spare_parts,
                           low_stock=low_stock,
                           suppliers=suppliers)

@asset_bp.route('/spare_parts/requests')
@login_required
@permission_required('asset:view')
def spare_parts_requests():
    """备件申请列表（默认显示所有申请，可按状态过滤）"""
    # 可按查询参数过滤状态，这里简单返回所有
    requests = SparePartRequest.query.order_by(SparePartRequest.requested_at.desc()).all()
    # 获取所有启用备件供下拉选择
    spare_parts = SparePart.query.filter_by(is_active=True).all()
    return render_template('asset/spare_parts_requests.html',
                           requests=requests,
                           spare_parts=spare_parts)

@asset_bp.route('/spare_parts/request/create', methods=['GET', 'POST'])
@login_required
@permission_required('asset:edit')
def spare_parts_request_create():
    """创建备件申请"""
    form = SparePartRequestForm()
    form.spare_part_id.choices = [(p.id, f"{p.name} ({p.model})") for p in SparePart.query.all()]
    
    if form.validate_on_submit():
        request = SparePartRequest(
            spare_part_id=form.spare_part_id.data,
            quantity=form.quantity.data,
            requester=current_user.username,
            reason=form.reason.data,
            urgency=form.urgency.data
        )
        db.session.add(request)
        db.session.commit()
        log_audit('create', 'spare_part_request', request.id, f"创建备件申请", user_id=current_user.id if current_user.is_authenticated else None)
        flash('备件申请提交成功！', 'success')
        return redirect(url_for('asset.spare_parts_requests'))
    
    return render_template('asset/spare_parts_request_create.html', form=form)




@asset_bp.route('/spare_parts/usage')
@login_required
@permission_required('asset:view')
def spare_parts_usage():
    """备件使用统计"""
    # 获取日期参数，默认最近30天
    try:
        start_date = request.args.get('start_date', (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d'))
        end_date = request.args.get('end_date', datetime.now().strftime('%Y-%m-%d'))
    except:
        start_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
        end_date = datetime.now().strftime('%Y-%m-%d')

    # 查询统计，使用 coalesce 处理 NULL 值
    usage_stats = db.session.query(
        SparePart.part_name,
        func.coalesce(func.sum(SparePartUsage.quantity), 0).label('total_used'),
        func.coalesce(func.sum(SparePartUsage.quantity * SparePart.unit_price), 0).label('total_cost')
    ).join(SparePartUsage, SparePartUsage.spare_part_id == SparePart.id)\
     .filter(SparePartUsage.usage_date.between(start_date, end_date))\
     .group_by(SparePart.part_name)\
     .order_by(func.sum(SparePartUsage.quantity).desc())\
     .all()

    return render_template('asset/spare_parts_usage.html',
                         usage_stats=usage_stats,
                         start_date=start_date,
                         end_date=end_date)



@asset_bp.route('/export/report/<report_type>')
@login_required
@permission_required('asset:view')
def export_report(report_type):
    """导出资产报表"""
    if report_type == 'inventory':
        assets = Asset.query.all()
        data = [{
            '资产编号': asset.asset_code,
            '资产名称': asset.name,
            '类别': asset.category,
            '型号': asset.model,
            '采购价格': asset.purchase_price,
            '当前价值': asset.current_value,
            '状态': asset.status,
            '使用部门': asset.department,
            '责任人': asset.responsible_person,
            '采购日期': asset.purchase_date.strftime('%Y-%m-%d') if asset.purchase_date else '',
            '预计寿命': asset.useful_life,
            '残值': asset.residual_value
        } for asset in assets]
        
        filename = '资产清单.xlsx'
        
    elif report_type == 'depreciation':
        # 导出折旧报表
        records = AssetDepreciation.query.filter_by(year=datetime.now().year).all()
        data = [{
            '资产编号': record.asset.asset_code,
            '资产名称': record.asset.name,
            '年份': record.year,
            '月折旧额': record.monthly_depreciation,
            '累计折旧': record.accumulated_depreciation,
            '当前价值': record.current_value,
            '折旧方法': record.method
        } for record in records]
        
        filename = '折旧报表.xlsx'
    
    elif report_type == 'spare_parts':
        spare_parts = SparePart.query.all()
        data = [{
            '备件编号': part.part_code,
            '备件名称': part.name,
            '型号': part.model,
            '当前库存': part.quantity,
            '最小库存': part.min_quantity,
            '单位价格': part.unit_price,
            '供应商': part.supplier.name if part.supplier else '',
            '位置': part.location,
            '备注': part.notes
        } for part in spare_parts]
        
        filename = '备件库存.xlsx'
    
    else:
        flash('报表类型错误！', 'error')
        return redirect(url_for('asset.asset_reports'))
    
    # 生成Excel文件
    df = pd.DataFrame(data)
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='报表')
    
    output.seek(0)
    
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=filename
    )





@asset_bp.route('/add', methods=['GET', 'POST'])
@login_required
@permission_required('asset:edit')
def asset_add():
    form = AssetForm()
    
    # 设置动态 choices
    form.location_id.choices = [(0, '无')] + [(l.id, l.name) for l in Location.query.all()]
    form.cabinet_id.choices = [(0, '无')] + [(c.id, c.name) for c in Cabinet.query.all()]
    form.device_id.choices = [(0, '无')] + [(d.id, d.name) for d in Device.query.all()]
    form.supplier_id.choices = [(0, '无')] + [(s.id, s.name) for s in Supplier.query.filter_by(is_active=True).all()]
    form.responsible_user_id.choices = [(0, '无')] + [
        (u.id, f"{u.username} ({u.department or '无部门'})") 
        for u in User.query.filter_by(is_active=True).all()
    ]

    if form.validate_on_submit():
        asset = Asset()
        form.populate_obj(asset)
        
        # 处理外键空值（0 → None）
        for field in ['device_id', 'location_id', 'cabinet_id', 'supplier_id', 'responsible_user_id']:
            if hasattr(asset, field) and getattr(asset, field) == 0:
                setattr(asset, field, None)
        
        for field in ['serial_number', 'position', 'brand', 'model', 'specification', 
                  'usage_description', 'tags', 'notes']:
            value = getattr(asset, field, None)
            if value == '':
                setattr(asset, field, None)


        # 处理责任人冗余字段
        if asset.responsible_user_id:
            user = User.query.get(asset.responsible_user_id)
            if user:
                asset.owner_person = user.username
                asset.owner_department = user.department
                asset.owner_contact = user.phone
        
        db.session.add(asset)
        db.session.flush()  # 获取资产ID

        # 创建采购台账
        ledger_entry = AssetLedger(
            asset_id=asset.id,
            asset_code=asset.asset_number,
            asset_name=asset.asset_name,
            transaction_type='purchase',
            transaction_date=asset.purchase_date or datetime.now().date(),
            transaction_time=datetime.now(),
            debit_amount=asset.purchase_price or 0,
            credit_amount=0,
            balance_amount=asset.purchase_price or 0,
            quantity_change=1,
            quantity_balance=1,
            status_before='new',
            status_after=asset.status,
            location_id_after=asset.location_id,
            location_after=asset.location.name if asset.location else None,
            responsible_person_after=asset.owner_person,
            department_after=asset.owner_department,
            description='资产新增采购',
            operator_id=current_user.id if current_user.is_authenticated else None,
            operator_name=current_user.username if current_user.is_authenticated else None,
            approval_status='approved'
        )
        db.session.add(ledger_entry)

        db.session.commit()
        log_audit('create', 'asset', asset.id, f"添加设备: {asset.asset_name}", user_id=current_user.id if current_user.is_authenticated else None)
        flash('资产添加成功', 'success')
        return redirect(url_for('asset.asset_inventory'))
    
    return render_template('asset/add.html', form=form)


@asset_bp.route('/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@permission_required('asset:edit')
def asset_edit(id):
    asset = Asset.query.get_or_404(id)
    form = AssetForm(obj=asset)

    # 记录旧值（用于生成台账）
    old_status = asset.status
    old_location_id = asset.location_id
    old_location_name = asset.location.name if asset.location else None
    old_owner_person = asset.owner_person
    old_owner_department = asset.owner_department
    old_purchase_price = asset.purchase_price

    # 设置动态 choices
    form.location_id.choices = [(0, '无')] + [(l.id, l.name) for l in Location.query.all()]
    form.cabinet_id.choices = [(0, '无')] + [(c.id, c.name) for c in Cabinet.query.all()]
    form.device_id.choices = [(0, '无')] + [(d.id, d.name) for d in Device.query.all()]
    form.supplier_id.choices = [(0, '无')] + [(s.id, s.name) for s in Supplier.query.filter_by(is_active=True).all()]
    form.responsible_user_id.choices = [(0, '无')] + [
        (u.id, f"{u.username} ({u.department or '无部门'})") 
        for u in User.query.filter_by(is_active=True).all()
    ]

    if form.validate_on_submit():
        form.populate_obj(asset)
        
        # 清理空字符串
        for field in ['serial_number', 'position', 'brand', 'model', 'specification', 
                      'usage_description', 'tags', 'notes']:
            value = getattr(asset, field, None)
            if value in ['', 'None', 'null']:
                setattr(asset, field, None)
        
        # 外键 0 → None
        for field in ['device_id', 'location_id', 'cabinet_id', 'supplier_id', 'responsible_user_id']:
            if hasattr(asset, field) and getattr(asset, field) == 0:
                setattr(asset, field, None)

        # 收集变化并生成台账
        changes = []

        # 转移（位置或责任人变化）
        if (old_location_id != asset.location_id) or (old_owner_person != asset.owner_person):
            transfer_entry = AssetLedger(
                asset_id=asset.id,
                asset_code=asset.asset_number,
                asset_name=asset.asset_name,
                transaction_type='transfer',
                transaction_date=datetime.now().date(),
                transaction_time=datetime.now(),
                debit_amount=0,
                credit_amount=0,
                balance_amount=asset.purchase_price or 0,
                quantity_change=0,
                quantity_balance=1,
                status_before=old_status,
                status_after=asset.status,
                location_id_before=old_location_id,
                location_id_after=asset.location_id,
                location_before=old_location_name,
                location_after=asset.location.name if asset.location else None,
                responsible_person_before=old_owner_person,
                responsible_person_after=asset.owner_person,
                department_before=old_owner_department,
                department_after=asset.owner_department,
                description=f'资产转移: 位置/责任人变更',
                operator_id=current_user.id if current_user.is_authenticated else None,
                operator_name=current_user.username if current_user.is_authenticated else None,
                approval_status='approved'
            )
            changes.append(transfer_entry)

        # 价值重估（价格变化）
        if old_purchase_price != asset.purchase_price:
            revaluation_entry = AssetLedger(
                asset_id=asset.id,
                asset_code=asset.asset_number,
                asset_name=asset.asset_name,
                transaction_type='revaluation',
                transaction_date=datetime.now().date(),
                transaction_time=datetime.now(),
                debit_amount=0,
                credit_amount=0,
                balance_amount=asset.purchase_price or 0,
                quantity_change=0,
                quantity_balance=1,
                status_before=old_status,
                status_after=asset.status,
                location_id_before=old_location_id,
                location_id_after=asset.location_id,
                location_before=old_location_name,
                location_after=asset.location.name if asset.location else None,
                responsible_person_before=old_owner_person,
                responsible_person_after=asset.owner_person,
                department_before=old_owner_department,
                department_after=asset.owner_department,
                description=f'价值重估: {old_purchase_price} → {asset.purchase_price}',
                operator_id=current_user.id if current_user.is_authenticated else None,
                operator_name=current_user.username if current_user.is_authenticated else None,
                approval_status='approved'
            )
            changes.append(revaluation_entry)

        # 状态变化（如果状态变了且没有其他变化）
        if old_status != asset.status and not changes:
            status_entry = AssetLedger(
                asset_id=asset.id,
                asset_code=asset.asset_number,
                asset_name=asset.asset_name,
                transaction_type='status_change',  # 注意：需要在TRANSACTION_TYPES中添加此类型
                transaction_date=datetime.now().date(),
                transaction_time=datetime.now(),
                debit_amount=0,
                credit_amount=0,
                balance_amount=asset.purchase_price or 0,
                quantity_change=0,
                quantity_balance=1,
                status_before=old_status,
                status_after=asset.status,
                location_id_before=old_location_id,
                location_id_after=asset.location_id,
                location_before=old_location_name,
                location_after=asset.location.name if asset.location else None,
                responsible_person_before=old_owner_person,
                responsible_person_after=asset.owner_person,
                department_before=old_owner_department,
                department_after=asset.owner_department,
                description=f'状态变更: {old_status} → {asset.status}',
                operator_id=current_user.id if current_user.is_authenticated else None,
                operator_name=current_user.username if current_user.is_authenticated else None,
                approval_status='approved'
            )
            changes.append(status_entry)

        # 将台账记录添加到会话
        for entry in changes:
            db.session.add(entry)

        db.session.commit()
        log_audit('update', 'asset', asset.id, f"编辑设备: {asset.asset_name}", user_id=current_user.id if current_user.is_authenticated else None)
        flash('资产更新成功', 'success')
        return redirect(url_for('asset.asset_inventory'))

    return render_template('asset/edit.html', form=form, asset=asset)

@asset_bp.route('/api/user/<int:user_id>')
@login_required
@permission_required('asset:view')
def api_user_detail(user_id):
    user = User.query.get_or_404(user_id)
    return jsonify({
        'success': True,
        'username': user.username,
        'department': user.department,
        'phone': user.phone
    })



@asset_bp.route('/<int:id>/delete', methods=['POST', 'DELETE'])
@login_required
@permission_required('asset:edit')
def asset_delete(id):
    """删除资产（支持 POST 和 DELETE 方法）"""
    asset = Asset.query.get_or_404(id)
    
    # 执行删除（物理删除或软删除）
    db.session.delete(asset)  # 若需软删除，可改为 asset.is_active = False
    db.session.commit()
    log_audit('delete', 'asset', id, f"删除设备: {asset.asset_name}", user_id=current_user.id if current_user.is_authenticated else None)

    # 如果是 AJAX 请求（X-Requested-With: XMLHttpRequest），返回 JSON
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'success': True, 'message': '资产删除成功'})
    
    # 普通表单提交则重定向
    flash('资产删除成功', 'success')
    return redirect(url_for('asset.asset_inventory'))

@asset_bp.route('/<int:id>')
@login_required
@permission_required('asset:view')
def asset_detail(id):
    asset = Asset.query.get_or_404(id)
    return render_template('asset/detail.html', asset=asset)


import csv
from io import StringIO, BytesIO
from flask import Response, request, url_for


@asset_bp.route('/export')
@login_required
@permission_required('asset:view')
def asset_export():
    # 1. 获取前端传来的筛选参数
    search = request.args.get('search', '').strip()
    asset_type = request.args.get('type', '')
    status = request.args.get('status', '')

    # 2. 构建查询（应用所有筛选）
    query = Asset.query
    if search:
        query = query.filter(
            db.or_(
                Asset.asset_number.ilike(f'%{search}%'),
                Asset.asset_name.ilike(f'%{search}%'),
                Asset.model.ilike(f'%{search}%')
            )
        )
    if asset_type:
        query = query.filter(Asset.asset_type == asset_type)
    if status:
        query = query.filter(Asset.status == status)

    # 3. 获取所有符合条件的资产（不分页）
    assets = query.all()

    # 4. 准备导出字段（与表格列对齐，并补充可选字段）
    output = StringIO()
    # 使用 utf-8-sig 编码，Excel 打开不会乱码
    writer = csv.writer(output, delimiter=',')
    # 写入表头
    writer.writerow([
        '资产编号', '资产名称', '类型', '品牌', '型号',
        '状态', '当前价值(¥)', '位置', '责任人', '责任部门', '入库日期', '备注'
    ])

    for a in assets:
        # 状态映射为中文（如果数据库存的是英文）
        status_map = {
            'active': '使用中', 'inactive': '闲置',
            'maintenance': '维护中', 'retired': '已报废', 'lost': '丢失'
        }
        status_cn = status_map.get(a.status, a.status)

        # 位置名称
        location_name = a.location.name if a.location else ''
        cabinet_name = a.cabinet.name if a.cabinet else ''
        full_location = f"{location_name} / {cabinet_name}" if cabinet_name else location_name

        writer.writerow([
            a.asset_number,
            a.asset_name,
            a.asset_type,
            a.brand or '',
            a.model or '',
            status_cn,
            f"{a.current_value:.2f}" if a.current_value else '0.00',
            full_location,
            a.owner_person or '',
            a.owner_department or '',
            a.purchase_date.strftime('%Y-%m-%d') if a.purchase_date else '',
            a.notes or ''
        ])

    # 5. 构造响应，设置正确的 Content-Disposition 和编码
    output.seek(0)
    response = Response(output.getvalue(), mimetype='text/csv')
    response.headers.set('Content-Disposition', 'attachment', filename='assets_export.csv')
    # 关键：添加 BOM 头
    response.headers.set('Content-Type', 'text/csv; charset=utf-8-sig')
    return response

@asset_bp.route('/import/template')
@login_required
@permission_required('asset:view')
def download_asset_template():
    """下载资产导入模板（CSV格式）"""
    # 定义 CSV 列头（与 Asset 模型字段对应）
    headers = [
        'asset_number', 'asset_name', 'asset_type', 'asset_subtype',
        'brand', 'model', 'serial_number', 'specification',
        'status', 'condition', 'in_use',
        'purchase_date', 'purchase_price', 'warranty_expiry', 'depreciation_rate',
        'owner_department', 'owner_person', 'owner_contact',
        'supplier_name', 'supplier_contact',
        'location_id', 'cabinet_id', 'position',
        'device_id', 'tags', 'notes', 'usage_description', 'is_active'
    ]
    
    # 创建内存中的 CSV 文件
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(headers)  # 写入表头
    # 可添加一行示例数据
    writer.writerow([
        'AST-2024001', '核心交换机', '网络设备', '核心层交换机',
        'Huawei', 'S12700', 'SN12345678', '48端口千兆',
        'active', 'good', 'TRUE',
        '2023-01-15', '35000.00', '2026-01-14', '10',
        'IT部', '张三', '13800138000',
        'XX科技', '010-12345678',
        '1', '3', '机房A-01机柜-10U',
        '', '核心,生产环境', '需定期检查', '承载核心业务', 'TRUE'
    ])
    
    # 转换为字节流以供下载
    mem = io.BytesIO()
    mem.write(output.getvalue().encode('utf-8-sig'))  # 使用 utf-8-sig 兼容 Excel
    mem.seek(0)
    output.close()
    
    return send_file(
        mem,
        as_attachment=True,
        download_name='asset_import_template.csv',
        mimetype='text/csv'
    )
@asset_bp.route('/import', methods=['GET', 'POST'])
@login_required
@permission_required('asset:edit')
def asset_import():
    """资产导入页面及处理"""
    if request.method == 'GET':
        # 可查询最近的导入记录（假设有 ImportLog 模型）
        # 如果没有，可传入空列表
        import_logs = []  # 替换为实际查询
        return render_template('asset/import.html', import_logs=import_logs)
    
    # POST 处理文件上传
    file = request.files.get('file')
    if not file or file.filename == '':
        flash('请选择要上传的文件', 'danger')
        return redirect(url_for('asset.asset_import'))
    
    # 验证文件扩展名
    filename = secure_filename(file.filename)
    if not (filename.endswith('.csv') or filename.endswith('.xlsx') or filename.endswith('.xls')):
        flash('不支持的文件格式，请上传 CSV 或 Excel 文件', 'danger')
        return redirect(url_for('asset.asset_import'))
    
    # 获取导入选项
    update_mode = request.form.get('update_mode', 'insert')  # insert 或 update
    first_row_header = request.form.get('first_row_header') == '1'
    
    # 解析文件
    rows = []
    try:
        if filename.endswith('.csv'):
            rows = parse_csv(file)
        else:
            # 如需支持 Excel，需安装 openpyxl 或 xlrd
            # 这里给出一个简单提示，实际可扩展
            flash('Excel 解析需要安装 openpyxl，请先使用 CSV 格式', 'warning')
            return redirect(url_for('asset.asset_import'))
            # 若已安装，可调用 parse_excel(file)
    except Exception as e:
        current_app.logger.error(f"解析文件失败: {str(e)}")
        flash(f'文件解析失败: {str(e)}', 'danger')
        return redirect(url_for('asset.asset_import'))
    
    if first_row_header and len(rows) > 0:
        headers = rows[0]
        data_rows = rows[1:]
    else:
        # 如果没有表头，则使用默认顺序（与模板列顺序一致）
        headers = [
            'asset_number', 'asset_name', 'asset_type', 'asset_subtype',
            'brand', 'model', 'serial_number', 'specification',
            'status', 'condition', 'in_use',
            'purchase_date', 'purchase_price', 'warranty_expiry', 'depreciation_rate',
            'owner_department', 'owner_person', 'owner_contact',
            'supplier_name', 'supplier_contact',
            'location_id', 'cabinet_id', 'position',
            'device_id', 'tags', 'notes', 'usage_description', 'is_active'
        ]
        data_rows = rows
    
    # 转换数据为字典列表
    assets_data = []
    for row in data_rows:
        if len(row) < len(headers):
            # 行数据不足，填充空字符串
            row += [''] * (len(headers) - len(row))
        asset_dict = dict(zip(headers, row))
        assets_data.append(asset_dict)
    
    # 批量处理
    success_count = 0
    error_count = 0
    errors = []
    
    for idx, data in enumerate(assets_data, start=1):
        try:
            # 必填字段检查
            if not data.get('asset_number') or not data.get('asset_name') or not data.get('asset_type') or not data.get('status'):
                raise ValueError("资产编号、资产名称、资产类型、状态为必填项")
            
            # 查找是否已存在
            asset = Asset.query.filter_by(asset_number=data['asset_number']).first()
            
            if asset and update_mode == 'insert':
                # 已存在且模式为仅插入，跳过
                error_count += 1
                errors.append(f"第{idx}行: 资产编号 {data['asset_number']} 已存在，跳过")
                continue
            elif asset and update_mode == 'update':
                # 更新现有资产
                pass
            elif not asset:
                # 新建资产
                asset = Asset()
                db.session.add(asset)
            
            # 字段映射（根据模型字段赋值）
            # 字符串字段直接赋值
            asset.asset_number = data.get('asset_number')
            asset.asset_name = data.get('asset_name')
            asset.asset_type = data.get('asset_type')
            asset.asset_subtype = data.get('asset_subtype') or None
            asset.brand = data.get('brand') or None
            asset.model = data.get('model') or None
            asset.serial_number = data.get('serial_number') or None
            asset.specification = data.get('specification') or None
            
            # 状态字段需校验
            status = data.get('status', 'active')
            if status not in ['active', 'inactive', 'maintenance', 'retired', 'lost']:
                status = 'active'
            asset.status = status
            
            condition = data.get('condition', 'good')
            if condition not in ['excellent', 'good', 'fair', 'poor']:
                condition = 'good'
            asset.condition = condition
            
            # 布尔值处理（字符串 'true'/'1'/'yes' 转换为 True）
            in_use = data.get('in_use', 'true')
            asset.in_use = str(in_use).lower() in ['true', '1', 'yes', 'on']
            
            # 日期字段
            if data.get('purchase_date'):
                try:
                    asset.purchase_date = datetime.strptime(data['purchase_date'], '%Y-%m-%d').date()
                except:
                    pass
            if data.get('warranty_expiry'):
                try:
                    asset.warranty_expiry = datetime.strptime(data['warranty_expiry'], '%Y-%m-%d').date()
                except:
                    pass
            
            # 数值字段
            try:
                asset.purchase_price = float(data['purchase_price']) if data.get('purchase_price') else None
            except:
                pass
            try:
                asset.depreciation_rate = float(data['depreciation_rate']) if data.get('depreciation_rate') else None
            except:
                pass
            
            # 外键字段
            if data.get('location_id'):
                try:
                    asset.location_id = int(data['location_id'])
                except:
                    pass
            if data.get('cabinet_id'):
                try:
                    asset.cabinet_id = int(data['cabinet_id'])
                except:
                    pass
            if data.get('device_id'):
                try:
                    asset.device_id = int(data['device_id'])
                except:
                    pass
            
            # 其他文本字段
            asset.owner_department = data.get('owner_department') or None
            asset.owner_person = data.get('owner_person') or None
            asset.owner_contact = data.get('owner_contact') or None
            asset.supplier_name = data.get('supplier_name') or None
            asset.supplier_contact = data.get('supplier_contact') or None
            asset.position = data.get('position') or None
            asset.tags = data.get('tags') or None
            asset.notes = data.get('notes') or None
            asset.usage_description = data.get('usage_description') or None
            
            # 是否有效
            is_active = data.get('is_active', 'true')
            asset.is_active = str(is_active).lower() in ['true', '1', 'yes', 'on']
            
            # 计算当前价值（模型方法会自动计算？可在此手动调用或依赖模型事件）
            # 若模型有 calculate_current_value 方法，可在此赋值
            # asset.current_value = asset.calculate_current_value()
            
            # 提交
            db.session.commit()
            success_count += 1
            
        except Exception as e:
            db.session.rollback()
            error_count += 1
            errors.append(f"第{idx}行: {str(e)}")
            current_app.logger.error(f"导入行{idx}失败: {str(e)}")

    log_audit('execute', 'asset', None, f"导入资产: {success_count}条成功, {error_count}条失败",
              details={'success_count': success_count, 'error_count': error_count},
              user_id=current_user.id if current_user.is_authenticated else None)

    # 导入结果反馈
    if success_count > 0:
        flash(f'成功导入 {success_count} 条资产记录', 'success')
    if error_count > 0:
        flash(f'导入失败 {error_count} 条，请检查错误日志', 'danger')
        # 可将错误列表记录到日志或返回给用户
        for err in errors[:10]:  # 只显示前10条
            flash(err, 'warning')
    
    return redirect(url_for('asset.asset_inventory'))

def parse_csv(file):
    """解析 CSV 文件，返回行列表"""
    stream = io.StringIO(file.stream.read().decode('utf-8-sig'))
    reader = csv.reader(stream)
    return [row for row in reader]


def parse_excel(file):
    """解析 Excel 文件，返回行列表（需安装 openpyxl）"""
    try:
        from openpyxl import load_workbook
    except ImportError:
        raise ImportError("请安装 openpyxl: pip install openpyxl")
    
    wb = load_workbook(file)
    ws = wb.active
    rows = []
    for row in ws.iter_rows(values_only=True):
        rows.append([cell if cell is not None else '' for cell in row])
    return rows

@asset_bp.route('/supplier/add', methods=['POST'])
@login_required
@permission_required('asset:edit')
def add_supplier():
    """新增供应商（API接口）"""
    try:
        name = request.form.get('name')
        if not name:
            return jsonify(success=False, message='供应商名称不能为空'), 400

        supplier = Supplier(
            name=name,
            contact_person=request.form.get('contact_person'),
            email=request.form.get('email'),
            phone=request.form.get('phone'),
            address=request.form.get('address'),
            website=request.form.get('website'),
            rating=request.form.get('rating', type=int),
            lead_time=request.form.get('lead_time', type=int),
            payment_terms=request.form.get('payment_terms'),
            notes=request.form.get('notes'),
            is_active=(request.form.get('is_active') == 'on')
        )
        db.session.add(supplier)
        db.session.commit()
        log_audit('create', 'supplier', supplier.id, f"添加供应商: {name}", user_id=current_user.id if current_user.is_authenticated else None)
        return jsonify(success=True, message='供应商添加成功', supplier_id=supplier.id)
    except Exception as e:
        db.session.rollback()
        # 记录错误日志
        current_app.logger.error(f"添加供应商失败: {str(e)}")
        return jsonify(success=False, message=str(e)), 500


@asset_bp.route('/supplier/edit/<int:id>', methods=['PUT', 'POST'])
@login_required
@permission_required('asset:edit')
def edit_supplier(id):
    """编辑供应商（支持 PUT 和 POST）"""
    supplier = Supplier.query.get_or_404(id)
    try:
        supplier.name = request.form.get('name', supplier.name)
        supplier.contact_person = request.form.get('contact_person', supplier.contact_person)
        supplier.email = request.form.get('email', supplier.email)
        supplier.phone = request.form.get('phone', supplier.phone)
        supplier.address = request.form.get('address', supplier.address)
        supplier.website = request.form.get('website', supplier.website)
        supplier.rating = request.form.get('rating', type=int) or supplier.rating
        supplier.lead_time = request.form.get('lead_time', type=int) or supplier.lead_time
        supplier.payment_terms = request.form.get('payment_terms', supplier.payment_terms)
        supplier.notes = request.form.get('notes', supplier.notes)
        supplier.is_active = (request.form.get('is_active') == 'on')
        supplier.updated_at = datetime.utcnow()
        db.session.commit()
        log_audit('update', 'supplier', id, f"编辑供应商: {supplier.name}", user_id=current_user.id if current_user.is_authenticated else None)
        return jsonify(success=True, message='供应商更新成功')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error editing supplier {id}: {str(e)}")
        return jsonify(success=False, message=str(e)), 500


@asset_bp.route('/supplier/delete/<int:id>', methods=['DELETE'])
@login_required
@permission_required('asset:edit')
def delete_supplier(id):
    """删除供应商"""
    supplier = Supplier.query.get_or_404(id)
    try:
        db.session.delete(supplier)
        db.session.commit()
        log_audit('delete', 'supplier', id, f"删除供应商: {supplier.name}", user_id=current_user.id if current_user.is_authenticated else None)
        return jsonify(success=True, message='供应商删除成功')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting supplier {id}: {str(e)}")
        return jsonify(success=False, message=str(e)), 500


@asset_bp.route('/supplier/get/<int:id>')
@login_required
@permission_required('asset:view')
def get_supplier(id):
    """获取单个供应商详情"""
    supplier = Supplier.query.get_or_404(id)
    data = {
        'id': supplier.id,
        'name': supplier.name,
        'contact_person': supplier.contact_person,
        'email': supplier.email,
        'phone': supplier.phone,
        'address': supplier.address,
        'website': supplier.website,
        'rating': supplier.rating,
        'lead_time': supplier.lead_time,
        'payment_terms': supplier.payment_terms,
        'notes': supplier.notes,
        'is_active': supplier.is_active
    }
    return jsonify(success=True, supplier=data)




@asset_bp.route('/spare_part/get/<int:id>', methods=['GET'])
@login_required
@permission_required('asset:view')
def get_spare_part(id):
    """获取单个备件详情（JSON）"""
    part = SparePart.query.get(id)
    if not part:
        return jsonify(success=False, message='备件不存在'), 404
    
    # 构造返回数据（可根据需要扩展）
    data = {
        'id': part.id,
        'part_number': part.part_number,
        'name': part.name,
        'category': part.category,
        'vendor': part.vendor,
        'model': part.model,
        'unit_price': part.unit_price,
        'current_stock': part.current_stock,
        'min_stock_level': part.min_stock_level,
        'max_stock_level': part.max_stock_level,
        'location': part.location,
        'supplier_id': part.supplier_id,
        'description': part.description,
        'compatible_devices': part.compatible_devices,
        'storage_conditions': part.storage_conditions,
        'is_active': part.is_active
    }
    return jsonify(success=True, part=data)


@asset_bp.route('/spare_part/add', methods=['POST'])
@login_required
@permission_required('asset:edit')
def add_spare_part():
    """新增备件（接收表单数据）"""
    try:
        # 必填字段验证
        part_number = request.form.get('part_number')
        name = request.form.get('name')
        if not part_number or not name:
            return jsonify(success=False, message='备件编号和名称为必填项'), 400

        # 创建备件对象
        part = SparePart(
            part_number=part_number,
            name=name,
            description=request.form.get('description'),
            category=request.form.get('category'),
            vendor=request.form.get('vendor'),
            model=request.form.get('model'),
            compatible_devices=request.form.get('compatible_devices'),
            unit_price=request.form.get('unit_price', type=float),
            current_stock=request.form.get('current_stock', type=int, default=0),
            min_stock_level=request.form.get('min_stock_level', type=int, default=1),
            max_stock_level=request.form.get('max_stock_level', type=int),
            location=request.form.get('location'),
            storage_conditions=request.form.get('storage_conditions'),
            supplier_id=request.form.get('supplier_id', type=int) or None,
            is_active=request.form.get('is_active') == 'on'
        )
        db.session.add(part)
        db.session.commit()
        log_audit('create', 'spare_part', part.id, f"添加备件: {name}", user_id=current_user.id if current_user.is_authenticated else None)

        return jsonify(success=True, message='备件添加成功', part_id=part.id)
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"添加备件失败: {str(e)}")
        return jsonify(success=False, message=str(e)), 500


@asset_bp.route('/spare_part/edit/<int:id>', methods=['POST'])
@login_required
@permission_required('asset:edit')
def edit_spare_part(id):
    """编辑备件（接收表单数据）"""
    part = SparePart.query.get(id)
    if not part:
        return jsonify(success=False, message='备件不存在'), 404

    try:
        # 更新字段（仅当表单中有值时才更新，保留原值）
        part.part_number = request.form.get('part_number', part.part_number)
        part.name = request.form.get('name', part.name)
        part.description = request.form.get('description', part.description)
        part.category = request.form.get('category', part.category)
        part.vendor = request.form.get('vendor', part.vendor)
        part.model = request.form.get('model', part.model)
        part.compatible_devices = request.form.get('compatible_devices', part.compatible_devices)
        
        # 数字类型转换
        unit_price = request.form.get('unit_price')
        if unit_price is not None and unit_price != '':
            part.unit_price = float(unit_price)
        
        current_stock = request.form.get('current_stock')
        if current_stock is not None and current_stock != '':
            part.current_stock = int(current_stock)
        
        min_stock = request.form.get('min_stock_level')
        if min_stock is not None and min_stock != '':
            part.min_stock_level = int(min_stock)
        
        max_stock = request.form.get('max_stock_level')
        if max_stock is not None and max_stock != '':
            part.max_stock_level = int(max_stock)
        
        part.location = request.form.get('location', part.location)
        part.storage_conditions = request.form.get('storage_conditions', part.storage_conditions)
        
        supplier_id = request.form.get('supplier_id')
        if supplier_id is not None and supplier_id != '':
            part.supplier_id = int(supplier_id)
        else:
            part.supplier_id = None
        
        part.is_active = request.form.get('is_active') == 'on' if 'is_active' in request.form else part.is_active
        
        part.updated_at = datetime.utcnow()
        db.session.commit()
        log_audit('update', 'spare_part', id, f"编辑备件: {part.name}", user_id=current_user.id if current_user.is_authenticated else None)

        return jsonify(success=True, message='备件更新成功')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"编辑备件 {id} 失败: {str(e)}")
        return jsonify(success=False, message=str(e)), 500


@asset_bp.route('/spare_part/delete/<int:id>', methods=['DELETE'])
@login_required
@permission_required('asset:edit')
def delete_spare_part(id):
    """删除备件"""
    part = SparePart.query.get(id)
    if not part:
        return jsonify(success=False, message='备件不存在'), 404

    try:
        db.session.delete(part)
        db.session.commit()
        log_audit('delete', 'spare_part', id, f"删除备件: {part.name}", user_id=current_user.id if current_user.is_authenticated else None)
        return jsonify(success=True, message='备件删除成功')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"删除备件 {id} 失败: {str(e)}")
        return jsonify(success=False, message=str(e)), 500


@asset_bp.route('/spare_part/adjust-stock/<int:id>', methods=['POST'])
@login_required
@permission_required('asset:edit')
def adjust_stock(id):
    """库存调整（接收 JSON）"""
    part = SparePart.query.get(id)
    if not part:
        return jsonify(success=False, message='备件不存在'), 404

    data = request.get_json()
    if not data:
        return jsonify(success=False, message='无效的请求数据'), 400

    adjustment = data.get('adjustment')
    reason = data.get('reason', '')

    if adjustment is None or not isinstance(adjustment, int):
        return jsonify(success=False, message='调整数量必须是整数'), 400

    try:
        # 更新库存（正数增加，负数减少）
        part.current_stock += adjustment
        # 确保库存不低于0（可根据业务需求调整）
        if part.current_stock < 0:
            part.current_stock = 0
        
        part.updated_at = datetime.utcnow()
        db.session.commit()
        log_audit('execute', 'spare_part', part.id, f"调整备件库存: {part.name}, 调整量: {adjustment}",
                  details={'adjustment': adjustment, 'new_stock': part.current_stock, 'reason': reason},
                  user_id=current_user.id if current_user.is_authenticated else None)

        return jsonify(success=True, message='库存调整成功', new_stock=part.current_stock)
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"调整备件 {id} 库存失败: {str(e)}")
        return jsonify(success=False, message=str(e)), 500


@asset_bp.route('/spare_part_request/get/<int:id>', methods=['GET'])
@login_required
@permission_required('asset:view')
def get_spare_part_request(id):
    """获取单个申请详情（JSON）"""
    req = SparePartRequest.query.get(id)
    if not req:
        return jsonify(success=False, message='申请不存在'), 404

    data = {
        'id': req.id,
        'request_number': req.request_number,
        'spare_part_id': req.spare_part_id,
        'quantity': req.quantity,
        'reason': req.reason,
        'urgency': req.urgency,
        'usage_description': req.usage_description,
        'requester_id': req.requester_id,
        'requester_name': req.requester_name,
        'department': req.department,
        'approval_status': req.approval_status,
        'issued_quantity': req.issued_quantity,
        'status': req.status,
    }
    return jsonify(success=True, request=data)


@asset_bp.route('/spare_part_request/add', methods=['POST'])
@login_required
@permission_required('asset:edit')
def add_spare_part_request():
    """新增备件申请"""
    try:
        # 表单数据
        spare_part_id = request.form.get('spare_part_id', type=int)
        quantity = request.form.get('quantity', type=int)
        reason = request.form.get('reason')
        urgency = request.form.get('urgency', 'medium')
        usage_description = request.form.get('usage_description')

        # 验证
        if not spare_part_id or not quantity or not reason:
            return jsonify(success=False, message='备件、数量、原因为必填项'), 400

        # 检查备件是否存在
        spare_part = SparePart.query.get(spare_part_id)
        if not spare_part:
            return jsonify(success=False, message='备件不存在'), 404

        # 生成申请单号
        new_request = SparePartRequest()
        request_number = new_request.generate_request_number()

        # 创建申请
        req = SparePartRequest(
            request_number=request_number,
            spare_part_id=spare_part_id,
            quantity=quantity,
            reason=reason,
            urgency=urgency,
            usage_description=usage_description,
            requester_id=current_user.id,
            requester_name=current_user.username,  # 假设 User 有 username 字段
            department=current_user.department if hasattr(current_user, 'department') else None,
            approval_status='pending',
            status='pending'
        )
        db.session.add(req)
        db.session.commit()
        log_audit('create', 'spare_part_request', req.id, f"创建备件申请: {req.id}", user_id=current_user.id if current_user.is_authenticated else None)
        send_new_request_notification(req)
        return jsonify(success=True, message='申请提交成功', request_id=req.id)
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"添加申请失败: {str(e)}")
        return jsonify(success=False, message=str(e)), 500


@asset_bp.route('/spare_part_request/edit/<int:id>', methods=['POST'])
@login_required
@permission_required('asset:edit')
def edit_spare_part_request(id):
    """编辑备件申请（仅允许在 pending 状态时编辑）"""
    req = SparePartRequest.query.get(id)
    if not req:
        return jsonify(success=False, message='申请不存在'), 404

    # 仅允许编辑待审批的申请
    if req.status != 'pending':
        return jsonify(success=False, message='只能编辑待审批的申请'), 403

    try:
        # 更新字段
        req.spare_part_id = request.form.get('spare_part_id', type=int) or req.spare_part_id
        req.quantity = request.form.get('quantity', type=int) or req.quantity
        req.reason = request.form.get('reason', req.reason)
        req.urgency = request.form.get('urgency', req.urgency)
        req.usage_description = request.form.get('usage_description', req.usage_description)
        req.updated_at = datetime.utcnow()
        db.session.commit()
        log_audit('update', 'spare_part_request', id, f"编辑备件申请: {id}", user_id=current_user.id if current_user.is_authenticated else None)
        return jsonify(success=True, message='申请更新成功')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"编辑申请 {id} 失败: {str(e)}")
        return jsonify(success=False, message=str(e)), 500


@asset_bp.route('/spare_part_request/delete/<int:id>', methods=['DELETE'])
@login_required
@permission_required('asset:edit')
def delete_spare_part_request(id):
    """删除备件申请（仅允许 pending 状态）"""
    req = SparePartRequest.query.get(id)
    if not req:
        return jsonify(success=False, message='申请不存在'), 404

    if req.status != 'pending':
        return jsonify(success=False, message='只能删除待审批的申请'), 403

    try:
        db.session.delete(req)
        db.session.commit()
        log_audit('delete', 'spare_part_request', id, f"删除备件申请: {id}", user_id=current_user.id if current_user.is_authenticated else None)
        return jsonify(success=True, message='申请删除成功')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"删除申请 {id} 失败: {str(e)}")
        return jsonify(success=False, message=str(e)), 500





@asset_bp.route('/spare_part_request/approve/<int:id>', methods=['POST'])
@login_required
@permission_required('asset:edit')
def approve_spare_part_request(id):
    """审批备件申请"""

    req = SparePartRequest.query.get(id)
    if not req:
        return jsonify(success=False, message='申请不存在'), 404

    # 只能审批 pending 状态的申请
    if req.status != 'pending':
        return jsonify(success=False, message='该申请已处理，不能再次审批'), 400

    data = request.get_json()
    if not data:
        return jsonify(success=False, message='无效的请求数据'), 400

    approval_status = data.get('approval_status')
    approval_notes = data.get('approval_notes', '')

    if approval_status not in ['approved', 'rejected', 'partially_approved']:
        return jsonify(success=False, message='无效的审批状态'), 400

    try:
        # 更新申请
        req.approval_status = approval_status
        req.approval_notes = approval_notes
        req.approved_by = current_user.username
        req.approved_at = datetime.utcnow()

        # 根据审批结果更新状态（可根据业务调整）
        if approval_status == 'approved':
            req.status = 'approved'
        elif approval_status == 'rejected':
            req.status = 'cancelled'  # 或维持 pending，但通常拒绝后变为 cancelled
        elif approval_status == 'partially_approved':
            req.status = 'approved'   # 部分通过也视为已审批，但可能需后续处理

        db.session.commit()
        log_audit('execute', 'spare_part_request', req.id, f"审批备件申请: {req.id}, 状态: {approval_status}",
                  details={'approval_status': approval_status, 'approval_notes': approval_notes},
                  user_id=current_user.id if current_user.is_authenticated else None)

        # 发送邮件通知申请人
        send_approval_notification(req)

        return jsonify(success=True, message='审批完成')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"审批申请 {id} 失败: {str(e)}")
        return jsonify(success=False, message=str(e)), 500
