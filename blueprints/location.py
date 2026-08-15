# blueprints/location.py - 完整的位置管理蓝图

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_file,current_app
from flask_login import login_required, current_user
from models.models import  Location,Cabinet,Device  
from extensions import db 
from forms import LocationForm, LocationImportForm
from werkzeug.utils import secure_filename  # 添加这个导入
import pandas as pd
import os
import io
import openpyxl
from io import BytesIO
from datetime import datetime, timedelta
from utils.audit import log_audit
from utils.permission import permission_required

location_bp = Blueprint('location', __name__, url_prefix='/location')

@location_bp.route('/')
@login_required
@permission_required('location:view')
def location_list():
    #位置列表
    search = request.args.get('search', '')
    page = request.args.get('page', 1, type=int)
    per_page = 20
    
    # 使用 joinedload 预加载 cabinets 和 devices
    query = Location.query.options(
        db.joinedload(Location.cabinets).joinedload(Cabinet.devices)
    )
    
    if search:
        query = query.filter(or_(
            Location.name.ilike(f'%{search}%'),
            Location.description.ilike(f'%{search}%'),
            Location.address.ilike(f'%{search}%')
        ))
    
    locations = query.order_by(Location.name).paginate(page=page, per_page=per_page, error_out=False)
    
    # 统计每个位置的机柜和设备数量
    for location in locations.items:
        location.cabinet_count_value = len(location.cabinets)
        location.total_devices = sum(len(cabinet.devices) for cabinet in location.cabinets)
        location.used_u_count = sum(cabinet.get_used_u_count() for cabinet in location.cabinets)
        
        # 为每个机柜预计算U位占用情况和使用信息
        for cabinet in location.cabinets:
            # 计算 u_slots
            cabinet.u_slots = {}
            for device in cabinet.devices:
                if device.position_u:
                    for u in range(device.position_u, device.position_u + device.height_u):
                        if u <= cabinet.height_u:
                            cabinet.u_slots[u] = device
            
            # 计算 usage_info
            used = cabinet.get_used_u_count()
            total = cabinet.height_u
            cabinet.usage_info = {
                'used': used,
                'total': total,
                'remaining': total - used,
                'usage_percent': round((used / total) * 100, 1) if total > 0 else 0
            }
    
    return render_template('/location/location_list.html', 
                         locations=locations,
                         search=search)


