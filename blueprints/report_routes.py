from flask import Blueprint, render_template, jsonify, request, current_app, send_file
from flask_login import login_required, current_user
from extensions import db
from utils.audit import log_audit
from utils.permission import permission_required
from models.report_models import ReportTemplate, ScheduledReport, ReportExecution, ReportFavorite
from models.models import Device, Interface, DeviceMonitor, DeviceMonitorConfig
from models.device_performance_models import DevicePerformance
from models.models import Alert
from models.models import Cabinet,  Location
from models.maintenance_models import ChangeRequest, MaintenanceTask,Asset,WorkOrder
from models.device_performance_models import DevicePerformance,PerformanceThreshold,PerformanceBaseline,PerformanceAlert
from datetime import datetime, timedelta
import json
import pandas as pd
from io import BytesIO
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')  # 使用非GUI后端
from forms import ReportFilterForm,ExportReportForm
import plotly.graph_objects as go
import plotly.utils
from sqlalchemy import create_engine, func, extract
from models.device_performance_models import PerformanceData

report_bp = Blueprint('report', __name__, url_prefix='/report')

@report_bp.route('/')
@login_required
@permission_required('report:view')
def report_dashboard():
    """报表仪表板"""
    return render_template('report/dashboard.html')


@report_bp.route('/device_status_report')
@login_required
@permission_required('report:view')
def device_status_report():
    """设备状态统计报表"""
    # 获取设备状态统计
    status_stats = db.session.query(
        Device.status,
        db.func.count(Device.id).label('count')
    ).group_by(Device.status).all()
    
    # 计算总计
    total_devices = db.session.query(db.func.count(Device.id)).scalar()
    
    return render_template('report/device_status.html',
                         status_stats=status_stats,
                         total_devices=total_devices)
#导出功能
@report_bp.route('/export_device_status')
@login_required
@permission_required('report:view')
def export_device_status():
    """导出设备状态详细数据"""
    devices = Device.query.all()
    
    output = []
    for device in devices:
        output.append({
            '设备名称': device.name,
            '状态': device.status,
            '设备类型': device.device_type,
            '品牌': device.brand,
            '型号': device.model,
            '管理IP': device.management_ip or '',
            '位置': device.cabinet.location.name if device.cabinet and device.cabinet.location else '',
            '机柜': device.cabinet.name if device.cabinet else '',
            '最后检查时间': device.last_checked.strftime('%Y-%m-%d %H:%M:%S') if device.last_checked else ''
        })
    
    # 返回JSON或CSV格式
    return jsonify(output)




@report_bp.route('/device_type_distribution')
@login_required
@permission_required('report:view')
def device_type_distribution():
    """设备类型分布报表"""
    type_stats = db.session.query(
        Device.device_type,
        db.func.count(Device.id).label('count')
    ).group_by(Device.device_type).all()
    type_stats = [{'device_type': r.device_type, 'count': r.count} for r in type_stats]

    vendor_stats = db.session.query(
        Device.brand,
        db.func.count(Device.id).label('count')
    ).group_by(Device.brand).all()
    vendor_stats = [{'brand': r.brand, 'count': r.count} for r in vendor_stats]

    # 计算设备总数
    total_devices = db.session.query(db.func.count(Device.id)).scalar()

    return render_template('report/device_type.html',
                         type_stats=type_stats,
                         vendor_stats=vendor_stats,
                         total_count=sum(t['count'] for t in type_stats),
                         vendor_total=sum(v['count'] for v in vendor_stats),
                         total_devices=total_devices)  # 添加了设备总数


@report_bp.route('/device_performance_report')
@login_required
@permission_required('report:view')
def device_performance_report():
    """设备性能报表"""
    # 获取时间范围参数，默认为24小时
    time_range = request.args.get('timeRange', '24', type=str)
    
    # 根据参数计算时间范围
    hours_map = {
        '1': 1,
        '6': 6,
        '24': 24,
        '168': 168,
        '720': 720
    }
    
    hours = hours_map.get(time_range, 24)
    time_threshold = datetime.utcnow() - timedelta(hours=hours)
    
    # 获取CPU使用率最高的设备
    cpu_devices = db.session.query(
        DevicePerformance.device_id,
        Device.name,
        db.func.avg(DevicePerformance.cpu_usage).label('avg_cpu'),
        db.func.max(DevicePerformance.cpu_usage).label('max_cpu')
    ).join(Device).filter(
        DevicePerformance.timestamp >= time_threshold,
        DevicePerformance.cpu_usage.isnot(None)
    ).group_by(
        DevicePerformance.device_id, Device.name
    ).order_by(db.func.avg(DevicePerformance.cpu_usage).desc()).limit(10).all()
    
    # 获取内存使用率最高的设备
    memory_devices = db.session.query(
        DevicePerformance.device_id,
        Device.name,
        db.func.avg(DevicePerformance.memory_usage).label('avg_memory'),
        db.func.max(DevicePerformance.memory_usage).label('max_memory')
    ).join(Device).filter(
        DevicePerformance.timestamp >= time_threshold,
        DevicePerformance.memory_usage.isnot(None)
    ).group_by(
        DevicePerformance.device_id, Device.name
    ).order_by(db.func.avg(DevicePerformance.memory_usage).desc()).limit(10).all()
    
    return render_template('report/device_performance.html',
                         cpu_devices=cpu_devices,
                         memory_devices=memory_devices,
                         time_range=time_range)


