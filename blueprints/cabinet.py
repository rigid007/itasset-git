# cabinet.py - 机柜管理蓝图

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_file, current_app
from flask_login import login_required, current_user
from models.models import (Cabinet, Location, Device, AlertEvent, MonitorData,
                           DeviceMonitorLog, InventoryTransaction, DeviceMonitorConfig,
                           ConnectionPath, InterfaceMonitorData, OperationLog)
from extensions import db
from forms import CabinetForm, CabinetImportForm
from utils.audit import log_audit
from utils.permission import permission_required
import pandas as pd
from io import BytesIO
from datetime import datetime, timedelta
from sqlalchemy.orm import joinedload
from sqlalchemy import or_

import numpy as np

from flask_wtf import FlaskForm
from wtforms import FileField, BooleanField
from wtforms.validators import InputRequired
from werkzeug.utils import secure_filename

import os


cabinet_bp = Blueprint('cabinet', __name__, url_prefix='/cabinet')


@cabinet_bp.route('/cabinet/rack-view')
@login_required
@permission_required('cabinet:view')
def cabinet_rack_view():
    """机柜视图 - 可视化机柜布局"""
    try:
        # 获取所有机柜及其详细信息
        cabinets = Cabinet.query.order_by(Cabinet.name).all()
        
        # 获取筛选参数
        location_id = request.args.get('location_id', type=int)
        search_query = request.args.get('search', '')
        
        # 应用筛选条件
        if location_id:
            cabinets = [c for c in cabinets if c.location_id == location_id]
        
        if search_query:
            cabinets = [c for c in cabinets if search_query.lower() in c.name.lower()]
        
        # 为每个机柜准备详细信息
        cabinet_details = []
        for cabinet in cabinets:
            # 获取机柜中的设备（按U位排序）
            devices = Device.query.filter_by(cabinet_id=cabinet.id)\
                                 .order_by(Device.position_u.asc())\
                                 .all()
            
            # 计算U位使用情况
            used_u_count = sum(device.height_u for device in devices if device.position_u)
            total_u = cabinet.height_u or 42
            usage_percent = (used_u_count / total_u * 100) if total_u > 0 else 0
            
            # 构建U位槽位图
            u_slots = {}
            for device in devices:
                if device.position_u:
                    start_u = device.position_u
                    end_u = start_u + device.height_u - 1
                    for u in range(start_u, end_u + 1):
                        if u <= total_u:
                            u_slots[u] = {
                                'device_id': device.id,
                                'device_name': device.name,
                                'device_type': device.device_type,
                                'status': device.status,
                                'height': device.height_u,
                                'start_u': start_u,
                                'end_u': end_u
                            }
            
            # 收集机柜信息 - 修改这里！
            cabinet_details.append({
                'id': cabinet.id,
                'name': cabinet.name,
                'location': cabinet.location,  # 保存完整对象，而不是字符串
                'location_name': cabinet.location.name if cabinet.location else '未指定位置',  # 添加单独的显示字段
                'location_id': cabinet.location_id,
                'total_u': total_u,
                'used_u': used_u_count,
                'available_u': total_u - used_u_count,
                'usage_percent': round(usage_percent, 1),
                'devices': devices,
                'u_slots': u_slots,
                'power_capacity': cabinet.power_capacity,
                'description': cabinet.description
            })
        
        # 获取所有位置（用于筛选下拉框）
        locations = Location.query.order_by(Location.name).all()
        
        return render_template(
            '/cabinet/rack_view.html',
            cabinets=cabinet_details,
            locations=locations,
            selected_location_id=location_id,
            search_query=search_query
        )
        
    except Exception as e:
        current_app.logger.error(f"加载机柜视图失败: {str(e)}")
        flash(f'加载机柜视图失败: {str(e)}', 'error')
        return redirect(url_for('cabinet.cabinet_list'))

# ==================== 机柜相关路由 ====================
@cabinet_bp.route('/cabinets')
@login_required
@permission_required('cabinet:view')
def cabinet_list():
    """机柜列表（带分页、筛选、搜索）"""
    # 获取请求参数
    page = request.args.get('page', 1, type=int)
    per_page = current_app.config.get('ITEMS_PER_PAGE', 20)
    search_query = request.args.get('search', '')
    selected_location_id = request.args.get('location_id', '', type=int)
    selected_usage = request.args.get('usage', '')
    selected_height = request.args.get('height_u', '')
    sort_by = request.args.get('sort_by', 'name')
    
    # 构建基础查询
    query = Cabinet.query
    
    # 搜索过滤
    if search_query:
        query = query.filter(
            (Cabinet.name.ilike(f'%{search_query}%')) | 
            (Cabinet.description.ilike(f'%{search_query}%'))
        )
    
    # 位置筛选
    if selected_location_id:
        query = query.filter(Cabinet.location_id == selected_location_id)
    
    # 高度筛选
    if selected_height:
        if selected_height == 'other':
            # 筛选非42U、非47U的机柜
            query = query.filter(~Cabinet.height_u.in_([42, 47]))
        else:
            query = query.filter(Cabinet.height_u == int(selected_height))
    
    # 先获取所有符合筛选条件的机柜（用于计算总U位/已用U位）
    filtered_cabinets_all = query.all()
    
    # 计算总U位和已使用U位
    total_u = 0
    used_u = 0
    for cabinet in filtered_cabinets_all:
        total_u += cabinet.height_u
        used_u += cabinet.get_used_u_count()
    
    # 使用率筛选（基于计算字段）
    if selected_usage:
        filtered_cabinets = []
        for cabinet in filtered_cabinets_all:
            usage_percent = cabinet.get_u_availability()['usage_percent']
            if selected_usage == 'low' and usage_percent < 70:
                filtered_cabinets.append(cabinet)
            elif selected_usage == 'medium' and 70 <= usage_percent <= 90:
                filtered_cabinets.append(cabinet)
            elif selected_usage == 'high' and usage_percent > 90:
                filtered_cabinets.append(cabinet)
    else:
        filtered_cabinets = filtered_cabinets_all
    
    # 排序逻辑 - 修复核心错误：移除 .asc() 调用
    if sort_by == 'name':
        # 按机柜名称升序排序
        filtered_cabinets.sort(key=lambda x: x.name)
    elif sort_by == 'location':
        # 按位置名称升序排序（位置为空的排最后）
        filtered_cabinets.sort(key=lambda x: x.location.name if x.location else 'zzz')
    elif sort_by == 'usage':
        # 按使用率降序排序
        filtered_cabinets.sort(key=lambda x: x.get_u_availability()['usage_percent'], reverse=True)
    elif sort_by == 'updated':
        # 按更新时间降序排序
        filtered_cabinets.sort(key=lambda x: x.updated_at or datetime.min, reverse=True)
    
    # 分页处理
    total = len(filtered_cabinets)
    total_pages = (total + per_page - 1) // per_page
    start = (page - 1) * per_page
    end = start + per_page
    cabinets = filtered_cabinets[start:end]
    
    # 获取所有位置（用于筛选下拉框）
    all_locations = Location.query.order_by(Location.name.asc()).all()
    
    # 传递变量到模板
    return render_template(
        '/cabinet/cabinet_list.html',
        cabinets=cabinets,
        search_query=search_query,
        selected_location_id=selected_location_id,
        selected_usage=selected_usage,
        selected_height=selected_height,
        sort_by=sort_by,
        all_locations=all_locations,
        current_page=page,
        total_pages=total_pages,
        total_cabinets=total,
        per_page=per_page,
        total_u=total_u,  # 总U位
        used_u=used_u     # 已使用U位
    )

#  cabinet_add 函数

@cabinet_bp.route('/add', methods=['GET', 'POST'])
def cabinet_add():
    """添加机柜"""
    if request.method == 'POST':
        # 获取所有表单字段
        name = request.form.get('name', '').strip()
        location_id = request.form.get('location_id')
        model = request.form.get('model', '').strip() or None
        manufacturer = request.form.get('manufacturer', '').strip() or None
        height_u = request.form.get('height_u', type=int)
        width = request.form.get('width', type=int) or None
        depth = request.form.get('depth', type=int) or None
        weight_capacity = request.form.get('weight_capacity', type=int) or None
        power_supply = request.form.get('power_supply', '').strip() or None
        network_access = request.form.get('network_access', '').strip() or None
        cooling_system = request.form.get('cooling_system', '').strip() or None
        description = request.form.get('description', '').strip() or None
        notes = request.form.get('notes', '').strip() or None
        tags = request.form.get('tags', '').strip() or None

        # 验证必填字段
        if not name:
            flash('机柜名称不能为空', 'error')
            return redirect(url_for('cabinet.cabinet_add'))
        if not location_id:
            flash('请选择所属位置', 'error')
            return redirect(url_for('cabinet.cabinet_add'))
        if not height_u or height_u < 1 or height_u > 100:
            flash('请输入有效的U位高度（1-100）', 'error')
            return redirect(url_for('cabinet.cabinet_add'))

        # 创建机柜对象
        cabinet = Cabinet(
            name=name,
            location_id=int(location_id),
            model=model,
            manufacturer=manufacturer,
            height_u=height_u,
            width=width,
            depth=depth,
            weight_capacity=weight_capacity,
            power_supply=power_supply,
            network_access=network_access,
            cooling_system=cooling_system,
            description=description,
            notes=notes,
            tags=tags
        )
        db.session.add(cabinet)
        db.session.commit()
        log_audit('create', 'cabinet', cabinet.id, f"创建机柜: {cabinet.name}", details={'location_id': location_id, 'height_u': height_u})
        flash('机柜添加成功！', 'success')
        return redirect(url_for('cabinet.cabinet_list'))

    # GET 请求：获取位置列表并渲染表单
    locations = Location.query.order_by(Location.name).all()
    return render_template('/cabinet/cabinet_add.html', locations=locations)

# cabinet.py - 在适当位置添加 cabinet_detail 路由

# ==================== 机柜详情路由 ====================
# cabinet.py - 更新 cabinet_detail 函数