@location_bp.route('/locations/add', methods=['GET', 'POST'])
@login_required
@permission_required('location:edit')
def location_add():
    """添加位置"""



    if request.method == 'POST':
        try:
            location = Location(
                name=request.form['name'],
                description=request.form.get('description', ''),
                location_type=request.form.get('location_type', ''),
                address=request.form.get('address', ''),
                floor=request.form.get('floor', ''),
                room_number=request.form.get('room_number', ''),
                area=float(request.form.get('area', 0)) if request.form.get('area') else 0,
                capacity=int(request.form.get('capacity', 0)) if request.form.get('capacity') else 0,
                contact_person=request.form.get('contact_person', ''),
                contact_phone=request.form.get('contact_phone', ''),
                contact_email=request.form.get('contact_email', ''),
                contact_department=request.form.get('contact_department', ''),
                power_supply=request.form.get('power_supply', ''),
                cooling_system=request.form.get('cooling_system', ''),
                temperature=request.form.get('temperature', ''),
                humidity=request.form.get('humidity', ''),
                access_control=request.form.get('access_control', ''),
                tags=request.form.get('tags', ''),
                notes=request.form.get('notes', '')
            )
            
            db.session.add(location)
            db.session.commit()
            log_audit('create', 'location', location.id, f"添加位置: {location.name}", user_id=current_user.id if current_user.is_authenticated else None)
            flash('位置添加成功！', 'success')
            return redirect(url_for('location.location_list'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'添加失败: {str(e)}', 'danger')
    
    return render_template('/location/location_add.html')

@location_bp.route('/locations/<int:id>')
@login_required
@permission_required('location:view')
def location_detail(id):
    """位置详情"""
    location = Location.query.get_or_404(id)
    
    # 获取该位置下的所有机柜
    cabinets = Cabinet.query.filter_by(location_id=id).order_by(Cabinet.name).all()
    
    # 统计信息
    stats = {
        'cabinet_count': len(cabinets),
        #'total_devices': sum(cabinet.device_count() for cabinet in cabinets),
        'total_devices': sum(cabinet.device_count for cabinet in cabinets),
        'total_u_used': sum(cabinet.get_used_u_count() for cabinet in cabinets),
        'total_u_capacity': sum(cabinet.height_u for cabinet in cabinets),
    }
    
    return render_template('/location/location_detail.html',
                         location=location,
                         cabinets=cabinets,
                         stats=stats)



@location_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@permission_required('location:edit')
def location_edit(id):
    """编辑位置"""
    location = Location.query.get_or_404(id)
    form = LocationForm(obj=location)
    
    if form.validate_on_submit():
        # 检查位置名称是否与其他位置重复
        existing = Location.query.filter(
            Location.name == form.name.data,
            Location.id != id
        ).first()
        
        if existing:
            flash('位置名称已存在！', 'danger')
            return render_template('location/location_edit.html', form=form, location=location)
        
        form.populate_obj(location)
        location.updated_at = datetime.utcnow()
        
        try:
            db.session.commit()
            log_audit('update', 'location', id, f"编辑位置: {location.name}", user_id=current_user.id if current_user.is_authenticated else None)
            flash('位置更新成功！', 'success')
            return redirect(url_for('location.location_list'))
        except Exception as e:
            db.session.rollback()
            flash(f'更新失败: {str(e)}', 'danger')
    
    return render_template('location/location_edit.html', form=form, location=location)

@location_bp.route('/<int:id>/delete', methods=['POST'])
@login_required
@permission_required('location:edit')
def location_delete(id):
    """删除位置"""
    location = Location.query.get_or_404(id)
    
    # 检查是否有关联设备或机柜
    # if location.devices:
    #     flash('该位置下有设备，无法删除！', 'danger')
    #     return redirect(url_for('location.location_list'))
    
    if location.cabinets:
        flash('该位置下有机柜，无法删除！', 'danger')
        return redirect(url_for('location.location_list'))
    
    try:
        db.session.delete(location)
        db.session.commit()
        log_audit('delete', 'location', id, f"删除位置: {location.name}", user_id=current_user.id if current_user.is_authenticated else None)
        flash('位置删除成功！', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'删除失败: {str(e)}', 'danger')
    
    return redirect(url_for('location.location_list'))

@location_bp.route('/import', methods=['GET', 'POST'])
@login_required
@permission_required('location:edit')
def location_import():
    form = LocationImportForm()
    
    if form.validate_on_submit():
        try:
            file = form.file.data
            filename = secure_filename(file.filename)
            
            # 根据文件类型读取数据
            if filename.endswith(('.xlsx', '.xls')):
                df = pd.read_excel(file)
            elif filename.endswith('.csv'):
                df = pd.read_csv(file, encoding='utf-8')
            else:
                flash('不支持的文件格式，请上传 Excel 或 CSV 文件', 'error')
                return redirect(url_for('location.location_import'))
            
            # 检查数据行数限制
            max_records = 1000
            if len(df) > max_records:
                flash(f'一次最多导入 {max_records} 条记录，当前文件包含 {len(df)} 条', 'error')
                return redirect(url_for('location.location_import'))
            
            success_count = 0
            error_count = 0
            errors = []
            
            # 确保列名正确（处理中英文列名）
            column_mapping = {
                '位置名称': 'name',
                '名称': 'name',
                'name': 'name',
                '描述': 'description',
                'description': 'description',
                '地址': 'address',
                'address': 'address',
                '楼层': 'floor',
                'floor': 'floor',
                '房间号': 'room_number',
                '房间': 'room_number',
                'room_number': 'room_number',
                '面积': 'area',
                'area': 'area',
                '容量': 'capacity',
                'capacity': 'capacity',
                '联系人': 'contact_person',
                'contact_person': 'contact_person',
                '联系电话': 'contact_phone',
                '电话': 'contact_phone',
                'contact_phone': 'contact_phone',
                '邮箱': 'contact_email',
                'contact_email': 'contact_email',
                '部门': 'contact_department',
                'contact_department': 'contact_department',
                '位置类型': 'location_type',
                'location_type': 'location_type',
                '供电': 'power_supply',
                'power_supply': 'power_supply',
                '制冷': 'cooling_system',
                'cooling_system': 'cooling_system',
                '温度': 'temperature',
                'temperature': 'temperature',
                '湿度': 'humidity',
                'humidity': 'humidity',
                '门禁': 'access_control',
                'access_control': 'access_control',
                '标签': 'tags',
                'tags': 'tags',
                '备注': 'notes',
                'notes': 'notes'
            }
            
            # 重命名列，使用映射
            df.rename(columns={col: column_mapping.get(col, col) for col in df.columns}, inplace=True)
            
            # 检查必要字段
            required_fields = ['name']
            for field in required_fields:
                if field not in df.columns:
                    flash(f'缺少必要字段: {field}', 'error')
                    return redirect(url_for('location.location_import'))
            
            # 处理每一行数据
            for index, row in df.iterrows():
                try:
                    # 获取位置名称（必须字段）
                    location_name = str(row['name']).strip()
                    if not location_name:
                        errors.append(f"第{index+2}行：位置名称不能为空")
                        error_count += 1
                        continue
                    
                    # 检查位置是否已存在
                    existing_location = Location.query.filter_by(name=location_name).first()
                    
                    # 更新已存在的记录
                    if existing_location and form.update_existing.data:
                        # 只更新非空的值
                        for field in ['description', 'location_type', 'address', 'floor', 'room_number', 
                                     'area', 'capacity', 'contact_person', 'contact_phone', 'contact_email',
                                     'contact_department', 'power_supply', 'cooling_system', 'temperature',
                                     'humidity', 'access_control', 'tags', 'notes']:
                            if field in df.columns and pd.notna(row[field]):
                                setattr(existing_location, field, row[field])
                        
                        db.session.add(existing_location)
                        success_count += 1
                        continue
                    
                    # 跳过重复记录
                    if existing_location and form.skip_duplicates.data:
                        continue
                    
                    # 位置已存在但未选择更新或跳过
                    if existing_location:
                        errors.append(f"第{index+2}行：位置 '{location_name}' 已存在")
                        error_count += 1
                        continue
                    
                    # 创建新位置
                    location_data = {
                        'name': location_name
                    }
                    
                    # 添加其他字段（如果有）
                    for field in ['description', 'location_type', 'address', 'floor', 'room_number', 
                                 'area', 'capacity', 'contact_person', 'contact_phone', 'contact_email',
                                 'contact_department', 'power_supply', 'cooling_system', 'temperature',
                                 'humidity', 'access_control', 'tags', 'notes']:
                        if field in df.columns and pd.notna(row[field]):
                            location_data[field] = row[field]
                    
                    # 创建位置对象
                    location = Location(**location_data)
                    db.session.add(location)
                    success_count += 1
                    
                except Exception as e:
                    errors.append(f"第{index+2}行：{str(e)}")
                    error_count += 1
            
            # 提交到数据库
            db.session.commit()
            log_audit('execute', 'location', None, f"导入位置: {success_count}条成功, {error_count}条失败",
                      details={'success_count': success_count, 'error_count': error_count},
                      user_id=current_user.id if current_user.is_authenticated else None)

            # 显示结果
            flash(f'导入完成！成功导入 {success_count} 条记录，失败 {error_count} 条。', 'success')
            
            # 如果有错误，显示错误信息
            if errors:
                error_msg = '部分记录导入失败：<br>' + '<br>'.join(errors[:10])  # 只显示前10个错误
                if len(errors) > 10:
                    error_msg += f'<br>... 还有 {len(errors)-10} 个错误'
                flash(error_msg, 'warning')
            
            return redirect(url_for('location.location_list'))
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f'导入失败: {str(e)}')
            flash(f'导入失败：{str(e)}', 'error')
    
    # 处理表单验证错误
    if form.errors:
        for field, errors in form.errors.items():
            for error in errors:
                flash(f'{field}: {error}', 'error')
    
    return render_template('location/location_import.html', form=form)