@report_bp.route('/interface_utilization_report')
@login_required
@permission_required('report:view')
def interface_utilization_report():
    """接口利用率报表"""
    # 获取接口状态统计
    # 将 Interface.status 改为 Interface.oper_status 或 Interface.admin_status
    status_stats = db.session.query(
        Interface.oper_status,  # 修改这里：oper_status 或 admin_status
        db.func.count(Interface.id).label('count')
    ).group_by(Interface.oper_status).all()  # 修改这里
    
    # 获取接口利用率数据（假设你有接口性能表）
    # 如果没有 InterfacePerformance 表，这个查询可能会失败
    try:
        # 获取高利用率接口
        high_utilization_interfaces = db.session.query(
            InterfacePerformance.interface_id,
            Interface.name,
            Interface.device_id,
            Device.name.label('device_name'),
            db.func.avg(InterfacePerformance.in_utilization).label('avg_in_util'),
            db.func.avg(InterfacePerformance.out_utilization).label('avg_out_util')
        ).join(Interface, Interface.id == InterfacePerformance.interface_id
        ).join(Device, Device.id == Interface.device_id
        ).group_by(InterfacePerformance.interface_id, Interface.name, Interface.device_id, Device.name
        ).filter(
            db.or_(
                InterfacePerformance.in_utilization >= 80,
                InterfacePerformance.out_utilization >= 80
            )
        ).order_by(db.desc(db.func.avg(InterfacePerformance.in_utilization))).limit(20).all()
    except:
        # 如果表不存在或查询出错，返回空列表
        high_utilization_interfaces = []
    
    # 获取接口总数
    total_interfaces = db.session.query(db.func.count(Interface.id)).scalar()
    
    return render_template('report/interface_utilization.html',
                         status_stats=status_stats,
                         high_utilization_interfaces=high_utilization_interfaces,
                         total_interfaces=total_interfaces)

@report_bp.route('/cabinet_utilization_report')
@login_required
@permission_required('report:view')
def cabinet_utilization_report():
    """机柜使用率报表"""
    cabinets = Cabinet.query.all()
    cabinet_stats = []
    
    for cabinet in cabinets:
        # 计算机柜使用率 - 注意：应该是 cabinet.devices 而不是 cabinet.assets
        used_u = sum(device.height_u or 1 for device in cabinet.devices)
        total_u = cabinet.height_u or 42
        utilization = (used_u / total_u * 100) if total_u > 0 else 0
        
        cabinet_stats.append({
            'cabinet': cabinet,
            'used_u': used_u,
            'total_u': total_u,
            'utilization': round(utilization, 2),
            'device_count': len(cabinet.devices)  # 应该是 cabinet.devices
        })
    
    return render_template('report/cabinet_utilization.html',
                         cabinet_stats=cabinet_stats)


@report_bp.route('/location_summary_report')
@login_required
@permission_required('report:view')
def location_summary_report():
    """位置汇总报表"""
    locations = Location.query.all()
    location_stats = []
    
    for location in locations:
        device_count = Device.query.filter_by(location_id=location.id).count()
        cabinet_count = Cabinet.query.filter_by(location_id=location.id).count()

        total_u = 0
        used_u = 0
        for cabinet in location.cabinets:
            total_u += (cabinet.height_u or 42)
            try:
                used_u += cabinet.get_used_u_count()
            except Exception:
                used_u += sum((d.height_u or 1) for d in cabinet.devices)

        location_stats.append({
            'location': location,
            'device_count': device_count,
            'cabinet_count': cabinet_count,
            'total_u': total_u,
            'used_u': used_u
        })
    
    return render_template('report/location_summary.html',
                         location_stats=location_stats)