@cabinet_bp.route('/<int:id>')
@login_required
@permission_required('cabinet:view')
def cabinet_detail(id):
    """查看机柜详情"""
    try:
        cabinet = Cabinet.query.get_or_404(id)
        
        # 获取机柜中的设备（按U位排序）
        devices = Device.query.filter_by(cabinet_id=cabinet.id)\
                             .order_by(Device.position_u.asc())\
                             .all()
        
        # 计算U位使用情况
        used_u_count = sum(device.height_u for device in devices if device.position_u)
        total_u = cabinet.height_u or 42
        available_u = total_u - used_u_count
        usage_percent = (used_u_count / total_u * 100) if total_u > 0 else 0
        
        # 构建U位槽位图
        u_slots = {}
        for device in devices:
            if device.position_u:
                start_u = device.position_u
                end_u = start_u + device.height_u - 1
                for u in range(start_u, end_u + 1):
                    if u <= total_u:
                        u_slots[u] = {
                            'device_id': device.id,
                            'device_name': device.name,
                            'device_type': device.device_type,
                            'status': device.status,
                            'height_u': device.height_u,
                            'start_u': start_u,
                            'end_u': end_u
                        }

        # 获取U位使用情况
        usage_info = cabinet.get_u_availability()
        
        # 获取位置信息
        location_name = cabinet.location.name if cabinet.location else '未指定位置'
        location_id = cabinet.location_id
        
        # 准备数据传递给模板
        context = {
            'cabinet': cabinet,
            'devices': devices,
            'u_slots': u_slots,
            'location_name': location_name,
            'location_id': location_id,
            'total_u': total_u,
            'used_u': used_u_count,
            'usage_info':usage_info,
            'available_u': available_u,
            'usage_percent': round(usage_percent, 1),
            'cabinet_id': cabinet.id,  # 添加 cabinet_id
            'device_count': len(devices),  # 添加设备数量
        }
        

        return render_template(
            '/cabinet/cabinet_detail.html',
            **context
        )
        
    except Exception as e:
        current_app.logger.error(f"加载机柜详情失败: {str(e)}")
        flash(f'加载机柜详情失败: {str(e)}', 'error')
        return redirect(url_for('cabinet.cabinet_list'))



@cabinet_bp.route('/cabinet/<int:id>/edit', methods=['GET', 'POST'])
def cabinet_edit(id):
    cabinet = Cabinet.query.options(joinedload(Cabinet.devices)).get_or_404(id)
    locations = Location.query.all()
    
    if request.method == 'POST':
        cabinet.name = request.form['name']
        cabinet.location_id = request.form['location_id']
        cabinet.model = request.form.get('model')
        cabinet.manufacturer = request.form.get('manufacturer')
        cabinet.height_u = request.form.get('height_u', type=int)
        cabinet.width = request.form.get('width', type=int)
        cabinet.depth = request.form.get('depth', type=int)
        cabinet.weight_capacity = request.form.get('weight_capacity', type=int)
        cabinet.power_supply = request.form.get('power_supply')
        cabinet.network_access = request.form.get('network_access')
        cabinet.cooling_system = request.form.get('cooling_system')
        cabinet.description = request.form.get('description')
        cabinet.notes = request.form.get('notes')
        cabinet.tags = request.form.get('tags')
        
        db.session.commit()
        log_audit('update', 'cabinet', cabinet.id, f"更新机柜: {cabinet.name}")
        flash('机柜信息已更新', 'success')
        return redirect(url_for('cabinet.cabinet_detail', id=cabinet.id))
    
    return render_template('/cabinet/cabinet_edit.html', cabinet=cabinet, locations=locations)
# cabinet.py - 更新 cabinet_import 函数





class CabinetImportForm(FlaskForm):
    file = FileField('Excel文件', validators=[InputRequired()])
    skip_duplicates = BooleanField('跳过重复', default=True)
    update_existing = BooleanField('更新现有')
    validate_location = BooleanField('验证位置', default=True)