"""
@location_bp.route('/download-template/<type>')
@login_required
@permission_required('location:view')
def download_template(type):
    #下载导入模板
    try:
        # 创建示例数据
        data = [
            {
                '位置名称': '上海数据中心',
                '地址': '上海市浦东新区张江高科技园区',
                '联系人': '张三',
                '联系电话': '13800138000',
                '描述': '主要数据中心',
                '楼层': '3楼',
                '房间号': '301',
                '面积': 500.0,
                '容量': 50
            },
            {
                '位置名称': '北京备份中心',
                '地址': '北京市海淀区中关村',
                '联系人': '李四',
                '联系电话': '13900139000',
                '描述': '备份数据中心',
                '楼层': '2楼',
                '房间号': '208',
                '面积': 300.0,
                '容量': 30
            }
        ]
        
        df = pd.DataFrame(data)
        output = BytesIO()
        
        if type == 'excel':
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='位置模板')
            output.seek(0)
            mimetype = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            filename = '位置导入模板.xlsx'
        elif type == 'csv':
            df.to_csv(output, index=False, encoding='utf-8-sig')
            output.seek(0)
            mimetype = 'text/csv'
            filename = '位置导入模板.csv'
        else:
            flash('不支持的模板类型', 'error')
            return redirect(url_for('location.location_import'))
        
        return send_file(
            output,
            mimetype=mimetype,
            as_attachment=True,
            download_name=filename
        )
        
    except Exception as e:
        flash(f'生成模板失败: {str(e)}', 'error')
        return redirect(url_for('location.location_import'))

"""
@location_bp.route('/export', methods=['GET'])
@login_required
@permission_required('location:view')
def location_export():
    """导出位置数据"""
    try:
        # 获取所有位置数据
        locations = Location.query.all()
        
        if not locations:
            flash('没有位置数据可以导出', 'warning')
            return redirect(url_for('location.location_list'))
        
        # 准备数据
        data = []
        for location in locations:
            data.append({
                '位置名称': location.name or '',
                '位置类型': location.location_type or '',
                '地址': location.address or '',
                '楼层': location.floor or '',
                '房间号': location.room_number or '',
                '面积': str(location.area) if location.area else '',
                '容量': str(location.capacity) if location.capacity else '',
                '联系人': location.contact_person or '',
                '联系电话': location.contact_phone or '',
                '邮箱': location.contact_email or '',
                '部门': location.contact_department or '',
                '描述': location.description or '',
                '供电系统': location.power_supply or '',
                '制冷系统': location.cooling_system or '',
                '温度要求': location.temperature or '',
                '湿度要求': location.humidity or '',
                '门禁系统': location.access_control or '',
                '标签': location.tags or '',
                '备注': location.notes or '',
                '创建时间': (location.created_at + timedelta(hours=8)).strftime('%Y-%m-%d %H:%M:%S') if location.created_at else '',
                '更新时间': (location.updated_at + timedelta(hours=8)).strftime('%Y-%m-%d %H:%M:%S') if location.updated_at else '',
                # 机柜数量（计算字段）
                '机柜数量': str(location.cabinet_count()) if hasattr(location, 'cabinet_count') else '0'
            })
        
        # 创建DataFrame
        df = pd.DataFrame(data)
        
        # 生成Excel文件
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='位置数据', index=False)
            
            # 设置列宽（可选）
            worksheet = writer.sheets['位置数据']
            for idx, col in enumerate(df.columns):
                column_length = max(df[col].astype(str).map(len).max(), len(col))
                worksheet.column_dimensions[openpyxl.utils.get_column_letter(idx + 1)].width = min(column_length + 2, 50)
        
        output.seek(0)
        
        # 生成文件名
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'位置数据_导出_{timestamp}.xlsx'
        
        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=filename
        )
        
    except Exception as e:
        current_app.logger.error(f'导出失败: {str(e)}')
        flash(f'导出失败：{str(e)}', 'error')
        return redirect(url_for('location.location_list'))