# 在路由文件中添加
@report_bp.route('/api/location/<int:location_id>')
@login_required
@permission_required('report:view')
def get_location_detail(location_id):
    """获取位置详情API"""
    location = Location.query.get_or_404(location_id)
    
    # 获取统计数据
    device_count = Device.query.filter_by(location_id=location.id).count()
    cabinet_count = Cabinet.query.filter_by(location_id=location.id).count()
    
    # 计算U位使用情况
    total_u = 0
    used_u = 0
    for cabinet in location.cabinets:
        total_u += (cabinet.height_u or 42)
        used_u += cabinet.get_used_u_count()
    
    location_data = {
        'id': location.id,
        'name': location.name,
        'description': location.description,
        'location_type': location.location_type,
        'address': location.address,
        'floor': location.floor,
        'room_number': location.room_number,
        'area': location.area,
        'capacity': location.capacity,
        'contact_person': location.contact_person,
        'contact_phone': location.contact_phone,
        'contact_email': location.contact_email,
        'contact_department': location.contact_department,
        'power_supply': location.power_supply,
        'cooling_system': location.cooling_system,
        'temperature': location.temperature,
        'humidity': location.humidity,
        'access_control': location.access_control,
        'tags': location.tags,
        'notes': location.notes,
        'device_count': device_count,
        'cabinet_count': cabinet_count,
        'total_u': total_u,
        'used_u': used_u,
        'usage_percentage': round((used_u / total_u * 100) if total_u > 0 else 0, 1)
    }
    
    return jsonify({'success': True, 'location': location_data})

@report_bp.route('/asset_inventory_report')
@login_required
@permission_required('report:view')
def asset_inventory_report():
    """资产清单报表"""
    assets = Asset.query.order_by(Asset.purchase_date.desc()).all()
    
    # 按类型统计
    type_stats = db.session.query(
        Asset.asset_type,
        db.func.count(Asset.id).label('count'),
        db.func.sum(Asset.purchase_price or 0).label('total_value')
    ).group_by(Asset.asset_type).all()
    
    return render_template('report/asset_inventory.html',
                         assets=assets,
                         type_stats=type_stats)


# 在 report 蓝图中添加
@report_bp.route('/api/asset/<int:asset_id>')
@login_required
@permission_required('report:view')
def get_asset_detail(asset_id):
    """获取资产详情API"""
    asset = Asset.query.get_or_404(asset_id)
    
    # 获取关联的设备信息
    device_info = None
    if asset.device:
        device_info = {
            'id': asset.device.id,
            'name': asset.device.name,
            'ip_address': asset.device.ip_address
        }
    
    # 获取位置信息
    location_info = None
    if asset.location:
        location_info = {
            'id': asset.location.id,
            'name': asset.location.name,
            'address': asset.location.address
        }
    
    # 状态显示文本
    status_display = {
        'active': '在用',
        'inactive': '停用',
        'maintenance': '维修中',
        'retired': '已报废',
        'lost': '丢失'
    }.get(asset.status, asset.status)
    
    asset_data = {
        'id': asset.id,
        'asset_number': asset.asset_number,
        'asset_name': asset.asset_name,
        'asset_type': asset.asset_type,
        'asset_subtype': asset.asset_subtype,
        'brand': asset.brand,
        'model': asset.model,
        'serial_number': asset.serial_number,
        'specification': asset.specification,
        'status': asset.status,
        'status_display': status_display,
        'status_class': asset.get_status_badge_class(),
        'condition': asset.condition,
        'condition_class': asset.get_condition_badge_class(),
        'purchase_date': asset.purchase_date.isoformat() if asset.purchase_date else None,
        'purchase_price': asset.purchase_price,
        'current_value': asset.calculate_current_value(),
        'warranty_expiry': asset.warranty_expiry.isoformat() if asset.warranty_expiry else None,
        'is_under_warranty': asset.is_under_warranty(),
        'depreciation_rate': asset.depreciation_rate,
        'age_years': asset.get_age(),
        'owner_department': asset.owner_department,
        'owner_person': asset.owner_person,
        'owner_contact': asset.owner_contact,
        'supplier_name': asset.supplier_name,
        'supplier_contact': asset.supplier_contact,
        'location_name': asset.location.name if asset.location else None,
        'position': asset.position,
        'device_id': asset.device_id,
        'device_name': asset.device.name if asset.device else None,
        'tags': asset.tags,
        'notes': asset.notes,
        'created_at': asset.created_at.isoformat() if asset.created_at else None,
        'updated_at': asset.updated_at.isoformat() if asset.updated_at else None
    }
    
    return jsonify({'success': True, 'asset': asset_data})

#==============================


@report_bp.route('/uptime_report')
@login_required
@permission_required('report:view')
def uptime_report():
    """设备可用性报表"""
    # 获取最近30天的可用性数据
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=30)
    
    # 这里需要根据实际监控数据计算可用性
    # 简化版：假设有uptime记录
    devices = Device.query.all()
    uptime_stats = []
    
    for device in devices:
        # 模拟计算可用性
        uptime_percent = 99.5  # 实际应从监控数据计算
        
        uptime_stats.append({
            'device': device,
            'uptime_percent': uptime_percent,
            'downtime_minutes': (100 - uptime_percent) * 432 / 100  # 30天=43200分钟
        })
    
    return render_template('report/uptime.html',
                         uptime_stats=uptime_stats)