@cabinet_bp.route('/import', methods=['GET', 'POST'])
def cabinet_import():
    form = CabinetImportForm()
    locations = {loc.id: loc for loc in Location.query.all()}  # 用于快速验证位置ID
    
    if request.method == 'POST' and form.validate_on_submit():
        f = form.file.data
        if f is None or f.filename == '':
            flash('未选择文件', 'danger')
            return redirect(url_for('cabinet.cabinet_import'))
        # 仅允许 Excel 文件，防止上传恶意脚本/HTML 造成存储型 XSS 或代码执行
        ext = os.path.splitext(f.filename)[1].lower()
        if ext not in ('.xlsx', '.xls'):
            flash('仅支持 .xlsx / .xls 格式的 Excel 文件', 'danger')
            return redirect(url_for('cabinet.cabinet_import'))
        filename = secure_filename(f.filename)
        # 保存临时文件（或直接读取到内存）
        filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
        f.save(filepath)
        
        try:
            df = pd.read_excel(filepath, dtype=str)  # 先全部读取为字符串
            # 清理列名：去除空格和特殊字符
            df.columns = df.columns.str.strip()
            
            # 定义字段映射（Excel列名 -> 模型字段名）
            field_mapping = {
                '机柜名称': 'name',
                '位置ID': 'location_id',
                '机柜型号': 'model',
                '制造厂商': 'manufacturer',
                'U位高度': 'height_u',
                '宽度(mm)': 'width',
                '深度(mm)': 'depth',
                '承重(kg)': 'weight_capacity',
                '电源容量(KW)': 'power_capacity',
                '电源配置': 'power_supply',
                '网络接入': 'network_access',
                '制冷系统': 'cooling_system',
                '标签': 'tags',
                '描述': 'description',
                '备注': 'notes'
            }
            
            # 检查必填列是否存在
            required_columns = ['机柜名称', '位置ID']
            missing = [col for col in required_columns if col not in df.columns]
            if missing:
                flash(f'Excel文件中缺少必填列: {", ".join(missing)}', 'error')
                return redirect(url_for('cabinet.cabinet_import'))
            
            # 统计信息
            stats = {'total': len(df), 'success': 0, 'skipped': 0, 'failed': 0, 'errors': []}
            
            for idx, row in df.iterrows():
                row_num = idx + 2  # Excel行号（第1行为标题）
                name = str(row.get('机柜名称', '')).strip()
                if not name:
                    stats['failed'] += 1
                    stats['errors'].append(f'第{row_num}行: 机柜名称为空')
                    continue
                
                # 处理位置ID
                location_id_raw = row.get('位置ID', '')
                if pd.isna(location_id_raw) or str(location_id_raw).strip() == '':
                    if form.validate_location.data:
                        stats['failed'] += 1
                        stats['errors'].append(f'第{row_num}行: 位置ID不能为空')
                        continue
                    else:
                        location_id = None
                else:
                    try:
                        location_id = int(float(location_id_raw))
                    except:
                        stats['failed'] += 1
                        stats['errors'].append(f'第{row_num}行: 位置ID必须是整数')
                        continue
                    if form.validate_location.data and location_id not in locations:
                        stats['failed'] += 1
                        stats['errors'].append(f'第{row_num}行: 位置ID {location_id} 不存在于系统中')
                        continue
                
                # 检查机柜是否已存在
                existing = Cabinet.query.filter_by(name=name).first()
                if existing:
                    if form.skip_duplicates.data and not form.update_existing.data:
                        stats['skipped'] += 1
                        continue
                    elif form.update_existing.data:
                        cabinet = existing
                    else:
                        stats['failed'] += 1
                        stats['errors'].append(f'第{row_num}行: 机柜 "{name}" 已存在，且未选择更新模式')
                        continue
                else:
                    cabinet = Cabinet()
                
                # 填充字段
                cabinet.name = name
                cabinet.location_id = location_id
                
                # 可选字段
                cabinet.model = _safe_str(row.get('机柜型号'))
                cabinet.manufacturer = _safe_str(row.get('制造厂商'))
                cabinet.height_u = _safe_int(row.get('U位高度'), default=42)
                cabinet.width = _safe_int(row.get('宽度(mm)'))
                cabinet.depth = _safe_int(row.get('深度(mm)'))
                cabinet.weight_capacity = _safe_int(row.get('承重(kg)'))
                cabinet.power_capacity = _safe_float(row.get('电源容量(KW)'))
                cabinet.power_supply = _safe_str(row.get('电源配置'))
                cabinet.network_access = _safe_str(row.get('网络接入'))
                cabinet.cooling_system = _safe_str(row.get('制冷系统'))
                cabinet.tags = _safe_str(row.get('标签'))
                cabinet.description = _safe_str(row.get('描述'))
                cabinet.notes = _safe_str(row.get('备注'))
                
                # 时间戳会自动处理
                db.session.add(cabinet)
                stats['success'] += 1
            
            db.session.commit()
            log_audit('create', 'cabinet', None, f"导入机柜: 成功{stats['success']}条", details={'success': stats['success'], 'skipped': stats['skipped'], 'failed': stats['failed']})

            # 清理临时文件
            os.remove(filepath)

            # 返回结果（可通过session传递统计信息，或使用AJAX）
            flash(f'导入完成: 成功{stats["success"]}条, 跳过{stats["skipped"]}条, 失败{stats["failed"]}条',
                  'success' if stats['failed']==0 else 'warning')
            if stats['errors']:
                for err in stats['errors'][:5]:
                    flash(err, 'error')
            return redirect(url_for('cabinet.cabinet_list'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'导入失败: {str(e)}', 'error')
            return redirect(url_for('cabinet.cabinet_import'))
    
    return render_template('cabinet/cabinet_import.html', form=form)

# 辅助函数
def _safe_str(value):
    if pd.isna(value):
        return None
    s = str(value).strip()
    return s if s else None

def _safe_int(value, default=None):
    if pd.isna(value):
        return default
    try:
        return int(float(value))
    except:
        return default

def _safe_float(value, default=None):
    if pd.isna(value):
        return default
    try:
        return float(value)
    except:
        return default


@cabinet_bp.route('/export')
def cabinet_export():
    """导出机柜（包含所有扩展字段）"""
    from io import BytesIO
    import pandas as pd
    from openpyxl.styles import Font, PatternFill, Alignment
    from datetime import datetime, timedelta

    # 使用 joinedload 预加载关联数据，提高性能
    cabinets = Cabinet.query.options(joinedload(Cabinet.location)).all()
    
    data = []
    for cabinet in cabinets:
        # 获取U位使用情况
        u_availability = cabinet.get_u_availability()
        
        data.append({
            '机柜ID': cabinet.id,
            '机柜名称': cabinet.name,
            '位置': cabinet.location.name if cabinet.location else '',
            '位置ID': cabinet.location_id,
            '机柜型号': cabinet.model or '',
            '制造厂商': cabinet.manufacturer or '',
            '总容量(U)': cabinet.height_u,
            '已用容量(U)': u_availability['used'],
            '剩余容量(U)': u_availability['remaining'],
            '使用率': f"{u_availability['usage_percentage']}%",
            '宽度(mm)': cabinet.width or '',
            '深度(mm)': cabinet.depth or '',
            '承重(kg)': cabinet.weight_capacity or '',
            '电源容量(KW)': cabinet.power_capacity or '',
            '电源配置': cabinet.power_supply or '',
            '网络接入': cabinet.network_access or '',
            '制冷系统': cabinet.cooling_system or '',
            '标签': cabinet.tags or '',
            '描述': cabinet.description or '',
            '备注': cabinet.notes or '',
            '设备数量': cabinet.device_count,
            '创建时间': (cabinet.created_at + timedelta(hours=8)).strftime('%Y-%m-%d %H:%M:%S') if cabinet.created_at else '',
            '更新时间': (cabinet.updated_at + timedelta(hours=8)).strftime('%Y-%m-%d %H:%M:%S') if cabinet.updated_at else ''
        })
    
    # 创建DataFrame
    df = pd.DataFrame(data)
    
    # 创建内存中的Excel文件
    output = BytesIO()
    
    # 使用openpyxl引擎写入Excel
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='机柜列表')
        
        # 获取工作簿和工作表
        workbook = writer.book
        worksheet = writer.sheets['机柜列表']
        
        # 设置列宽（根据内容调整）
        column_widths = {
            'A': 10,   # 机柜ID
            'B': 20,   # 机柜名称
            'C': 25,   # 位置
            'D': 10,   # 位置ID
            'E': 15,   # 机柜型号
            'F': 15,   # 制造厂商
            'G': 12,   # 总容量(U)
            'H': 12,   # 已用容量(U)
            'I': 12,   # 剩余容量(U)
            'J': 10,   # 使用率
            'K': 12,   # 宽度(mm)
            'L': 12,   # 深度(mm)
            'M': 12,   # 承重(kg)
            'N': 15,   # 电源容量(KW)
            'O': 30,   # 电源配置
            'P': 30,   # 网络接入
            'Q': 20,   # 制冷系统
            'R': 20,   # 标签
            'S': 30,   # 描述
            'T': 30,   # 备注
            'U': 10,   # 设备数量
            'V': 20,   # 创建时间
            'W': 20    # 更新时间
        }
        
        for col, width in column_widths.items():
            worksheet.column_dimensions[col].width = width
        
        # 设置标题行样式
        header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
        header_font = Font(bold=True, color="FFFFFF")
        header_alignment = Alignment(horizontal="center", vertical="center")
        
        for cell in worksheet[1]:
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = header_alignment
    
    output.seek(0)
    
    # 生成文件名
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'机柜列表_导出_{timestamp}.xlsx'
    
    return send_file(
        output,
        as_attachment=True,
        download_name=filename,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
@cabinet_bp.route('/cabinets/<int:id>/delete', methods=['POST'])
@login_required
@permission_required('cabinet:edit')
def cabinet_delete(id):
    cabinet = Cabinet.query.get_or_404(id)
    cabinet_name = cabinet.name
    device_count = cabinet.device_count  # 可选，用于提示

    try:
        db.session.delete(cabinet)
        db.session.commit()
        log_audit('delete', 'cabinet', id, f"删除机柜: {cabinet_name}", details={'device_count': device_count})
        return jsonify({
            'success': True,
            'message': f'机柜 "{cabinet_name}" 及其关联的 {device_count} 个设备已删除'
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'删除失败: {str(e)}'
        }), 500

@cabinet_bp.route('/cabinet/bulk_delete', methods=['POST'])
@login_required
@permission_required('cabinet:edit')
def cabinet_bulk_delete():
    """批量删除机柜（前端以 JSON 方式调用，返回 JSON）"""

    try:
        data = request.get_json(silent=True)
        if data is None:
            # 兼容 form 提交
            cabinet_ids = request.form.get('cabinet_ids', request.form.get('ids', '')).split(',')
            cabinet_ids = [int(i) for i in cabinet_ids if i.strip().isdigit()]
        else:
            cabinet_ids = data.get('ids', data.get('cabinet_ids', []))
            cabinet_ids = [int(i) for i in cabinet_ids if str(i).strip().isdigit()]

        if not cabinet_ids:
            return jsonify({'success': False, 'message': '请选择要删除的机柜'}), 400

        # 预加载所有待删除的机柜
        cabinets_to_delete = []
        not_found = []
        for cid in cabinet_ids:
            cab = Cabinet.query.get(cid)
            if cab:
                cabinets_to_delete.append(cab)
            else:
                not_found.append(cid)

        if not cabinets_to_delete:
            return jsonify({'success': False, 'message': '未找到有效的机柜进行删除'}), 400

        # 收集所有受影响设备的 ID（用于清理关联数据）
        all_device_ids = []
        for cab in cabinets_to_delete:
            dev_ids = [d.id for d in Device.query.filter_by(cabinet_id=cab.id).with_entities(Device.id).all()]
            all_device_ids.extend(dev_ids)

        # 如果有设备，先清理设备关联数据（与 batch_delete_devices 逻辑一致）
        if all_device_ids:
            # 1. 删除设备监控配置
            DeviceMonitorConfig.query.filter(
                DeviceMonitorConfig.device_id.in_(all_device_ids)
            ).delete(synchronize_session=False)

            # 2. 删除告警事件
            AlertEvent.query.filter(
                AlertEvent.device_id.in_(all_device_ids)
            ).delete(synchronize_session=False)

            # 3. 删除各类监控数据
            MonitorData.query.filter(
                MonitorData.device_id.in_(all_device_ids)
            ).delete(synchronize_session=False)

            DeviceMonitorLog.query.filter(
                DeviceMonitorLog.device_id.in_(all_device_ids)
            ).delete(synchronize_session=False)

            InterfaceMonitorData.query.filter(
                InterfaceMonitorData.device_id.in_(all_device_ids)
            ).delete(synchronize_session=False)

            # 4. 删除库存事务
            InventoryTransaction.query.filter(
                InventoryTransaction.device_id.in_(all_device_ids)
            ).delete(synchronize_session=False)

            # 5. 删除拓扑连接（source 或 target）
            ConnectionPath.query.filter(
                or_(
                    ConnectionPath.source_device_id.in_(all_device_ids),
                    ConnectionPath.target_device_id.in_(all_device_ids)
                )
            ).delete(synchronize_session=False)

        # 逐个删除机柜（ORM 级联：cabinet → devices → interfaces）
        deleted_count = 0
        for cab in cabinets_to_delete:
            db.session.delete(cab)
            deleted_count += 1

        db.session.commit()

        log_audit('delete', 'cabinet', None,
                  f"批量删除 {deleted_count} 个机柜",
                  details={'deleted_count': deleted_count, 'cabinet_ids': cabinet_ids, 'device_count': len(all_device_ids)})

        # 记录操作日志
        log = OperationLog(
            user_id=current_user.id,
            username=current_user.username,
            operation_type='bulk_delete',
            resource_type='cabinet',
            resource_name=f'{deleted_count}个机柜',
            details=f'批量删除了{deleted_count}个机柜，ID: {cabinet_ids}',
            ip_address=request.remote_addr,
            user_agent=request.user_agent.string
        )
        db.session.add(log)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': f'成功删除 {deleted_count} 个机柜',
            'deleted_count': deleted_count
        })

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"批量删除机柜失败: {e}", exc_info=True)
        return jsonify({'success': False, 'message': f'删除失败: {str(e)}'}), 500





@cabinet_bp.route('api/cabinet/<int:id>/u-slots')
def cabinet_u_slots(id):
    cabinet = Cabinet.query.get_or_404(id)
    usage_info = cabinet.get_u_availability()
    u_slots = {}
    for device in cabinet.devices:
        if device.position_u:
            for u in range(device.position_u, device.position_u + device.height_u):
                if u <= cabinet.height_u:
                    u_slots[u] = {
                        'id': device.id,
                        'name': device.name,
                        'ip_address': device.ip_address,
                        'asset_number': device.asset_number
                    }
    return jsonify({
        'id': cabinet.id,
        'name': cabinet.name,
        'height_u': cabinet.height_u,
        'u_slots': u_slots,
        'usage_percentage': usage_info['usage_percentage'],
        'used': usage_info['used'],
        'remaining': usage_info['remaining']
    })