@location_bp.route('/download_template/<type>')
@login_required
@permission_required('location:view')
def download_template(type):
    """下载导入模板"""
    
    # 创建示例数据
    data = {
        '位置名称': ['上海数据中心', '北京数据中心'],
        '位置类型': ['数据中心', '数据中心'],
        '地址': ['上海市浦东新区', '北京市海淀区'],
        '楼层': ['3楼', '2楼'],
        '房间号': ['301', '201'],
        '面积': [500.0, 300.0],
        '容量': [50, 30],
        '联系人': ['张三', '李四'],
        '联系电话': ['13800138000', '13900139000'],
        '邮箱': ['zhangsan@example.com', 'lisi@example.com'],
        '部门': ['IT部', 'IT部'],
        '描述': ['主要数据中心', '备用数据中心'],
        '供电': ['双路UPS', '双路UPS'],
        '制冷': ['精密空调', '精密空调'],
        '温度': ['22-24°C', '22-24°C'],
        '湿度': ['40-60%', '40-60%'],
        '门禁': ['刷卡+密码', '刷卡+密码'],
        '标签': ['核心,生产', '备份,测试'],
        '备注': ['', '']
    }
    
    df = pd.DataFrame(data)
    
    if type == 'excel':
        # 创建Excel文件
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='位置数据', index=False)
        output.seek(0)
        
        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name='位置导入模板.xlsx'
        )
    
    elif type == 'csv':
        # 创建CSV文件
        output = io.StringIO()
        df.to_csv(output, index=False, encoding='utf-8-sig')
        output.seek(0)
        
        return send_file(
            io.BytesIO(output.getvalue().encode('utf-8-sig')),
            mimetype='text/csv',
            as_attachment=True,
            download_name='位置导入模板.csv'
        )
    
    flash('不支持的模板类型', 'error')
    return redirect(url_for('location.location_import'))