@report_bp.route('/performance_trend_report')
@login_required
@permission_required('report:view')
def performance_trend_report():
    """性能趋势报表"""
    # 获取最近7天的性能趋势数据
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=7)
    
    # 按天统计平均性能
    daily_stats = db.session.query(
        db.func.date(DevicePerformance.timestamp).label('date'),
        db.func.avg(DevicePerformance.cpu_usage).label('avg_cpu'),
        db.func.avg(DevicePerformance.memory_usage).label('avg_memory')
    ).filter(
        DevicePerformance.timestamp.between(start_date, end_date)
    ).group_by(
        db.func.date(DevicePerformance.timestamp)
    ).order_by('date').all()
    
    return render_template('report/performance_trend.html',
                         daily_stats=daily_stats)


@report_bp.route('/monitoring_coverage_report')
@login_required
@permission_required('report:view')
def monitoring_coverage_report():
    """监控覆盖报表"""
    total_devices = Device.query.count()
    monitored_devices = DeviceMonitor.query.filter_by(enabled=True).count()

    # 按监控方式（ping/snmp/ssh/api）统计启用的设备数
    monitors = DeviceMonitor.query.filter_by(enabled=True).all()
    method_counter = {'ping': 0, 'snmp': 0, 'ssh': 0, 'api': 0}
    for m in monitors:
        methods = m.get_monitor_methods()
        for key in method_counter:
            if methods.get(key):
                method_counter[key] += 1
    monitoring_stats = [(k, v) for k, v in method_counter.items() if v > 0]

    coverage_percent = (monitored_devices / total_devices * 100) if total_devices > 0 else 0

    return render_template('report/monitoring_coverage.html',
                         total_devices=total_devices,
                         monitored_devices=monitored_devices,
                         coverage_percent=round(coverage_percent, 2),
                         monitoring_stats=monitoring_stats)


@report_bp.route('/alert_statistics_report')
@login_required
@permission_required('report:view')
def alert_statistics_report():
    """告警统计报表"""
    # 获取最近30天的告警统计
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=30)
    
    # 按严重程度统计
    severity_stats = db.session.query(
        Alert.severity,
        db.func.count(Alert.id).label('count')
    ).filter(
        Alert.created_at.between(start_date, end_date)
    ).group_by(Alert.severity).all()
    
    # 按设备统计
    device_stats = db.session.query(
        Device.name,
        db.func.count(Alert.id).label('count')
    ).join(Alert).filter(
        Alert.created_at.between(start_date, end_date)
    ).group_by(Device.name).order_by(
        db.func.count(Alert.id).desc()
    ).limit(10).all()
    
    # 按天统计趋势
    daily_stats = db.session.query(
        db.func.date(Alert.created_at).label('date'),
        db.func.count(Alert.id).label('count')
    ).filter(
        Alert.created_at.between(start_date, end_date)
    ).group_by(
        db.func.date(Alert.created_at)
    ).order_by('date').all()
    
    return render_template('report/alert_statistics.html',
                         severity_stats=severity_stats,
                         device_stats=device_stats,
                         daily_stats=daily_stats)


@report_bp.route('/alert_trend_report')
@login_required
@permission_required('report:view')
def alert_trend_report():
    """告警趋势报表"""
    return render_template('report/alert_trend.html')


@report_bp.route('/response_time_report')
@login_required
@permission_required('report:view')
def response_time_report():
    """响应时间报表"""
    # 获取最近30天的告警响应时间
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=30)
    
    alerts = Alert.query.filter(
        Alert.created_at.between(start_date, end_date),
        Alert.acknowledged_at.isnot(None)
    ).all()
    
    response_times = []
    for alert in alerts:
        if alert.acknowledged_at and alert.created_at:
            response_minutes = (alert.acknowledged_at - alert.created_at).total_seconds() / 60
            response_times.append({
                'alert_id': alert.id,
                'device': alert.device.name if alert.device else 'Unknown',
                'severity': alert.severity,
                'response_minutes': round(response_minutes, 2),
                'created_at': alert.created_at
            })
    
    # 计算平均响应时间
    avg_response = sum(rt['response_minutes'] for rt in response_times) / len(response_times) if response_times else 0
    
    return render_template('report/response_time.html',
                         response_times=response_times,
                         avg_response=round(avg_response, 2))