@cabinet_bp.route('/cabinet/<int:cabinet_id>/device/add', methods=['POST'])
@login_required
@permission_required('cabinet:edit')
def add_device_to_cabinet(cabinet_id):
    """在机柜中添加设备"""
    cabinet = Cabinet.query.get_or_404(cabinet_id)
    
    try:
        # 获取表单数据
        name = request.form.get('name', '').strip()
        management_ip = request.form.get('management_ip', '').strip()  # 【新增】获取管理IP
        position_u = int(request.form.get('position_u', 1))
        height_u = int(request.form.get('height_u', 1))
        ip_address = request.form.get('ip_address', '').strip()
        device_type = request.form.get('device_type', 'server')       # 【新增】设备类型
        brand = request.form.get('brand', '')                         # 【新增】厂商
        model = request.form.get('model', '').strip()
        status = request.form.get('status', 'active')
        mac_address = request.form.get('mac_address', '').strip()     # 【新增】MAC地址
        description = request.form.get('description', '').strip()
        
        # 验证U位是否可用（原有代码保持不变）
        if position_u < 1 or position_u + height_u - 1 > cabinet.height_u:
            flash('U位超出机柜范围！', 'danger')
            return redirect(url_for('cabinet.cabinet_detail', id=cabinet_id))
        
        existing_devices = Device.query.filter_by(cabinet_id=cabinet_id).all()
        for u in range(position_u, position_u + height_u):
            for device in existing_devices:
                if device.position_u and u >= device.position_u and u < device.position_u + device.height_u:
                    flash(f'U位 {u} 已被设备 {device.name} 占用！', 'danger')
                    return redirect(url_for('cabinet.cabinet_detail', id=cabinet_id))
        
        # 创建新设备（添加所有字段）
        device = Device(
            name=name,
            management_ip=management_ip,      # 【新增】
            cabinet_id=cabinet_id,
            position_u=position_u,
            height_u=height_u,
            ip_address=ip_address,
            device_type=device_type,          # 【新增】
            brand=brand,                      # 【新增】
            model=model,
            status=status,
            mac_address=mac_address,          # 【新增】
            description=description,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        
        db.session.add(device)
        db.session.commit()
        log_audit('create', 'device', device.id, f"在机柜中创建设备: {name}", details={'cabinet_id': cabinet_id, 'position_u': position_u, 'height_u': height_u})

        flash(f'设备 "{name}" 添加成功！', 'success')
        return redirect(url_for('cabinet.cabinet_detail', id=cabinet_id))
        
    except Exception as e:
        db.session.rollback()
        flash(f'添加设备失败: {str(e)}', 'danger')
        return redirect(url_for('cabinet.cabinet_detail', id=cabinet_id))



@cabinet_bp.route('/api/cabinets/rack-summary')
@login_required
@permission_required('cabinet:view')
def get_cabinets_rack_summary():
    """API: 获取所有机柜的概要信息（用于dashboard）"""
    try:
        cabinets = Cabinet.query.order_by(Cabinet.name).all()
        
        summary = []
        for cabinet in cabinets:
            # 计算U位使用情况
            devices = Device.query.filter_by(cabinet_id=cabinet.id).all()
            used_u = sum(device.height_u for device in devices if device.position_u)
            total_u = cabinet.height_u or 42
            usage_percent = (used_u / total_u * 100) if total_u > 0 else 0
            
            # 计算在线设备数量
            online_devices = sum(1 for device in devices if device.status == 'online')
            
            summary.append({
                'id': cabinet.id,
                'name': cabinet.name,
                'location': cabinet.location.name if cabinet.location else '未指定',
                'total_slots': total_u,
                'used_slots': used_u,
                'usage_percent': round(usage_percent, 1),
                'total_devices': len(devices),
                'online_devices': online_devices,
                'location_id': cabinet.location_id
            })
        
        return jsonify({
            'success': True,
            'total_cabinets': len(cabinets),
            'avg_usage_percent': round(sum(c['usage_percent'] for c in summary) / len(summary), 1) if summary else 0,
            'cabinets': summary
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500

@cabinet_bp.route('/cabinet/visual/<int:id>')
@login_required
@permission_required('cabinet:view')
def cabinet_visual(id):
    """机柜可视化视图（3D/2D视图）"""
    cabinet = Cabinet.query.get_or_404(id)
    
    # 获取机柜中的设备
    devices = Device.query.filter_by(cabinet_id=cabinet.id)\
                         .order_by(Device.position_u.asc())\
                         .all()
    
    # 准备可视化数据
    visual_data = {
        'cabinet': {
            'id': cabinet.id,
            'name': cabinet.name,
            'total_u': cabinet.height_u or 42,
            'width': 600,  # 可视化宽度
            'depth': 1000,  # 可视化深度
            'location': cabinet.location.name if cabinet.location else '未指定'
        },
        'devices': []
    }
    
    # 定义设备类型颜色
    device_colors = {
        'router': '#007bff',      # 蓝色
        'switch': '#28a745',      # 绿色
        'firewall': '#ffc107',    # 黄色
        'server': '#6f42c1',      # 紫色
        'storage': '#e83e8c',
        'ap': '#17a2b8',           # 青色（无线AP）     # 粉色
        'unknown': '#6c757d'      # 灰色
    }
    
    for device in devices:
        if device.position_u and device.height_u:
            visual_data['devices'].append({
                'id': device.id,
                'name': device.name,
                'type': device.device_type,
                'status': device.status,
                'start_u': device.position_u,
                'height_u': device.height_u,
                'color': device_colors.get(device.device_type, '#6c757d'),
                'ip': device.management_ip,
                'model': device.model,
                'brand': device.brand
            })
    
    #return render_template('cabinet/visual.html', visual_data=visual_data)
    u_info = cabinet.get_u_availability()  # ←←← 关键：定义 u_info
    
    return render_template(
        'cabinet/visual.html',
        cabinet=cabinet,
        devices=cabinet.devices,
        total_u=u_info['total'],
        used_u=u_info['used'],
        available_u=u_info['remaining'],
        usage_percent=u_info['usage_percentage'],
        u_slots=u_info['u_slots']
    )

# @cabinet_bp.route('/api/cabinets/<int:id>/assign-device', methods=['POST'])
# @login_required
# def assign_device_to_cabinet(id):
#     """API: 分配设备到机柜"""
#     try:
#         data = request.get_json()
#         device_id = data.get('device_id')
#         position_u = data.get('position_u')
#         height_u = data.get('height_u', 1)
        
#         if not device_id or not position_u:
#             return jsonify({
#                 'success': False,
#                 'message': '设备ID和U位位置不能为空'
#             }), 400
        
#         cabinet = Cabinet.query.get_or_404(id)
#         device = Device.query.get_or_404(device_id)
        
#         # 检查U位是否可用
#         if position_u < 1 or position_u + height_u - 1 > cabinet.height_u:
#             return jsonify({
#                 'success': False,
#                 'message': f'U位位置超出机柜范围 (1-{cabinet.height_u})'
#             }), 400
        
#         # 检查U位是否被占用
#         existing_devices = Device.query.filter_by(cabinet_id=id).all()
#         for u in range(position_u, position_u + height_u):
#             for existing_device in existing_devices:
#                 if existing_device.id != device_id and existing_device.position_u:
#                     existing_start = existing_device.position_u
#                     existing_end = existing_start + existing_device.height_u - 1
#                     if existing_start <= u <= existing_end:
#                         return jsonify({
#                             'success': False,
#                             'message': f'U位 {u} 已被设备 {existing_device.name} 占用'
#                         }), 400
        
#         # 更新设备位置
#         device.cabinet_id = id
#         device.position_u = position_u
#         device.height_u = height_u
#         device.updated_at = datetime.utcnow()
        
#         db.session.commit()
        
#         # 记录操作日志
#         log_operation('assign', 'device', device.id, device.name, 
#                      f'分配设备到机柜 {cabinet.name}，U位 {position_u}-{position_u + height_u - 1}')
        
#         return jsonify({
#             'success': True,
#             'message': f'设备 {device.name} 已成功分配到机柜 {cabinet.name}',
#             'device': {
#                 'id': device.id,
#                 'name': device.name,
#                 'position_u': device.position_u,
#                 'height_u': device.height_u
#             }
#         })
        
#     except Exception as e:
#         db.session.rollback()
#         return jsonify({
#             'success': False,
#             'message': f'分配失败: {str(e)}'
#         }), 500

@cabinet_bp.route('/device/<int:id>')
@login_required
@permission_required('cabinet:view')
def device_detail(id):
    """设备详情 - 支持HTML和JSON响应"""
    device = Device.query.get_or_404(id)
    
    # 检查请求是否要求JSON
    if request.headers.get('Accept') == 'application/json' or request.is_json:
        return jsonify({
            'success': True,
            'device': {
                'id': device.id,
                'name': device.name,
                'management_ip': device.management_ip,
                'ip_address': device.ip_address,
                'position_u': device.position_u,
                'height_u': device.height_u,
                'device_type': device.device_type,
                'brand': device.brand,
                'model': device.model,
                'status': device.status,
                'mac_address': device.mac_address,
                'description': device.description,
                'cabinet_id': device.cabinet_id
            }
        })
    
    # 否则返回HTML页面
    return render_template('device_detail.html', device=device)

@cabinet_bp.route('/api/cabinets/<int:id>/remove-device/<int:device_id>', methods=['POST'])
@login_required
@permission_required('cabinet:edit')
def remove_device_from_cabinet_api(id, device_id):
    """API: 从机柜中移除设备"""
    try:
        cabinet = Cabinet.query.get_or_404(id)
        device = Device.query.get_or_404(device_id)
        
        if device.cabinet_id != id:
            return jsonify({
                'success': False,
                'message': '该设备不在指定机柜中'
            }), 400
        
        # 移除设备
        device.cabinet_id = None
        device.position_u = None
        device.height_u = 1
        device.updated_at = datetime.utcnow()
        
        db.session.commit()
        log_audit('update', 'device', device.id, f"从机柜移除设备: {device.name}", details={'cabinet_id': id, 'cabinet_name': cabinet.name})

        return jsonify({
            'success': True,
            'message': f'设备 {device.name} 已从机柜 {cabinet.name} 中移除'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'移除失败: {str(e)}'
        }), 500



# @cabinet_bp.route('/device/<int:id>/edit', methods=['POST'])
# @login_required
# def device_edit(id):  # 改为 device_edit
#     """编辑设备 - 支持表单提交和JSON响应"""
#     device = Device.query.get_or_404(id)
    
#     # 处理表单数据
#     device.name = request.form.get('name')
#     device.management_ip = request.form.get('management_ip')
#     device.ip_address = request.form.get('ip_address')
#     device.position_u = int(request.form.get('position_u', 1))
#     device.height_u = int(request.form.get('height_u', 1))
#     device.device_type = request.form.get('device_type', 'server')
#     device.brand = request.form.get('brand')
#     device.model = request.form.get('model')
#     device.status = request.form.get('status', 'active')
#     device.mac_address = request.form.get('mac_address')
#     device.description = request.form.get('description')
    
#     try:
#         db.session.commit()
#         # 返回JSON响应
#         return jsonify({'success': True, 'message': '设备更新成功'})
#     except Exception as e:
#         db.session.rollback()
#         return jsonify({'success': False, 'message': f'更新失败: {str(e)}'}), 500


@cabinet_bp.route('/devices/<int:id>/edit', methods=['POST'])
def edit_device(id):
    device = Device.query.get_or_404(id)
    try:
        # 打印原始值
        old_mgmt_ip = device.management_ip
        print(f"Before update: management_ip = {old_mgmt_ip}")
        
        # 获取表单数据
        management_ip = request.form.get('management_ip', '').strip()
        print(f"Received management_ip from form: {management_ip}")
        
        # 更新字段
        device.management_ip = management_ip  
       # 获取表单数据，对于必填字段进行验证
        name = request.form.get('name', '').strip()
        if not name:
            raise ValueError("设备名称不能为空")
        
        management_ip = request.form.get('management_ip', '').strip()
        if not management_ip:
            raise ValueError("管理IP地址不能为空")
        
        # 更新字段
        device.name = name
        device.management_ip = management_ip
        device.ip_address = request.form.get('ip_address', '').strip()
        device.position_u = int(request.form.get('position_u', device.position_u))
        device.height_u = int(request.form.get('height_u', device.height_u))
        device.device_type = request.form.get('device_type', device.device_type)
        device.brand = request.form.get('brand', device.brand)
        device.model = request.form.get('model', device.model)
        device.status = request.form.get('status', device.status)
        device.mac_address = request.form.get('mac_address', '').strip()
        device.description = request.form.get('description', '').strip()
        device.updated_at = datetime.utcnow()
        
        db.session.commit()
        log_audit('update', 'device', device.id, f"更新设备: {device.name}", details={'management_ip': device.management_ip})

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': True, 'message': '设备更新成功'})
        flash('设备更新成功', 'success')
        return redirect(url_for('cabinet.cabinet_detail', id=device.cabinet_id))

    except ValueError as ve:
        db.session.rollback()
        error_msg = str(ve)
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': error_msg}), 400
        flash(error_msg, 'danger')
        return redirect(url_for('cabinet.cabinet_detail', id=device.cabinet_id))

    except Exception as e:
        db.session.rollback()
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': str(e)}), 500
        flash(f'更新失败: {str(e)}', 'danger')
        return redirect(url_for('cabinet.cabinet_detail', id=device.cabinet_id))



@cabinet_bp.route('/device/<int:id>/delete', methods=['POST'])
@login_required
@permission_required('cabinet:edit')
def delete_device(id):
    """删除设备"""
    device = Device.query.get_or_404(id)
    
    try:
        # 与 devices 列表删除同源：清空全部 FK 子行，避免 ORM 对 NOT NULL 外键置 NULL 报 1048
        from blueprints.device import _purge_device_children
        _purge_device_children([device.id])
        db.session.delete(device)
        db.session.commit()
        log_audit('delete', 'device', id, f"删除设备: {device.name}")
        return jsonify({'success': True, 'message': '设备删除成功'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'删除失败: {str(e)}'}), 500


# ==============================================================
# 机柜视图（交互式：左黑底机柜立面 + 右基本信息/编辑面板）
# ==============================================================

def _is_valid_ipv4(addr):
    """简单的IPv4格式校验（空值返回False）"""
    if not addr:
        return False
    import ipaddress
    try:
        ipaddress.IPv4Address(addr)
        return True
    except Exception:
        return False


def _is_valid_mac(addr):
    if not addr:
        return True
    import re
    return bool(re.match(r'^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$', addr))


def _build_device_detail_dict(device):
    """构造设备完整信息字典，供前端编辑表单预填"""
    return {
        'id': device.id,
        'name': device.name or '',
        'device_type': device.device_type or 'server',
        'brand': device.brand or '',
        'manufacturer': device.manufacturer or '',
        'model': device.model or '',
        'serial_number': device.serial_number or '',
        'asset_number': device.asset_number or '',
        'management_ip': device.management_ip or '',
        'ip_address': device.ip_address or '',
        'mac_address': device.mac_address or '',
        'status': device.status or 'unknown',
        'position_u': device.position_u,
        'height_u': device.height_u or 1,
        'owner': device.owner or '',
        'department': device.department or '',
        'cabinet_id': device.cabinet_id,
        'location_id': device.location_id,
        'description': device.description or '',
    }


def _dup_exists(field, value, exclude_id):
    """检查某字段值是否已存在（排除 exclude_id 自身；exclude_id 为 None 时检查全部）"""
    if not value:
        return False
    q = Device.query.filter(field == value)
    if exclude_id is not None:
        q = q.filter(Device.id != exclude_id)
    return q.first() is not None


def _validate_device_fields(data, exclude_id=None):
    """校验设备通用字段，返回错误列表"""
    errors = []
    name = (data.get('name') or '').strip()
    management_ip = (data.get('management_ip') or '').strip()

    if not name:
        errors.append('设备名称不能为空')
    elif _dup_exists(Device.name, name, exclude_id):
        errors.append(f'设备名称 "{name}" 已被其他设备使用')

    if not management_ip:
        errors.append('管理IP地址不能为空')
    elif not _is_valid_ipv4(management_ip):
        errors.append('管理IP地址格式不正确')
    elif _dup_exists(Device.management_ip, management_ip, exclude_id):
        errors.append(f'管理IP地址 "{management_ip}" 已被其他设备使用')

    mac = (data.get('mac_address') or '').strip()
    if mac and not _is_valid_mac(mac):
        errors.append('MAC地址格式不正确（示例：00:1A:2B:3C:4D:5E）')

    asset_number = (data.get('asset_number') or '').strip()
    if asset_number and _dup_exists(Device.asset_number, asset_number, exclude_id):
        errors.append(f'资产编号 "{asset_number}" 已被其他设备使用')

    serial_number = (data.get('serial_number') or '').strip()
    if serial_number and _dup_exists(Device.serial_number, serial_number, exclude_id):
        errors.append(f'序列号 "{serial_number}" 已被其他设备使用')

    return errors


def _validate_u_overlap(cabinet, position_u, height_u, exclude_id=None):
    """校验U位范围与重叠，返回错误列表"""
    errors = []
    total = cabinet.height_u or 42
    if position_u is None:
        errors.append('起始U位不能为空')
        return errors
    if position_u < 1 or position_u > total:
        errors.append(f'起始U位必须在 1 到 {total} 之间')
        return errors
    if position_u + height_u - 1 > total:
        errors.append(f'设备高度超出机柜范围（机柜总高：{total}U）')
        return errors
    overlap = Device.query.filter(
        Device.cabinet_id == cabinet.id,
        Device.id != exclude_id,
        Device.position_u <= position_u + height_u - 1,
        Device.position_u + Device.height_u - 1 >= position_u
    ).all()
    if overlap:
        names = ', '.join([d.name for d in overlap])
        errors.append(f'U位与以下设备冲突：{names}')
    return errors


@cabinet_bp.route('/<int:id>/rack-editor')
@login_required
@permission_required('cabinet:view')
def cabinet_rack_editor(id):
    """机柜视图（交互式）：左黑底机柜立面 + 右基本信息/编辑面板（idcops风格）"""
    try:
        cabinet = Cabinet.query.get_or_404(id)
        devices = Device.query.filter_by(cabinet_id=cabinet.id).order_by(Device.position_u.asc()).all()
        used_u = sum((d.height_u or 1) for d in devices if d.position_u)
        total_u = cabinet.height_u or 42
        available_u = total_u - used_u
        usage_percent = round(used_u / total_u * 100, 1) if total_u > 0 else 0

        # 构建U位槽位图，供服务端首屏渲染（无JS也能看）
        u_slots = {}
        for device in devices:
            if device.position_u:
                for u in range(device.position_u, device.position_u + device.height_u):
                    if u <= total_u:
                        u_slots[u] = {
                            'device_id': device.id,
                            'name': device.name,
                            'device_type': device.device_type,
                            'status': device.status,
                            'height_u': device.height_u,
                            'is_start': (u == device.position_u),
                        }

        return render_template(
            'cabinet/rack_editor.html',
            cabinet=cabinet,
            devices=devices,
            total_u=total_u,
            used_u=used_u,
            available_u=available_u,
            usage_percent=usage_percent,
            u_slots=u_slots,
        )
    except Exception as e:
        current_app.logger.error(f"加载机柜交互视图失败: {str(e)}")
        flash(f'加载机柜交互视图失败: {str(e)}', 'error')
        return redirect(url_for('cabinet.cabinet_detail', id=id))


@cabinet_bp.route('/api/devices/library')
@login_required
@permission_required('cabinet:view')
def rack_device_library():
    """API: 设备库（未分配到任何机柜的设备），用于新增设备时从库中选择"""
    try:
        q = request.args.get('q', '').strip()
        query = Device.query.filter(Device.cabinet_id.is_(None))
        if q:
            query = query.filter(Device.name.like(f'%{q}%'))
        devices = query.order_by(Device.name).limit(200).all()
        return jsonify({
            'success': True,
            'devices': [_build_device_detail_dict(d) for d in devices]
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@cabinet_bp.route('/api/devices/<int:device_id>/detail')
@login_required
@permission_required('cabinet:view')
def rack_device_detail(device_id):
    """API: 获取设备完整信息，供编辑表单预填"""
    try:
        device = Device.query.get_or_404(device_id)
        return jsonify({'success': True, 'device': _build_device_detail_dict(device)})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@cabinet_bp.route('/api/cabinet/<int:cabinet_id>/rack-detail')
@login_required
@permission_required('cabinet:view')
def rack_detail_api(cabinet_id):
    """API: 返回机柜实时U位详情，供前端点击操作后局部刷新"""
    try:
        cabinet = Cabinet.query.get_or_404(cabinet_id)
        devices = Device.query.filter_by(cabinet_id=cabinet.id).all()
        total_u = cabinet.height_u or 42
        used_u = sum((d.height_u or 1) for d in devices if d.position_u)
        u_slots = {}
        for device in devices:
            if device.position_u:
                for u in range(device.position_u, device.position_u + device.height_u):
                    if u <= total_u:
                        u_slots[u] = {
                            'device_id': device.id,
                            'name': device.name,
                            'device_type': device.device_type,
                            'status': device.status,
                            'height_u': device.height_u,
                            'brand': device.brand,
                            'model': device.model,
                            'management_ip': device.management_ip,
                            'position_u': device.position_u,
                            'is_start': (u == device.position_u),
                        }
        return jsonify({
            'success': True,
            'cabinet': {
                'id': cabinet.id,
                'name': cabinet.name,
                'location_name': cabinet.location.name if cabinet.location else '未指定',
            },
            'total_u': total_u,
            'used_u': used_u,
            'available_u': total_u - used_u,
            'usage_percent': round(used_u / total_u * 100, 1) if total_u > 0 else 0,
            'u_slots': u_slots,
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@cabinet_bp.route('/api/cabinet/<int:cabinet_id>/assign', methods=['POST'])
@login_required
@permission_required('cabinet:edit')
def rack_assign_device(cabinet_id):
    """API: 将设备分配到机柜U位。
    - 若提供 device_id：从设备库选择并补充信息（更新该设备并落到指定U位）
    - 否则：新建一台设备并分配到指定U位
    """
    try:
        cabinet = Cabinet.query.get_or_404(cabinet_id)
        data = request.get_json(silent=True) or {}
        device_id = data.get('device_id')
        position_u = data.get('position_u')
        height_u = int(data.get('height_u', 1) or 1)

        try:
            position_u = int(position_u) if position_u not in (None, '') else None
        except (TypeError, ValueError):
            position_u = None

        # U位校验
        u_errors = _validate_u_overlap(cabinet, position_u, height_u,
                                       exclude_id=int(device_id) if device_id else None)
        if u_errors:
            return jsonify({'success': False, 'message': '；'.join(u_errors)}), 400

        if device_id:
            # 从设备库选择
            device = Device.query.get_or_404(int(device_id))
            errors = _validate_device_fields(data, exclude_id=device.id)
            if errors:
                return jsonify({'success': False, 'message': '；'.join(errors)}), 400

            device.name = (data.get('name') or '').strip() or device.name
            device.device_type = (data.get('device_type') or '').strip() or device.device_type
            device.brand = (data.get('brand') or '').strip() or None
            device.manufacturer = (data.get('manufacturer') or '').strip() or None
            device.model = (data.get('model') or '').strip() or None
            device.serial_number = (data.get('serial_number') or '').strip() or None
            device.asset_number = (data.get('asset_number') or '').strip() or None
            device.management_ip = (data.get('management_ip') or '').strip()
            device.ip_address = (data.get('ip_address') or '').strip() or None
            device.mac_address = (data.get('mac_address') or '').strip() or None
            device.status = (data.get('status') or 'unknown').strip()
            device.owner = (data.get('owner') or '').strip() or None
            device.department = (data.get('department') or '').strip() or None
            device.description = (data.get('description') or '').strip() or None
            device.cabinet_id = cabinet.id
            device.location_id = cabinet.location_id
            device.position_u = position_u
            device.height_u = height_u
            device.updated_at = datetime.utcnow()
            action = 'assign'
        else:
            # 新建设备
            errors = _validate_device_fields(data)
            if errors:
                return jsonify({'success': False, 'message': '；'.join(errors)}), 400
            device = Device(
                name=(data.get('name') or '').strip(),
                device_type=(data.get('device_type') or 'server').strip(),
                brand=(data.get('brand') or '').strip() or None,
                manufacturer=(data.get('manufacturer') or '').strip() or None,
                model=(data.get('model') or '').strip() or None,
                serial_number=(data.get('serial_number') or '').strip() or None,
                asset_number=(data.get('asset_number') or '').strip() or None,
                management_ip=(data.get('management_ip') or '').strip(),
                ip_address=(data.get('ip_address') or '').strip() or None,
                mac_address=(data.get('mac_address') or '').strip() or None,
                status=(data.get('status') or 'unknown').strip(),
                owner=(data.get('owner') or '').strip() or None,
                department=(data.get('department') or '').strip() or None,
                description=(data.get('description') or '').strip() or None,
                cabinet_id=cabinet.id,
                location_id=cabinet.location_id,
                position_u=position_u,
                height_u=height_u,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            db.session.add(device)
            action = 'create'

        db.session.commit()
        log_audit('update' if action == 'assign' else 'create', 'device', device.id,
                  f"机柜交互视图分配设备: {device.name}",
                  details={'cabinet_id': cabinet_id, 'position_u': position_u, 'height_u': height_u})

        return jsonify({
            'success': True,
            'message': f'设备 "{device.name}" 已分配到 {cabinet.name} U{position_u}',
            'device_id': device.id,
            'action': action,
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'分配失败: {str(e)}'}), 500


@cabinet_bp.route('/api/devices/<int:device_id>', methods=['PUT'])
@login_required
@permission_required('cabinet:edit')
def rack_update_device(device_id):
    """API: 更新设备信息（含可选的U位调整）"""
    try:
        device = Device.query.get_or_404(device_id)
        data = request.get_json(silent=True) or {}

        errors = _validate_device_fields(data, exclude_id=device.id)
        if errors:
            return jsonify({'success': False, 'message': '；'.join(errors)}), 400

        position_u = data.get('position_u', device.position_u)
        height_u = int(data.get('height_u', device.height_u or 1) or 1)
        try:
            position_u = int(position_u) if position_u not in (None, '') else None
        except (TypeError, ValueError):
            position_u = None

        if 'position_u' in data or 'height_u' in data:
            cabinet = device.cabinet
            if cabinet and position_u:
                u_errors = _validate_u_overlap(cabinet, position_u, height_u, exclude_id=device.id)
                if u_errors:
                    return jsonify({'success': False, 'message': '；'.join(u_errors)}), 400

        device.name = (data.get('name') or '').strip()
        device.device_type = (data.get('device_type') or '').strip() or device.device_type
        device.brand = (data.get('brand') or '').strip() or None
        device.manufacturer = (data.get('manufacturer') or '').strip() or None
        device.model = (data.get('model') or '').strip() or None
        device.serial_number = (data.get('serial_number') or '').strip() or None
        device.asset_number = (data.get('asset_number') or '').strip() or None
        device.management_ip = (data.get('management_ip') or '').strip()
        device.ip_address = (data.get('ip_address') or '').strip() or None
        device.mac_address = (data.get('mac_address') or '').strip() or None
        device.status = (data.get('status') or 'unknown').strip()
        device.owner = (data.get('owner') or '').strip() or None
        device.department = (data.get('department') or '').strip() or None
        device.description = (data.get('description') or '').strip() or None
        if 'position_u' in data or 'height_u' in data:
            device.position_u = position_u
            device.height_u = height_u
        device.updated_at = datetime.utcnow()

        db.session.commit()
        log_audit('update', 'device', device.id, f"更新设备信息: {device.name}")
        return jsonify({'success': True, 'message': f'设备 "{device.name}" 信息已更新', 'device_id': device.id})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'更新失败: {str(e)}'}), 500



# 1. 获取可用设备（未分配到任何机柜）
@cabinet_bp.route('/api/devices/available', methods=['GET'])
def api_available_devices():
    cabinet_id = request.args.get('cabinet_id')
    # 查询所有 cabinet_id 为 NULL 的设备（即未分配的设备）
    devices = Device.query.filter(Device.cabinet_id.is_(None)).all()
    device_list = [{
        'id': d.id,
        'name': d.name,
        'management_ip': d.management_ip or ''
    } for d in devices]
    return jsonify({'success': True, 'devices': device_list})

# 2. 获取机柜 U 位详情
@cabinet_bp.route('/api/cabinets/<int:cabinet_id>/rack-detail', methods=['GET'])
def api_cabinet_rack_detail(cabinet_id):
    cabinet = Cabinet.query.get(cabinet_id)
    if not cabinet:
        return jsonify({'success': False, 'message': '机柜不存在'}), 404
    
    total_u = cabinet.height_u or 42
    # 获取该机柜下的所有设备
    devices = Device.query.filter_by(cabinet_id=cabinet_id).all()
    
    # 构建占用映射：U位位置 -> 设备信息
    occupied = {}
    for dev in devices:
        start = dev.position_u
        end = start + (dev.height_u or 1)
        for u in range(start, end):
            occupied[u] = {
                'device_id': dev.id,
                'device_name': dev.name,
                'device_type': dev.device_type,
                'height': dev.height_u or 1
            }
    
    u_slots = []
    for u in range(1, total_u + 1):
        if u in occupied:
            u_slots.append({
                'position': u,
                'status': 'occupied',
                'device': occupied[u]
            })
        else:
            u_slots.append({
                'position': u,
                'status': 'available',
                'device': None
            })
    
    return jsonify({'success': True, 'u_slots': u_slots})

# 3. 分配设备到机柜（更新 Device 表）
@cabinet_bp.route('/api/cabinets/<int:cabinet_id>/assign-device', methods=['POST'])
def api_assign_device(cabinet_id):
    data = request.get_json()
    device_id = data.get('device_id')
    position_u = data.get('position_u')
    height_u = data.get('height_u', 1)
    
    if not device_id or not position_u:
        return jsonify({'success': False, 'message': '缺少必要参数'}), 400
    
    cabinet = Cabinet.query.get(cabinet_id)
    if not cabinet:
        return jsonify({'success': False, 'message': '机柜不存在'}), 404
    
    device = Device.query.get(device_id)
    if not device:
        return jsonify({'success': False, 'message': '设备不存在'}), 404
    
    # 检查设备是否已经分配到其他机柜
    if device.cabinet_id is not None and device.cabinet_id != cabinet_id:
        return jsonify({'success': False, 'message': f'设备 {device.name} 已分配到其他机柜'}), 400
    
    total_u = cabinet.height_u or 42
    end_u = position_u + height_u - 1
    if end_u > total_u:
        return jsonify({'success': False, 'message': f'设备超出机柜最大 U 位（{total_u}）'}), 400
    
    # 检查 U 位冲突：查找同一机柜中，U位区间重叠的其他设备
    conflicting = Device.query.filter(
        Device.cabinet_id == cabinet_id,
        Device.id != device_id,  # 排除自身（如果是重新分配）
        Device.position_u < position_u + height_u,
        Device.position_u + (Device.height_u or 1) > position_u
    ).first()
    if conflicting:
        return jsonify({'success': False, 'message': f'U位区间 {position_u}~{end_u} 与设备 {conflicting.name} 冲突'}), 400
    
    # 执行分配（更新设备）
    device.cabinet_id = cabinet_id
    device.position_u = position_u
    device.height_u = height_u
    db.session.commit()
    log_audit('update', 'device', device_id, f"分配设备到机柜: {device.name}", details={'cabinet_id': cabinet_id, 'position_u': position_u, 'height_u': height_u})

    return jsonify({'success': True, 'message': f'设备 {device.name} 已成功分配到 {cabinet.name} 的 U{position_u}-U{end_u}'})

# blueprints/cabinet.py 新增

@cabinet_bp.route('/api/visual/create', methods=['POST'])
@login_required
@permission_required('cabinet:edit')
def api_cabinet_create_from_visual():
    """可视化页面快速创建机柜的API"""
    try:
        data = request.get_json()
        
        # 从JSON中提取数据
        name = data.get('name', '').strip()
        location_id = data.get('location_id')
        pos_x = data.get('pos_x')
        pos_y = data.get('pos_y')
        height_u = data.get('height_u', 42)  # 默认42U
        
        # --- 基本验证 (复用你 cabinet_add 中的逻辑) ---
        if not name:
            return jsonify({'success': False, 'message': '机柜名称不能为空'}), 400
        if not location_id:
            return jsonify({'success': False, 'message': '请选择所属位置'}), 400
            
        # 检查同一位置下是否有重名机柜
        existing = Cabinet.query.filter_by(location_id=location_id, name=name).first()
        if existing:
            return jsonify({'success': False, 'message': f'位置下已存在名为 "{name}" 的机柜'}), 400
            
        # --- 创建机柜 (复用模型) ---
        new_cabinet = Cabinet(
            name=name,
            location_id=location_id,
            pos_x=pos_x,
            pos_y=pos_y,
            height_u=height_u,
            # 其他字段可设默认值或稍后编辑
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        
        db.session.add(new_cabinet)
        db.session.commit()
        log_audit('create', 'cabinet', new_cabinet.id, f"可视化创建机柜: {name}", details={'location_id': location_id, 'pos_x': pos_x, 'pos_y': pos_y})

        return jsonify({
            'success': True,
            'message': '机柜创建成功',
            'cabinet': {
                'id': new_cabinet.id,
                'name': new_cabinet.name,
                'pos_x': new_cabinet.pos_x,
                'pos_y': new_cabinet.pos_y
            }
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'创建失败: {str(e)}'}), 500

# ============================================================
# 可视化API - 获取数据
# ============================================================
@cabinet_bp.route('/api/visual/data')
@login_required
@permission_required('cabinet:view')
def api_visual_data():
    """获取机房可视化所需的所有数据"""
    try:
        location_id = request.args.get('location_id', type=int)
        
        query = Cabinet.query
        if location_id:
            query = query.filter_by(location_id=location_id)
        
        cabinets = query.all()
        
        result_cabinets = []
        result_devices = {}
        
        for cab in cabinets:
            # 获取设备
            devs = Device.query.filter_by(cabinet_id=cab.id).all()
            result_devices[cab.id] = [{
                'id': d.id,
                'name': d.name,
                'device_type': d.device_type,
                'status': d.status,
                'position_u': d.position_u,
                'height_u': d.height_u,
                'model': d.model,
                'ip_address': d.ip_address
            } for d in devs]
            
            # 计算使用率
            total_u = cab.height_u or 42
            used_u = sum(d.height_u for d in devs if d.position_u)
            usage = round((used_u / total_u * 100), 1) if total_u > 0 else 0
            
            result_cabinets.append({
                'id': cab.id,
                'name': cab.name,
                'location_id': cab.location_id,
                'location_name': cab.location.name if cab.location else None,
                'pos_x': cab.pos_x or 10,
                'pos_y': cab.pos_y or 10,
                'height_u': cab.height_u or 42,
                'usage_percent': usage,
                'color': getattr(cab, 'color', '#007bff')
            })
        
        return jsonify({
            'success': True,
            'cabinets': result_cabinets,
            'devices': result_devices
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


# ============================================================
# 可视化API - 创建机柜
# ============================================================
@cabinet_bp.route('/api/visual/create', methods=['POST'])
@login_required
def api_visual_create():
    """从可视化页面快速创建机柜"""
    try:
        data = request.get_json()
        
        name = data.get('name', '').strip()
        location_id = data.get('location_id')
        pos_x = data.get('pos_x')
        pos_y = data.get('pos_y')
        height_u = data.get('height_u', 42)
        color = data.get('color', '#007bff')
        
        if not name:
            return jsonify({'success': False, 'message': '机柜名称不能为空'}), 400
        if not location_id:
            return jsonify({'success': False, 'message': '请选择所属位置'}), 400
            
        # 检查重名
        existing = Cabinet.query.filter_by(
            location_id=location_id, 
            name=name
        ).first()
        if existing:
            return jsonify({
                'success': False, 
                'message': f'该机房下已存在名为 "{name}" 的机柜'
            }), 400
        
        new_cabinet = Cabinet(
            name=name,
            location_id=location_id,
            pos_x=pos_x,
            pos_y=pos_y,
            height_u=height_u,
            color=color,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        
        db.session.add(new_cabinet)
        db.session.commit()
        log_audit('create', 'cabinet', new_cabinet.id, f"可视化创建机柜: {name}", details={'location_id': location_id, 'pos_x': pos_x, 'pos_y': pos_y})

        return jsonify({
            'success': True,
            'message': '机柜创建成功',
            'cabinet': {
                'id': new_cabinet.id,
                'name': new_cabinet.name,
                'pos_x': new_cabinet.pos_x,
                'pos_y': new_cabinet.pos_y
            }
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'创建失败: {str(e)}'}), 500


# ============================================================
# 可视化API - 更新机柜位置
# ============================================================
@cabinet_bp.route('/api/visual/<int:cabinet_id>/position', methods=['PUT'])
@login_required
@permission_required('cabinet:edit')
def api_visual_update_position(cabinet_id):
    """更新机柜在可视化地图上的位置"""
    try:
        data = request.get_json()
        pos_x = data.get('pos_x')
        pos_y = data.get('pos_y')
        
        if pos_x is None or pos_y is None:
            return jsonify({'success': False, 'message': '缺少坐标参数'}), 400
            
        cabinet = Cabinet.query.get_or_404(cabinet_id)
        cabinet.pos_x = pos_x
        cabinet.pos_y = pos_y
        cabinet.updated_at = datetime.utcnow()

        db.session.commit()
        log_audit('update', 'cabinet', cabinet_id, f"更新机柜位置: {cabinet.name}", details={'pos_x': pos_x, 'pos_y': pos_y})

        return jsonify({
            'success': True,
            'message': '位置更新成功'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

#导出到Excel


# cabinet.py 添加导出功能
from flask import send_file
import io
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter

@cabinet_bp.route('/api/export/rack-view')
def export_rack_view_excel():
    """导出机柜视图到Excel"""
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
        from openpyxl.utils import get_column_letter
        import io
        from datetime import datetime
        
        # 获取筛选参数
        location_id = request.args.get('location_id', type=int)
        search = request.args.get('search', '')
        
        # 获取机柜数据
        query = Cabinet.query
        if location_id:
            query = query.filter_by(location_id=location_id)
        if search:
            query = query.filter(Cabinet.name.contains(search))
        cabinets = query.all()
        
        if not cabinets:
            return jsonify({'success': False, 'message': '没有可导出的机柜数据'}), 404
        
        wb = Workbook()
        
        # 创建样式
        header_font = Font(bold=True, color='FFFFFF')
        header_fill = PatternFill(start_color='007BFF', end_color='007BFF', fill_type='solid')
        header_alignment = Alignment(horizontal='center', vertical='center')
        thin_border = Border(
            left=Side(style='thin'),
            right=Side(style='thin'),
            top=Side(style='thin'),
            bottom=Side(style='thin')
        )
        
        # ============ 辅助函数 ============
        def get_cabinet_total_u(cabinet):
            """获取机柜总U位"""
            return cabinet.height_u or 42  # 默认42U
        
        def get_cabinet_used_u(cabinet):
            """计算已使用的U位"""
            devices = Device.query.filter_by(cabinet_id=cabinet.id).all()
            used_u = set()
            for device in devices:
                if hasattr(device, 'position_u') and hasattr(device, 'height_u'):
                    for u in range(device.position_u, device.position_u + device.height_u):
                        used_u.add(u)
            return len(used_u)
        
        def get_device_count(cabinet):
            """获取设备数量"""
            return Device.query.filter_by(cabinet_id=cabinet.id).count()
        
        # ============ 1. 机柜概览工作表 ============
        ws_summary = wb.active
        ws_summary.title = '机柜概览'
        
        # 概览表头
        headers = ['机柜名称', '位置', '型号', '厂商', '总U位', '已用U位', '可用U位', '使用率', '设备数量', '电源容量(kW)', '承重(kg)']
        for col, header in enumerate(headers, 1):
            cell = ws_summary.cell(row=1, column=col, value=header)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_alignment
            cell.border = thin_border
        
        # 概览数据
        for row, cabinet in enumerate(cabinets, 2):
            total_u = get_cabinet_total_u(cabinet)
            used_u = get_cabinet_used_u(cabinet)
            available_u = total_u - used_u
            usage = round((used_u / total_u) * 100, 1) if total_u > 0 else 0
            device_count = get_device_count(cabinet)
            location_name = cabinet.location.name if hasattr(cabinet, 'location') and cabinet.location else ''
            
            ws_summary.cell(row=row, column=1, value=cabinet.name).border = thin_border
            ws_summary.cell(row=row, column=2, value=location_name).border = thin_border
            ws_summary.cell(row=row, column=3, value=cabinet.model or '').border = thin_border
            ws_summary.cell(row=row, column=4, value=cabinet.manufacturer or '').border = thin_border
            ws_summary.cell(row=row, column=5, value=total_u).border = thin_border
            ws_summary.cell(row=row, column=6, value=used_u).border = thin_border
            ws_summary.cell(row=row, column=7, value=available_u).border = thin_border
            ws_summary.cell(row=row, column=8, value=f'{usage}%').border = thin_border
            ws_summary.cell(row=row, column=9, value=device_count).border = thin_border
            ws_summary.cell(row=row, column=10, value=cabinet.power_capacity or '').border = thin_border
            ws_summary.cell(row=row, column=11, value=cabinet.weight_capacity or '').border = thin_border
        
        # 调整列宽
        for col in range(1, 12):
            ws_summary.column_dimensions[get_column_letter(col)].width = 15
        
        # ============ 2. U位详情工作表 ============
        ws_detail = wb.create_sheet('U位详情')
        
        detail_headers = ['机柜名称', '位置', 'U位编号', '设备名称', '设备类型', '设备状态', '设备IP', '设备高度(U)', '备注']
        for col, header in enumerate(detail_headers, 1):
            cell = ws_detail.cell(row=1, column=col, value=header)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_alignment
            cell.border = thin_border
        
        row = 2
        for cabinet in cabinets:
            total_u = get_cabinet_total_u(cabinet)
            devices = Device.query.filter_by(cabinet_id=cabinet.id).all()
            
            # 创建U位映射
            u_slots = {}
            for device in devices:
                if hasattr(device, 'position_u') and hasattr(device, 'height_u'):
                    for u in range(device.position_u, device.position_u + device.height_u):
                        u_slots[u] = device
            
            location_name = cabinet.location.name if hasattr(cabinet, 'location') and cabinet.location else ''
            
            for u in range(1, total_u + 1):
                device = u_slots.get(u)
                ws_detail.cell(row=row, column=1, value=cabinet.name).border = thin_border
                ws_detail.cell(row=row, column=2, value=location_name).border = thin_border
                ws_detail.cell(row=row, column=3, value=u).border = thin_border
                if device:
                    ws_detail.cell(row=row, column=4, value=device.name).border = thin_border
                    ws_detail.cell(row=row, column=5, value=getattr(device, 'device_type', '')).border = thin_border
                    ws_detail.cell(row=row, column=6, value=getattr(device, 'status', '')).border = thin_border
                    ws_detail.cell(row=row, column=7, value=getattr(device, 'management_ip', '') or '').border = thin_border
                    ws_detail.cell(row=row, column=8, value=getattr(device, 'height_u', 1)).border = thin_border
                    ws_detail.cell(row=row, column=9, value=getattr(device, 'remarks', '') or '').border = thin_border
                else:
                    ws_detail.cell(row=row, column=4, value='空闲').border = thin_border
                row += 1
        
        for col in range(1, 10):
            ws_detail.column_dimensions[get_column_letter(col)].width = 16
        
        # ============ 3. 设备清单工作表 ============
        ws_devices = wb.create_sheet('设备清单')
        device_headers = ['设备名称', '机柜', '位置', '起始U位', '高度(U)', '结束U位', '设备类型', '状态', '管理IP', '品牌', '型号', '备注']
        for col, header in enumerate(device_headers, 1):
            cell = ws_devices.cell(row=1, column=col, value=header)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_alignment
            cell.border = thin_border
        
        row = 2
        for cabinet in cabinets:
            devices = Device.query.filter_by(cabinet_id=cabinet.id).all()
            location_name = cabinet.location.name if hasattr(cabinet, 'location') and cabinet.location else ''
            for device in devices:
                ws_devices.cell(row=row, column=1, value=device.name).border = thin_border
                ws_devices.cell(row=row, column=2, value=cabinet.name).border = thin_border
                ws_devices.cell(row=row, column=3, value=location_name).border = thin_border
                ws_devices.cell(row=row, column=4, value=getattr(device, 'position_u', 0)).border = thin_border
                ws_devices.cell(row=row, column=5, value=getattr(device, 'height_u', 1)).border = thin_border
                end_u = getattr(device, 'position_u', 0) + getattr(device, 'height_u', 1) - 1
                ws_devices.cell(row=row, column=6, value=end_u if end_u > 0 else '').border = thin_border
                ws_devices.cell(row=row, column=7, value=getattr(device, 'device_type', '')).border = thin_border
                ws_devices.cell(row=row, column=8, value=getattr(device, 'status', '')).border = thin_border
                ws_devices.cell(row=row, column=9, value=getattr(device, 'management_ip', '') or '').border = thin_border
                ws_devices.cell(row=row, column=10, value=getattr(device, 'vendor', '') or '').border = thin_border
                ws_devices.cell(row=row, column=11, value=getattr(device, 'model', '') or '').border = thin_border
                ws_devices.cell(row=row, column=12, value=getattr(device, 'remarks', '') or '').border = thin_border
                row += 1
        
        for col in range(1, 13):
            ws_devices.column_dimensions[get_column_letter(col)].width = 16
        
        # ============ 4. 机柜详情工作表 ============
        ws_cabinet_detail = wb.create_sheet('机柜详情')
        cab_headers = ['机柜名称', '位置', '型号', '厂商', '总U位', '宽度(mm)', '深度(mm)', '承重(kg)', 
                      '电源容量(kW)', '电源配置', '网络接入', '制冷系统', '标签', '描述', '备注']
        for col, header in enumerate(cab_headers, 1):
            cell = ws_cabinet_detail.cell(row=1, column=col, value=header)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_alignment
            cell.border = thin_border
        
        row = 2
        for cabinet in cabinets:
            location_name = cabinet.location.name if hasattr(cabinet, 'location') and cabinet.location else ''
            ws_cabinet_detail.cell(row=row, column=1, value=cabinet.name).border = thin_border
            ws_cabinet_detail.cell(row=row, column=2, value=location_name).border = thin_border
            ws_cabinet_detail.cell(row=row, column=3, value=cabinet.model or '').border = thin_border
            ws_cabinet_detail.cell(row=row, column=4, value=cabinet.manufacturer or '').border = thin_border
            ws_cabinet_detail.cell(row=row, column=5, value=cabinet.height_u or 42).border = thin_border
            ws_cabinet_detail.cell(row=row, column=6, value=cabinet.width or '').border = thin_border
            ws_cabinet_detail.cell(row=row, column=7, value=cabinet.depth or '').border = thin_border
            ws_cabinet_detail.cell(row=row, column=8, value=cabinet.weight_capacity or '').border = thin_border
            ws_cabinet_detail.cell(row=row, column=9, value=cabinet.power_capacity or '').border = thin_border
            ws_cabinet_detail.cell(row=row, column=10, value=cabinet.power_supply or '').border = thin_border
            ws_cabinet_detail.cell(row=row, column=11, value=cabinet.network_access or '').border = thin_border
            ws_cabinet_detail.cell(row=row, column=12, value=cabinet.cooling_system or '').border = thin_border
            ws_cabinet_detail.cell(row=row, column=13, value=cabinet.tags or '').border = thin_border
            ws_cabinet_detail.cell(row=row, column=14, value=cabinet.description or '').border = thin_border
            ws_cabinet_detail.cell(row=row, column=15, value=cabinet.notes or '').border = thin_border
            row += 1
        
        for col in range(1, 16):
            ws_cabinet_detail.column_dimensions[get_column_letter(col)].width = 16
        
        # ============ 5. 位置统计工作表 ============
        try:
            from models import Location
            locations = Location.query.all()
            if locations:
                ws_location = wb.create_sheet('位置统计')
                loc_headers = ['位置', '机柜数', '总U位', '已用U位', '可用U位', '使用率', '设备数']
                for col, header in enumerate(loc_headers, 1):
                    cell = ws_location.cell(row=1, column=col, value=header)
                    cell.font = header_font
                    cell.fill = header_fill
                    cell.alignment = header_alignment
                    cell.border = thin_border
                
                row = 2
                for loc in locations:
                    loc_cabinets = Cabinet.query.filter_by(location_id=loc.id).all()
                    if loc_cabinets:
                        total_u = sum(get_cabinet_total_u(c) for c in loc_cabinets)
                        used_u = sum(get_cabinet_used_u(c) for c in loc_cabinets)
                        available_u = total_u - used_u
                        device_count = sum(get_device_count(c) for c in loc_cabinets)
                        usage = round((used_u / total_u) * 100, 1) if total_u > 0 else 0
                        ws_location.cell(row=row, column=1, value=loc.name).border = thin_border
                        ws_location.cell(row=row, column=2, value=len(loc_cabinets)).border = thin_border
                        ws_location.cell(row=row, column=3, value=total_u).border = thin_border
                        ws_location.cell(row=row, column=4, value=used_u).border = thin_border
                        ws_location.cell(row=row, column=5, value=available_u).border = thin_border
                        ws_location.cell(row=row, column=6, value=f'{usage}%').border = thin_border
                        ws_location.cell(row=row, column=7, value=device_count).border = thin_border
                        row += 1
                
                for col in range(1, 8):
                    ws_location.column_dimensions[get_column_letter(col)].width = 15
        except Exception as e:
            print(f"位置统计表生成失败: {e}")
        
        # 保存到内存
        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        
        # 生成文件名
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'机柜视图导出_{timestamp}.xlsx'
        
        return send_file(
            output,
            as_attachment=True,
            download_name=filename,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'导出失败: {str(e)}'}), 500