# blueprints/location.py - 添加可视化路由

# blueprints/location.py - 添加可视化路由

@location_bp.route('/viz')
@login_required
@permission_required('location:view')
def location_viz():
    """机房可视化页面"""
    try:
        # 获取所有位置（用于下拉筛选）
        locations = Location.query.order_by(Location.name).all()
        
        # 获取选中的位置ID（默认第一个）
        location_id = request.args.get('location_id', type=int)
        if not location_id and locations:
            location_id = locations[0].id
        
        # 获取当前选中位置下的机柜数据
        cabinets = []
        devices_by_cabinet = {}
        
        if location_id:
            cabinets = Cabinet.query.filter_by(location_id=location_id).all()
            for cab in cabinets:
                devices = Device.query.filter_by(cabinet_id=cab.id).all()
                devices_by_cabinet[cab.id] = [{
                    'id': d.id,
                    'name': d.name,
                    'device_type': d.device_type,
                    'status': d.status,
                    'position_u': d.position_u,
                    'height_u': d.height_u,
                    'model': d.model,
                    'ip_address': d.ip_address
                } for d in devices]
        
        return render_template(
            'cabinet/location_viz.html',
            locations=locations,
            selected_location_id=location_id,
            cabinets=cabinets,
            devices_by_cabinet=devices_by_cabinet
        )
        
    except Exception as e:
        current_app.logger.error(f"加载机房可视化失败: {str(e)}")
        flash(f'加载失败: {str(e)}', 'error')
        return redirect(url_for('location.location_list'))


# ==================== 3D机房可视化 ====================
# 原 Three.js 实现(location_viz_3d / cabinet/location_3d.html)已移除,
# 全系统统一采用 Babylon.js。此处重定向到 Babylon.js 机房可视化,
# 保留历史入口, 避免书签/外链失效。

@location_bp.route('/viz-3d')
@login_required
@permission_required('location:view')
def location_viz_3d():
    """旧 Three.js 3D 入口, 重定向到 Babylon.js 机房可视化。"""
    from flask import redirect
    return redirect(url_for('dc_view.dc_babylon') + ('?demo=1' if request.args.get('demo') else ''))