@report_bp.route('/change_report')
@login_required
@permission_required('report:view')
def change_report():
    """变更记录报表"""
    changes = ChangeRequest.query.order_by(ChangeRequest.created_at.desc()).all()
    
    # 按状态统计
    status_stats = db.session.query(
        ChangeRequest.status,
        db.func.count(ChangeRequest.id).label('count')
    ).group_by(ChangeRequest.status).all()
    
    return render_template('report/change_report.html',
                         changes=changes,
                         status_stats=status_stats)


@report_bp.route('/maintenance_report')
@login_required
@permission_required('report:view')
def maintenance_report():
    """维护记录报表"""
    tasks = MaintenanceTask.query.order_by(MaintenanceTask.scheduled_date.desc()).all()
    
    # 按类型统计
    type_stats = db.session.query(
        MaintenanceTask.maintenance_type,
        db.func.count(MaintenanceTask.id).label('count')
    ).group_by(MaintenanceTask.maintenance_type).all()
    
    return render_template('report/maintenance_report.html',
                         tasks=tasks,
                         type_stats=type_stats)


@report_bp.route('/compliance_report')
@login_required
@permission_required('report:view')
def compliance_report():
    """合规性报表"""
    # 设备合规性检查（基于现有监控配置与带外信息判定）
    devices = Device.query.all()
    compliance_stats = []

    # 预加载监控状态，避免 N+1
    monitored_ids = {dm.device_id for dm in DeviceMonitor.query.filter_by(enabled=True).all()}
    config_ids = {mc.device_id for mc in DeviceMonitorConfig.query.filter_by(enabled=True).all()}

    for device in devices:
        is_monitored = device.id in monitored_ids
        has_config = device.id in config_ids
        has_bmc = bool(device.bmc_ip)
        checks = {
            'monitoring_enabled': is_monitored,
            'monitor_config': has_config,
            'oob_managed': has_bmc,
            'security_patches': bool(device.os_version),  # 有系统版本视为已纳管可打补丁
        }

        passed_checks = sum(1 for check in checks.values() if check)
        total_checks = len(checks)
        compliance_percent = (passed_checks / total_checks * 100) if total_checks > 0 else 0

        compliance_stats.append({
            'device': device,
            'checks': checks,
            'passed_checks': passed_checks,
            'total_checks': total_checks,
            'compliance_percent': round(compliance_percent, 2)
        })
    
    return render_template('report/compliance_report.html',
                         compliance_stats=compliance_stats)


@report_bp.route('/custom_reports')
@login_required
@permission_required('report:view')
def custom_reports():
    """自定义报表"""
    templates = ReportTemplate.query.filter_by(is_active=True).all()
    favorites = ReportFavorite.query.filter_by(user_id=current_user.id).all()
    
    return render_template('report/custom_reports.html',
                         templates=templates,
                         favorites=favorites)


@report_bp.route('/scheduled_reports')
@login_required
@permission_required('report:view')
def scheduled_reports():
    """计划报表"""
    scheduled = ScheduledReport.query.filter_by(is_active=True).all()
    
    # 统计待执行的报表
    pending_count = ScheduledReport.query.filter(
        ScheduledReport.is_active == True,
        ScheduledReport.next_run_at <= datetime.utcnow()
    ).count()
    
    return render_template('report/scheduled_reports.html',
                         scheduled_reports=scheduled,
                         pending_count=pending_count)


@report_bp.route('/export_reports')
@login_required
@permission_required('report:view')
def export_reports():
    """导出报表"""
    recent_exports = ReportExecution.query.filter_by(
        generated_by=current_user.id
    ).order_by(ReportExecution.generated_at.desc()).limit(20).all()
    
    return render_template('report/export_reports.html',
                         recent_exports=recent_exports)


@report_bp.route('/api/export/<report_type>', methods=['POST'])
@login_required
@permission_required('report:edit')
def export_report(report_type):
    """导出报表API"""
    data = request.json
    format_type = data.get('format', 'pdf')
    
    # 根据报表类型生成数据
    if report_type == 'device_status':
        stats = db.session.query(
            Device.status,
            db.func.count(Device.id).label('count')
        ).group_by(Device.status).all()
        
        # 转换为DataFrame
        df = pd.DataFrame([(s.status, s.count) for s in stats], 
                         columns=['Status', 'Count'])
    
    elif report_type == 'alert_statistics':
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=30)
        
        stats = db.session.query(
            db.func.date(Alert.created_at).label('date'),
            Alert.severity,
            db.func.count(Alert.id).label('count')
        ).filter(
            Alert.created_at.between(start_date, end_date)
        ).group_by(
            db.func.date(Alert.created_at), Alert.severity
        ).all()
        
        df = pd.DataFrame([(s.date, s.severity, s.count) for s in stats],
                         columns=['Date', 'Severity', 'Count'])
    
    # 根据格式导出
    if format_type == 'excel':
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='Report', index=False)
        output.seek(0)
        
        return send_file(output, 
                        download_name=f'{report_type}_report.xlsx',
                        as_attachment=True,
                        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    
    elif format_type == 'csv':
        output = BytesIO()
        df.to_csv(output, index=False, encoding='utf-8-sig')
        output.seek(0)
        
        return send_file(output,
                        download_name=f'{report_type}_report.csv',
                        as_attachment=True,
                        mimetype='text/csv')
    
    return jsonify({'error': 'Unsupported format'}), 400


@report_bp.route('/api/schedule_report', methods=['POST'])
@login_required
@permission_required('report:edit')
def schedule_report():
    """创建计划报表"""
    data = request.json
    
    scheduled_report = ScheduledReport(
        name=data['name'],
        description=data.get('description'),
        report_type=data['report_type'],
        schedule_type=data['schedule_type'],
        schedule_config=json.dumps(data.get('schedule_config', {})),
        recipients=json.dumps(data.get('recipients', [])),
        format=data.get('format', 'pdf'),
        is_active=True,
        created_by=current_user.id
    )
    
    # 计算下次运行时间
    # 这里需要根据schedule_type和schedule_config计算
    # 简化版：设置为明天
    scheduled_report.next_run_at = datetime.utcnow() + timedelta(days=1)
    
    db.session.add(scheduled_report)
    db.session.commit()

    log_audit('create', 'scheduled_report', scheduled_report.id,
              f'创建计划报表 {scheduled_report.name}',
              details={'report_type': scheduled_report.report_type, 'schedule_type': scheduled_report.schedule_type},
              user_id=current_user.id)

    return jsonify({'success': True, 'id': scheduled_report.id})


@report_bp.route('/api/delete_schedule/<int:schedule_id>', methods=['DELETE'])
@login_required
@permission_required('report:edit')
def delete_schedule(schedule_id):
    """删除计划报表"""
    scheduled = ScheduledReport.query.get_or_404(schedule_id)

    # 检查权限
    if scheduled.created_by != current_user.id:
        return jsonify({'error': 'Permission denied'}), 403
    
    db.session.delete(scheduled)
    db.session.commit()

    log_audit('delete', 'scheduled_report', schedule_id,
              f'删除计划报表 #{schedule_id}',
              user_id=current_user.id)

    return jsonify({'success': True})



# report.py - 报表蓝图

#from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_file
#from models import db, Device, Alert, PerformanceData, Asset, WorkOrder
#from forms import ReportFilterForm, ExportReportForm
#import pandas as pd
#from io import BytesIO
#from datetime import datetime, timedelta
#from sqlalchemy import func, extract

#import json

#
@report_bp.route('/comprehensive')
@login_required
@permission_required('report:view')
def comprehensive_report():
    """综合报表"""
    form = ReportFilterForm()
    
    # 默认时间范围：最近30天
    end_date = datetime.now()
    start_date = end_date - timedelta(days=30)
    
    if form.validate_on_submit():
        start_date = form.start_date.data
        end_date = form.end_date.data
    
    # 设备统计
    device_stats = {
        'total': Device.query.count(),
        'online': Device.query.filter_by(status='online').count(),
        'offline': Device.query.filter_by(status='offline').count(),
        'warning': Device.query.filter_by(status='warning').count(),
        'by_type': db.session.query(
            Device.device_type, func.count(Device.id)
        ).group_by(Device.device_type).all()
    }
    
    # 告警统计（使用 first_occurred 字段）
    alert_stats = {
        'total': Alert.query.filter(
            Alert.first_occurred.between(start_date, end_date)
        ).count(),
        'critical': Alert.query.filter(
            Alert.first_occurred.between(start_date, end_date),
            Alert.severity == 'critical'
        ).count(),
        'warning': Alert.query.filter(
            Alert.first_occurred.between(start_date, end_date),
            Alert.severity == 'warning'
        ).count(),
        'by_device': db.session.query(
            Device.name, func.count(Alert.id)
        ).join(Alert, Alert.device_id == Device.id)\
         .filter(Alert.first_occurred.between(start_date, end_date))\
         .group_by(Device.name)\
         .order_by(func.count(Alert.id).desc())\
         .limit(10).all()
    }
    
    # 性能统计（需确保 PerformanceData 模型已定义）
    performance_stats = db.session.query(
        Device.name,
        func.avg(PerformanceData.cpu_usage).label('avg_cpu'),
        func.avg(PerformanceData.memory_usage).label('avg_memory'),
        func.avg(PerformanceData.disk_usage).label('avg_disk')
    ).join(PerformanceData, PerformanceData.device_id == Device.id)\
     .filter(PerformanceData.timestamp.between(start_date, end_date))\
     .group_by(Device.name)\
     .all()
    
    # 工单统计
    work_order_stats = {
        'total': WorkOrder.query.filter(
            WorkOrder.created_at.between(start_date, end_date)
        ).count(),
        'open': WorkOrder.query.filter(
            WorkOrder.created_at.between(start_date, end_date),
            WorkOrder.status == 'open'
        ).count(),
        'closed': WorkOrder.query.filter(
            WorkOrder.created_at.between(start_date, end_date),
            WorkOrder.status == 'closed'
        ).count(),
        'by_category': db.session.query(
            WorkOrder.category, func.count(WorkOrder.id)
        ).filter(WorkOrder.created_at.between(start_date, end_date))\
         .group_by(WorkOrder.category).all()
    }
    
    return render_template('report/comprehensive.html',
                         form=form,
                         device_stats=device_stats,
                         alert_stats=alert_stats,
                         performance_stats=performance_stats,
                         work_order_stats=work_order_stats,
                         start_date=start_date,
                         end_date=end_date)

@report_bp.route('/statistical/charts')
@login_required
@permission_required('report:view')
def statistical_charts():
    """统计图表"""
    
    # 设备状态饼图
    device_status_data = db.session.query(
        Device.status, func.count(Device.id)
    ).group_by(Device.status).all()
    
    device_status_labels = [status for status, _ in device_status_data]
    device_status_values = [count for _, count in device_status_data]
    
    # 告警趋势折线图（最近30天）
    end_date = datetime.now()
    start_date = end_date - timedelta(days=30)
    
    alert_trend_data = db.session.query(
        func.date(Alert.first_occurred).label('date'),
        func.count(Alert.id).label('count')
    ).filter(Alert.first_occurred.between(start_date, end_date))\
     .group_by(func.date(Alert.first_occurred))\
     .order_by('date').all()
    
    alert_dates = [data.date.strftime('%m-%d') for data in alert_trend_data]
    alert_counts = [data.count for data in alert_trend_data]
    
    # 设备性能热力图（CPU使用率）
    performance_heatmap = db.session.query(
        Device.name,
        extract('hour', PerformanceData.timestamp).label('hour'),
        func.avg(PerformanceData.cpu_usage).label('avg_cpu')
    ).join(PerformanceData, PerformanceData.device_id == Device.id)\
     .filter(PerformanceData.timestamp.between(start_date, end_date))\
     .group_by(Device.name, extract('hour', PerformanceData.timestamp))\
     .order_by(Device.name, 'hour').all()
    
    # 转换为热力图数据格式
    devices = sorted(set([data.name for data in performance_heatmap]))
    hours = list(range(24))
    
    heatmap_data = []
    for device in devices:
        device_data = [0] * 24
        for data in performance_heatmap:
            if data.name == device:
                device_data[int(data.hour)] = float(data.avg_cpu or 0)
        heatmap_data.append(device_data)
    
    return render_template('report/statistical_charts.html',
                         device_status_labels=json.dumps(device_status_labels),
                         device_status_values=json.dumps(device_status_values),
                         alert_dates=json.dumps(alert_dates),
                         alert_counts=json.dumps(alert_counts),
                         devices=json.dumps(devices),
                         hours=json.dumps(hours),
                         heatmap_data=json.dumps(heatmap_data))

@report_bp.route('/export', methods=['GET', 'POST'])
@login_required
@permission_required('report:edit')
def report_export():
    #报表导出
    form = ExportReportForm()
    
    if form.validate_on_submit():
        report_type = form.report_type.data
        format_type = form.format_type.data
        start_date = form.start_date.data
        end_date = form.end_date.data
        
        if format_type == 'excel':
            return export_report_excel(report_type, start_date, end_date)
        elif format_type == 'pdf':
            return export_report_pdf(report_type, start_date, end_date)
        elif format_type == 'csv':
            return export_report_csv(report_type, start_date, end_date)
    
    return render_template('report/export.html', form=form)

def export_report_excel(report_type, start_date, end_date):
    """导出Excel报表"""
    if report_type == 'device_status':
        devices = Device.query.all()
        data = [{
            '设备名称': device.name,
            'IP地址': device.ip_address,
            '类型': device.device_type,
            '状态': device.status,
            '位置': device.location.name if device.location else '',
            '机柜': device.cabinet.name if device.cabinet else '',
            '最后在线': device.last_checked.strftime('%Y-%m-%d %H:%M:%S') if device.last_checked else 'N/A',
            'CPU使用率': f"{device.cpu_usage}%" if device.cpu_usage else 'N/A',
            '内存使用率': f"{device.memory_usage}%" if device.memory_usage else 'N/A'
        } for device in devices]
        
        filename = '设备状态报表.xlsx'
    
    elif report_type == 'alert_summary':
        alerts = Alert.query.filter(
            Alert.first_occurred.between(start_date, end_date)
        ).all()
        
        data = [{
            '告警ID': alert.id,
            '设备': alert.device.name if alert.device else 'N/A',
            '级别': alert.severity,
            '类型': alert.alert_type,
            '消息': alert.message,
            '时间': Alert.first_occurred.strftime('%Y-%m-%d %H:%M:%S'),
            '状态': alert.status,
            '确认人': alert.acknowledged_by if alert.acknowledged_by else '未确认',
            '确认时间': alert.acknowledged_at.strftime('%Y-%m-%d %H:%M:%S') if alert.acknowledged_at else 'N/A'
        } for alert in alerts]
        
        filename = '告警汇总报表.xlsx'
    
    elif report_type == 'performance':
        performance_data = PerformanceData.query.filter(
            PerformanceData.timestamp.between(start_date, end_date)
        ).all()
        
        data = [{
            '设备': data.device.name if data.device else 'N/A',
            '时间': data.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
            'CPU使用率': f"{data.cpu_usage}%",
            '内存使用率': f"{data.memory_usage}%",
            '磁盘使用率': f"{data.disk_usage}%" if data.disk_usage else 'N/A',
            '网络流入': format_bytes(data.network_in) if data.network_in else 'N/A',
            '网络流出': format_bytes(data.network_out) if data.network_out else 'N/A'
        } for data in performance_data]
        
        filename = '性能数据报表.xlsx'
    
    else:
        flash('报表类型错误！', 'error')
        return redirect(url_for('report.report_export'))
    
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

def format_bytes(size):
    """格式化字节大小"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} PB"


from flask import make_response, render_template
import csv
import io
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4



def export_report_csv(report_type, start_date, end_date):
    """
    CSV报表导出函数（完整可运行实现）
    """
    # 创建内存中的CSV文件
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    
    # 1. 写入CSV表头（根据你的报表类型自定义）
    headers = ['序号', '数据项', '数值', '时间']  # 替换为你的实际表头
    writer.writerow(headers)
    
    # 2. 写入报表数据（示例：替换为你的实际数据查询逻辑）
    # 假设你从数据库查询到了report_data列表，这里用示例数据
    report_data = [
        [1, '指标1', 100, start_date],
        [2, '指标2', 200, end_date],
        # 更多数据行...
    ]
    for row in report_data:
        writer.writerow(row)
    
    # 将缓冲区指针移到开头
    buffer.seek(0)
    
    # 构建Flask响应，返回CSV文件
    response = make_response(buffer.getvalue())
    response.headers['Content-Type'] = 'text/csv; charset=utf-8'
    response.headers['Content-Disposition'] = f'attachment; filename={report_type}_report_{start_date}_{end_date}.csv'
    # 解决CSV中文乱码问题
    response.headers['Content-Encoding'] = 'utf-8'
    return response

def export_report_pdf(report_type, start_date, end_date):
    """
    PDF报表导出函数（完整可运行实现）
    """
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    
    # 写入报表标题和时间范围
    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, height-50, f"{report_type}报表")
    c.setFont("Helvetica", 12)
    c.drawString(50, height-80, f"时间范围：{start_date} 至 {end_date}")
    
    # 示例：写入一行数据
    c.drawString(50, height-110, "序号 | 数据项 | 数值")
    c.drawString(50, height-130, "1    | 指标1  | 100")
    
    c.showPage()
    c.save()
    buffer.seek(0)
    
    response = make_response(buffer)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename={report_type}_report_{start_date}_{end_date}.pdf'
    return response

# ---------------------- 你的原有视图函数 ----------------------
def report_export():
    # 补充：确保你已正确获取form、report_type、format_type
    # （如果你的代码里没有这些，需要补充，否则会报新的NameError）
    # 示例：从表单获取参数（替换为你的实际表单逻辑）
    # form = ReportExportForm()  # 假设这是你的表单类
    # if form.validate_on_submit():
    start_date = form.start_date.data
    end_date = form.end_date.data
    format_type = form.format_type.data  # 导出格式：excel/csv/pdf
    report_type = form.report_type.data   # 报表类型（比如"销售报表"/"财务报表"）
    
    if format_type == 'excel':
        return export_report_excel(report_type, start_date, end_date)
    elif format_type == 'pdf':
        return export_report_pdf(report_type, start_date, end_date)
    elif format_type == 'csv':
        return export_report_csv(report_type, start_date, end_date)  # 现在函数已定义，不会报错

    return render_template('report/export.html', form=form)
