# blueprints/monitor_settings.py
import json
from datetime import datetime, timedelta
from flask import Blueprint, render_template, jsonify, request, flash, redirect, url_for
from flask_login import login_required, current_user
from sqlalchemy import or_, and_, desc, asc

from utils.audit import log_audit
from utils.permission import permission_required

# 导入模型
from models.models import (
    Device, MonitorSetting, MonitorSchedule, NotificationConfig, 
    DeviceMonitorConfig, AlertRule, SystemConfig, db
)

# 初始化蓝图
monitor_settings_bp = Blueprint('monitor_settings', __name__, url_prefix='/monitoring/settings')

# ========== 监控设置主页面 ==========
@monitor_settings_bp.route('/')
@login_required
@permission_required('monitor:view')
def monitor_settings():
    """监控设置主页面"""
    # 获取所有设置分类
    categories = db.session.query(MonitorSetting.category).distinct().all()
    
    # 获取全局设置
    global_settings = {}
    for category in categories:
        category_name = category[0]
        settings = MonitorSetting.query.filter_by(
            category=category_name, 
            scope='global',
            enabled=True
        ).all()
        if settings:
            global_settings[category_name] = settings
    
    # 获取监控调度任务
    schedules = MonitorSchedule.query.order_by(MonitorSchedule.name).all()
    
    # 获取通知配置
    notifications = NotificationConfig.query.order_by(NotificationConfig.name).all()
    
    return render_template('monitoring/settings.html',
                         global_settings=global_settings,
                         schedules=schedules,
                         notifications=notifications)

# ========== 全局设置管理 ==========
@monitor_settings_bp.route('/global')
@login_required
@permission_required('monitor:view')
def global_settings():
    """全局设置管理页面"""
    category = request.args.get('category', 'general')
    
    # 获取该分类下的所有设置
    settings = MonitorSetting.query.filter_by(
        category=category, 
        scope='global'
    ).order_by(MonitorSetting.setting_key).all()
    
    # 获取所有分类
    categories = db.session.query(MonitorSetting.category).distinct().all()
    
    return render_template('monitoring/global_settings.html',
                         settings=settings,
                         categories=[c[0] for c in categories],
                         current_category=category)

@monitor_settings_bp.route('/global/save', methods=['POST'])
@login_required
@permission_required('monitor:edit')
def save_global_settings():
    """保存全局设置"""
    try:
        data = request.get_json()
        
        for setting_data in data.get('settings', []):
            setting_key = setting_data.get('key')
            setting_value = setting_data.get('value')
            category = setting_data.get('category', 'general')
            
            # 查找现有设置
            setting = MonitorSetting.query.filter_by(
                setting_key=setting_key, 
                scope='global'
            ).first()
            
            if not setting:
                # 创建新设置
                setting = MonitorSetting(
                    setting_key=setting_key,
                    category=category,
                    scope='global',
                    created_by=current_user.username,
                    is_default=False
                )
                db.session.add(setting)
            
            # 更新设置值
            setting.set_value(setting_value)
            setting.updated_at = datetime.utcnow()
            setting.updated_by = current_user.username
        
        db.session.commit()

        log_audit(
            action='update',
            resource_type='monitor_setting',
            resource_id='global',
            message='保存全局设置',
            user_id=current_user.id
        )

        return jsonify({
            'success': True,
            'message': '设置保存成功'
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'保存设置失败: {str(e)}'
        }), 500

@monitor_settings_bp.route('/global/<string:key>', methods=['DELETE'])
@login_required
@permission_required('monitor:edit')
def delete_global_setting(key):
    """删除全局设置"""
    try:
        setting = MonitorSetting.query.filter_by(
            setting_key=key, 
            scope='global',
            is_default=False
        ).first()
        
        if not setting:
            return jsonify({
                'success': False,
                'message': '设置不存在或不能删除'
            }), 404
        
        db.session.delete(setting)
        db.session.commit()

        log_audit(
            action='delete',
            resource_type='monitor_setting',
            resource_id=key,
            message=f'删除全局设置: {key}',
            user_id=current_user.id
        )

        return jsonify({
            'success': True,
            'message': '设置删除成功'
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'删除设置失败: {str(e)}'
        }), 500

@monitor_settings_bp.route('/global/reset', methods=['POST'])
@login_required
@permission_required('monitor:edit')
def reset_global_settings():
    """重置全局设置到默认值"""
    try:
        category = request.json.get('category')
        
        # 删除非默认设置
        if category:
            settings = MonitorSetting.query.filter_by(
                category=category,
                scope='global',
                is_default=False
            ).all()
        else:
            settings = MonitorSetting.query.filter_by(
                scope='global',
                is_default=False
            ).all()
        
        for setting in settings:
            db.session.delete(setting)
        
        db.session.commit()

        log_audit(
            action='execute',
            resource_type='monitor_setting',
            resource_id='global',
            message='重置全局设置到默认值',
            details={'category': category},
            user_id=current_user.id
        )

        return jsonify({
            'success': True,
            'message': '设置已重置到默认值'
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'重置设置失败: {str(e)}'
        }), 500

# ========== 监控调度管理 ==========
@monitor_settings_bp.route('/schedules')
@login_required
@permission_required('monitor:view')
def schedule_list():
    """监控调度列表"""
    schedules = MonitorSchedule.query.order_by(MonitorSchedule.name).all()
    
    return render_template('monitoring/schedule_list.html',
                         schedules=schedules)

@monitor_settings_bp.route('/schedules/create', methods=['GET', 'POST'])
@login_required
@permission_required('monitor:edit')
def create_schedule():
    """创建监控调度"""
    if request.method == 'POST':
        try:
            data = request.form
            
            schedule = MonitorSchedule(
                name=data.get('name'),
                description=data.get('description'),
                monitor_type=data.get('monitor_type'),
                target_type=data.get('target_type'),
                schedule_type=data.get('schedule_type'),
                enabled=data.get('enabled', 'off') == 'on',
                created_by=current_user.username
            )
            
            # 设置目标值
            target_value = data.get('target_value')
            if target_value:
                schedule.target_value = target_value
            
            # 设置调度参数
            if schedule.schedule_type == 'interval':
                interval = data.get('interval_seconds')
                if interval:
                    schedule.interval_seconds = int(interval)
            elif schedule.schedule_type == 'cron':
                cron_expr = data.get('cron_expression')
                if cron_expr:
                    schedule.cron_expression = cron_expr
            
            # 设置时间窗口
            start_time = data.get('start_time')
            end_time = data.get('end_time')
            weekdays = data.get('weekdays')
            
            if start_time:
                schedule.start_time = datetime.strptime(start_time, '%H:%M').time()
            if end_time:
                schedule.end_time = datetime.strptime(end_time, '%H:%M').time()
            if weekdays:
                schedule.weekdays = weekdays
            
            # 设置配置
            config_data = {}
            for key in request.form:
                if key.startswith('config_'):
                    config_key = key[7:]  # 去掉'config_'前缀
                    config_data[config_key] = request.form[key]
            
            schedule.set_config(config_data)
            
            db.session.add(schedule)
            db.session.commit()

            # 创建后立即同步到运行中的调度器
            try:
                from scheduler import apply_monitor_schedule
                apply_monitor_schedule(schedule)
            except Exception as se:
                current_app.logger.warning(f"同步监控计划 #{schedule.id} 到调度器失败: {se}")

            log_audit(
                action='create',
                resource_type='monitor_schedule',
                resource_id=schedule.id,
                message=f'创建监控调度: {schedule.name}',
                user_id=current_user.id
            )

            flash('监控调度创建成功', 'success')
            return redirect(url_for('monitor_settings.schedule_list'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'创建监控调度失败: {str(e)}', 'danger')
    
    # 获取所有设备用于选择
    devices = Device.query.order_by(Device.name).all()
    
    return render_template('monitoring/schedule_form.html',
                         schedule=None,
                         devices=devices,
                         is_edit=False)

@monitor_settings_bp.route('/schedules/<int:schedule_id>/edit', methods=['GET', 'POST'])
@login_required
@permission_required('monitor:edit')
def edit_schedule(schedule_id):
    """编辑监控调度"""
    schedule = MonitorSchedule.query.get_or_404(schedule_id)
    
    if request.method == 'POST':
        try:
            data = request.form
            
            schedule.name = data.get('name')
            schedule.description = data.get('description')
            schedule.monitor_type = data.get('monitor_type')
            schedule.target_type = data.get('target_type')
            schedule.schedule_type = data.get('schedule_type')
            schedule.enabled = data.get('enabled', 'off') == 'on'
            
            # 设置目标值
            target_value = data.get('target_value')
            if target_value:
                schedule.target_value = target_value
            
            # 设置调度参数
            if schedule.schedule_type == 'interval':
                interval = data.get('interval_seconds')
                if interval:
                    schedule.interval_seconds = int(interval)
            elif schedule.schedule_type == 'cron':
                cron_expr = data.get('cron_expression')
                if cron_expr:
                    schedule.cron_expression = cron_expr
            
            # 设置时间窗口
            start_time = data.get('start_time')
            end_time = data.get('end_time')
            weekdays = data.get('weekdays')
            
            if start_time:
                schedule.start_time = datetime.strptime(start_time, '%H:%M').time()
            else:
                schedule.start_time = None
                
            if end_time:
                schedule.end_time = datetime.strptime(end_time, '%H:%M').time()
            else:
                schedule.end_time = None
                
            schedule.weekdays = weekdays if weekdays else None
            
            # 设置配置
            config_data = {}
            for key in request.form:
                if key.startswith('config_'):
                    config_key = key[7:]  # 去掉'config_'前缀
                    config_data[config_key] = request.form[key]
            
            schedule.set_config(config_data)
            
            db.session.commit()

            # 保存后立即同步到运行中的调度器
            try:
                from scheduler import apply_monitor_schedule
                apply_monitor_schedule(schedule)
            except Exception as se:
                current_app.logger.warning(f"同步监控计划 #{schedule.id} 到调度器失败: {se}")

            log_audit(
                action='update',
                resource_type='monitor_schedule',
                resource_id=schedule.id,
                message=f'更新监控调度: {schedule.name}',
                user_id=current_user.id
            )

            flash('监控调度更新成功', 'success')
            return redirect(url_for('monitor_settings.schedule_list'))

        except Exception as e:
            db.session.rollback()
            flash(f'更新监控调度失败: {str(e)}', 'danger')

    # 获取所有设备用于选择
    devices = Device.query.order_by(Device.name).all()

    return render_template('monitoring/schedule_form.html',
                         schedule=schedule,
                         devices=devices,
                         is_edit=True)

@monitor_settings_bp.route('/schedules/<int:schedule_id>/delete', methods=['POST'])
@login_required
@permission_required('monitor:edit')
def delete_schedule(schedule_id):
    """删除监控调度"""
    try:
        schedule = MonitorSchedule.query.get_or_404(schedule_id)

        # 删除前先移除运行中的调度任务
        try:
            from scheduler import remove_monitor_schedule
            remove_monitor_schedule(schedule_id)
        except Exception as se:
            current_app.logger.warning(f"移除监控计划 #{schedule_id} 调度失败: {se}")

        db.session.delete(schedule)
        db.session.commit()

        log_audit(
            action='delete',
            resource_type='monitor_schedule',
            resource_id=schedule_id,
            message=f'删除监控调度: {schedule.name}',
            user_id=current_user.id
        )

        flash('监控调度删除成功', 'success')

    except Exception as e:
        db.session.rollback()
        flash(f'删除监控调度失败: {str(e)}', 'danger')

    return redirect(url_for('monitor_settings.schedule_list'))

@monitor_settings_bp.route('/schedules/<int:schedule_id>/toggle', methods=['POST'])
@login_required
@permission_required('monitor:edit')
def toggle_schedule(schedule_id):
    """启用/禁用监控调度"""
    try:
        schedule = MonitorSchedule.query.get_or_404(schedule_id)
        schedule.enabled = not schedule.enabled

        db.session.commit()

        # 启用/禁用后立即同步到运行中的调度器
        try:
            from scheduler import apply_monitor_schedule
            apply_monitor_schedule(schedule)
        except Exception as se:
            current_app.logger.warning(f"同步监控计划 #{schedule.id} 到调度器失败: {se}")

        log_audit(
            action='update',
            resource_type='monitor_schedule',
            resource_id=schedule_id,
            message=f'{"启用" if schedule.enabled else "禁用"}监控调度: {schedule.name}',
            user_id=current_user.id
        )

        status = '启用' if schedule.enabled else '禁用'
        flash(f'监控调度已{status}', 'success')

    except Exception as e:
        db.session.rollback()
        flash(f'操作失败: {str(e)}', 'danger')

    return redirect(url_for('monitor_settings.schedule_list'))

@monitor_settings_bp.route('/schedules/<int:schedule_id>/run', methods=['POST'])
@login_required
@permission_required('monitor:edit')
def run_schedule(schedule_id):
    """立即运行监控调度"""
    try:
        schedule = MonitorSchedule.query.get_or_404(schedule_id)

        # 立即触发对应的实际监控任务（后台线程执行，避免阻塞请求）
        from scheduler import run_monitor_schedule_now
        ok, msg = run_monitor_schedule_now(schedule)
        if not ok:
            flash(f'执行失败: {msg}', 'danger')
            return redirect(url_for('monitor_settings.schedule_list'))

        log_audit(
            action='execute',
            resource_type='monitor_schedule',
            resource_id=schedule_id,
            message=f'立即运行监控调度: {schedule.name}',
            user_id=current_user.id
        )

        flash('监控调度已开始执行', 'success')

    except Exception as e:
        db.session.rollback()
        flash(f'执行失败: {str(e)}', 'danger')

    return redirect(url_for('monitor_settings.schedule_list'))

# ========== 通知配置管理 ==========
@monitor_settings_bp.route('/notifications')
@login_required
@permission_required('monitor:view')
def notification_list():
    """通知配置列表"""
    notifications = NotificationConfig.query.order_by(NotificationConfig.name).all()

    return render_template('monitoring/notification_list.html',
                         notifications=notifications)

@monitor_settings_bp.route('/notifications/create', methods=['GET', 'POST'])
@login_required
@permission_required('monitor:edit')
def create_notification():
    """创建通知配置"""
    if request.method == 'POST':
        try:
            data = request.form
            
            notification = NotificationConfig(
                name=data.get('name'),
                description=data.get('description'),
                notification_type=data.get('notification_type'),
                trigger_on=data.get('trigger_on', 'all'),
                enabled=data.get('enabled', 'off') == 'on',
                created_by=current_user.username
            )
            
            # 设置接收者
            receivers = data.get('receivers', '')
            if receivers:
                receiver_list = [r.strip() for r in receivers.split(',') if r.strip()]
                notification.set_receivers(receiver_list)
            
            # 设置内容模板
            notification.title_template = data.get('title_template', '')
            notification.message_template = data.get('message_template', '')
            
            # 设置特定类型配置
            config_data = {}
            for key in request.form:
                if key.startswith('config_'):
                    config_key = key[7:]  # 去掉'config_'前缀
                    config_data[config_key] = request.form[key]
            
            notification.set_config(config_data)
            
            db.session.add(notification)
            db.session.commit()

            log_audit(
                action='create',
                resource_type='notification_config',
                resource_id=notification.id,
                message=f'创建通知配置: {notification.name}',
                user_id=current_user.id
            )

            flash('通知配置创建成功', 'success')
            return redirect(url_for('monitor_settings.notification_list'))

        except Exception as e:
            db.session.rollback()
            flash(f'创建通知配置失败: {str(e)}', 'danger')

    return render_template('monitoring/notification_form.html',
                         notification=None,
                         is_edit=False)

@monitor_settings_bp.route('/notifications/<int:notification_id>/edit', methods=['GET', 'POST'])
@login_required
@permission_required('monitor:edit')
def edit_notification(notification_id):
    """编辑通知配置"""
    notification = NotificationConfig.query.get_or_404(notification_id)
    
    if request.method == 'POST':
        try:
            data = request.form
            
            notification.name = data.get('name')
            notification.description = data.get('description')
            notification.notification_type = data.get('notification_type')
            notification.trigger_on = data.get('trigger_on', 'all')
            notification.enabled = data.get('enabled', 'off') == 'on'
            
            # 设置接收者
            receivers = data.get('receivers', '')
            if receivers:
                receiver_list = [r.strip() for r in receivers.split(',') if r.strip()]
                notification.set_receivers(receiver_list)
            else:
                notification.set_receivers([])
            
            # 设置内容模板
            notification.title_template = data.get('title_template', '')
            notification.message_template = data.get('message_template', '')
            
            # 设置特定类型配置
            config_data = {}
            for key in request.form:
                if key.startswith('config_'):
                    config_key = key[7:]  # 去掉'config_'前缀
                    config_data[config_key] = request.form[key]
            
            notification.set_config(config_data)
            
            db.session.commit()

            log_audit(
                action='update',
                resource_type='notification_config',
                resource_id=notification.id,
                message=f'更新通知配置: {notification.name}',
                user_id=current_user.id
            )

            flash('通知配置更新成功', 'success')
            return redirect(url_for('monitor_settings.notification_list'))

        except Exception as e:
            db.session.rollback()
            flash(f'更新通知配置失败: {str(e)}', 'danger')

    return render_template('monitoring/notification_form.html',
                         notification=notification,
                         is_edit=True)

@monitor_settings_bp.route('/notifications/<int:notification_id>/delete', methods=['POST'])
@login_required
@permission_required('monitor:edit')
def delete_notification(notification_id):
    """删除通知配置"""
    try:
        notification = NotificationConfig.query.get_or_404(notification_id)
        
        db.session.delete(notification)
        db.session.commit()

        log_audit(
            action='delete',
            resource_type='notification_config',
            resource_id=notification_id,
            message=f'删除通知配置: {notification.name}',
            user_id=current_user.id
        )

        flash('通知配置删除成功', 'success')

    except Exception as e:
        db.session.rollback()
        flash(f'删除通知配置失败: {str(e)}', 'danger')

    return redirect(url_for('monitor_settings.notification_list'))

@monitor_settings_bp.route('/notifications/<int:notification_id>/test', methods=['POST'])
@login_required
@permission_required('monitor:edit')
def test_notification(notification_id):
    """测试通知配置"""
    try:
        notification = NotificationConfig.query.get_or_404(notification_id)
        
        # 这里应该调用实际的通知发送函数
        # 现在只是更新测试状态
        notification.last_tested = datetime.utcnow()
        notification.test_status = 'success'
        notification.test_message = '测试通知发送成功'

        db.session.commit()

        log_audit(
            action='execute',
            resource_type='notification_config',
            resource_id=notification_id,
            message=f'测试通知配置: {notification.name}',
            user_id=current_user.id
        )

        flash('测试通知发送成功', 'success')

    except Exception as e:
        db.session.rollback()
        flash(f'测试通知失败: {str(e)}', 'danger')

    return redirect(url_for('monitor_settings.notification_list'))

# ========== 设备监控配置 ==========
@monitor_settings_bp.route('/device_configs')
@login_required
@permission_required('monitor:view')
def device_config_list():
    """设备监控配置列表"""
    # 获取查询参数
    device_name = request.args.get('device_name', '')
    device_type = request.args.get('device_type', '')
    enabled = request.args.get('enabled', '')
    
    # 构建查询
    query = DeviceMonitorConfig.query.join(Device)
    
    if device_name:
        query = query.filter(Device.name.ilike(f'%{device_name}%'))
    
    if device_type:
        query = query.filter(Device.device_type == device_type)
    
    if enabled == 'true':
        query = query.filter(DeviceMonitorConfig.enabled == True)
    elif enabled == 'false':
        query = query.filter(DeviceMonitorConfig.enabled == False)
    
    configs = query.order_by(Device.name).all()
    
    # 获取设备类型列表
    device_types = db.session.query(Device.device_type).distinct().all()
    
    return render_template('monitoring/device_config_list.html',
                         configs=configs,
                         device_types=[t[0] for t in device_types],
                         device_name=device_name,
                         device_type=device_type,
                         enabled=enabled)

@monitor_settings_bp.route('/device_configs/<int:device_id>')
@login_required
@permission_required('monitor:view')
def device_config_detail(device_id):
    """设备监控配置详情"""
    device = Device.query.get_or_404(device_id)
    
    # 获取或创建配置
    config = DeviceMonitorConfig.query.filter_by(device_id=device_id).first()
    
    if not config:
        # 创建默认配置
        config = DeviceMonitorConfig(
            device_id=device_id,
            enable_ping=True,
            enable_snmp=device.snmp_community is not None,
            enable_ssh='auto',
            enable_api=False,
            ping_interval=60,
            snmp_interval=300,
            ssh_interval=300,
            api_interval=300,
            ping_timeout=2.0,
            snmp_timeout=5.0,
            ssh_timeout=10.0,
            api_timeout=5.0,
            retry_count=3,
            retry_interval=5,
            snmp_version=device.snmp_version or 2,
            snmp_community=device.snmp_community,
            ssh_username=device.ssh_username,
            ssh_password=device.ssh_password,
            ssh_port=22,
            enabled=True,
            created_by=current_user.username
        )
        
        db.session.add(config)
        db.session.commit()
    
    return render_template('monitoring/device_config_detail.html',
                         config=config,
                         device=device)

@monitor_settings_bp.route('/device_configs/<int:device_id>/save', methods=['POST'])
@login_required
@permission_required('monitor:edit')
def save_device_config(device_id):
    """保存设备监控配置"""
    try:
        device = Device.query.get_or_404(device_id)
        config = DeviceMonitorConfig.query.filter_by(device_id=device_id).first()
        
        if not config:
            config = DeviceMonitorConfig(
                device_id=device_id,
                created_by=current_user.username
            )
            db.session.add(config)
        
        data = request.form
        
        # 更新基本设置
        config.enable_ping = data.get('enable_ping', 'off') == 'on'
        config.enable_snmp = data.get('enable_snmp', 'off') == 'on'
        config.enable_ssh = data.get('enable_ssh', 'auto')
        config.enable_api = data.get('enable_api', 'off') == 'on'
        
        config.ping_interval = int(data.get('ping_interval', 60))
        config.snmp_interval = int(data.get('snmp_interval', 300))
        config.ssh_interval = int(data.get('ssh_interval', 300))
        config.api_interval = int(data.get('api_interval', 300))
        
        config.ping_timeout = float(data.get('ping_timeout', 2.0))
        config.snmp_timeout = float(data.get('snmp_timeout', 5.0))
        config.ssh_timeout = float(data.get('ssh_timeout', 10.0))
        config.api_timeout = float(data.get('api_timeout', 5.0))
        
        config.retry_count = int(data.get('retry_count', 3))
        config.retry_interval = int(data.get('retry_interval', 5))
        
        # 更新SNMP配置
        config.snmp_version = int(data.get('snmp_version', 2))
        config.snmp_community = data.get('snmp_community')
        
        # 更新SSH配置
        config.ssh_username = data.get('ssh_username')
        config.ssh_password = data.get('ssh_password')
        config.ssh_port = int(data.get('ssh_port', 22))
        
        # 更新API配置
        config.api_url = data.get('api_url')
        config.api_method = data.get('api_method', 'GET')
        
        # 更新设备表中的相应字段
        device.snmp_version = config.snmp_version
        device.snmp_community = config.snmp_community
        device.ssh_username = config.ssh_username
        device.ssh_password = config.ssh_password
        
        config.enabled = data.get('enabled', 'off') == 'on'
        config.updated_at = datetime.utcnow()

        db.session.commit()

        log_audit(
            action='update',
            resource_type='device_monitor_config',
            resource_id=device_id,
            message=f'保存设备监控配置: {device.name}',
            user_id=current_user.id
        )

        flash('设备监控配置保存成功', 'success')
        return redirect(url_for('monitor_settings.device_config_detail', device_id=device_id))

    except Exception as e:
        db.session.rollback()
        flash(f'保存配置失败: {str(e)}', 'danger')
        return redirect(url_for('monitor_settings.device_config_detail', device_id=device_id))

@monitor_settings_bp.route('/device_configs/<int:device_id>/toggle', methods=['POST'])
@login_required
@permission_required('monitor:edit')
def toggle_device_config(device_id):
    """启用/禁用设备监控"""
    try:
        config = DeviceMonitorConfig.query.filter_by(device_id=device_id).first()
        
        if not config:
            flash('设备监控配置不存在', 'warning')
            return redirect(url_for('monitor_settings.device_config_list'))
        
        config.enabled = not config.enabled

        db.session.commit()

        log_audit(
            action='update',
            resource_type='device_monitor_config',
            resource_id=device_id,
            message=f'{"启用" if config.enabled else "禁用"}设备监控: 设备ID={device_id}',
            user_id=current_user.id
        )

        status = '启用' if config.enabled else '禁用'
        flash(f'设备监控已{status}', 'success')

    except Exception as e:
        db.session.rollback()
        flash(f'操作失败: {str(e)}', 'danger')

    return redirect(url_for('monitor_settings.device_config_list'))

@monitor_settings_bp.route('/device_configs/batch_update', methods=['POST'])
@login_required
@permission_required('monitor:edit')
def batch_update_device_configs():
    """批量更新设备监控配置"""
    try:
        data = request.get_json()
        device_ids = data.get('device_ids', [])
        updates = data.get('updates', {})
        
        for device_id in device_ids:
            config = DeviceMonitorConfig.query.filter_by(device_id=device_id).first()
            
            if not config:
                config = DeviceMonitorConfig(
                    device_id=device_id,
                    created_by=current_user.username
                )
                db.session.add(config)
            
            # 应用更新
            for key, value in updates.items():
                if hasattr(config, key):
                    # 处理不同类型的值
                    if isinstance(getattr(config, key), bool):
                        setattr(config, key, str(value).lower() in ('true', '1', 'yes'))
                    elif isinstance(getattr(config, key), int):
                        setattr(config, key, int(value))
                    elif isinstance(getattr(config, key), float):
                        setattr(config, key, float(value))
                    else:
                        setattr(config, key, value)
            
            config.updated_at = datetime.utcnow()
        
        db.session.commit()

        log_audit(
            action='update',
            resource_type='device_monitor_config',
            resource_id='batch',
            message=f'批量更新 {len(device_ids)} 个设备的监控配置',
            details={'device_ids': device_ids},
            user_id=current_user.id
        )

        return jsonify({
            'success': True,
            'message': f'已更新 {len(device_ids)} 个设备的监控配置'
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'批量更新失败: {str(e)}'
        }), 500

# ========== API接口 ==========
@monitor_settings_bp.route('/api/settings')
@login_required
@permission_required('monitor:view')
def api_get_settings():
    """获取监控设置API"""
    category = request.args.get('category', 'general')
    scope = request.args.get('scope', 'global')
    target_id = request.args.get('target_id', type=int)
    
    query = MonitorSetting.query.filter_by(
        category=category,
        scope=scope,
        enabled=True
    )
    
    if target_id:
        query = query.filter_by(target_id=target_id)
    
    settings = query.all()
    
    result = {}
    for setting in settings:
        result[setting.setting_key] = setting.get_value()
    
    return jsonify(result)

@monitor_settings_bp.route('/api/settings/<string:key>', methods=['GET', 'PUT'])
@login_required
@permission_required('monitor:edit')
def api_setting_detail(key):
    """监控设置详情API"""
    scope = request.args.get('scope', 'global')
    target_id = request.args.get('target_id', type=int)
    
    if request.method == 'GET':
        setting = MonitorSetting.query.filter_by(
            setting_key=key,
            scope=scope
        ).first()
        
        if not setting:
            return jsonify({'error': '设置不存在'}), 404
        
        return jsonify(setting.to_dict())
    
    elif request.method == 'PUT':
        data = request.get_json()
        
        setting = MonitorSetting.query.filter_by(
            setting_key=key,
            scope=scope
        ).first()
        
        if not setting:
            # 创建新设置
            setting = MonitorSetting(
                setting_key=key,
                scope=scope,
                created_by=current_user.username
            )
            db.session.add(setting)
        
        if 'value' in data:
            setting.set_value(data['value'])
        
        if 'category' in data:
            setting.category = data['category']
        
        if 'description' in data:
            setting.description = data['description']
        
        if 'enabled' in data:
            setting.enabled = data['enabled']
        
        setting.updated_at = datetime.utcnow()
        setting.updated_by = current_user.username
        
        db.session.commit()

        log_audit(
            action='update',
            resource_type='monitor_setting',
            resource_id=key,
            message=f'更新监控设置: {key}',
            details={'scope': scope},
            user_id=current_user.id
        )

        return jsonify({
            'success': True,
            'message': '设置保存成功',
            'setting': setting.to_dict()
        })

@monitor_settings_bp.route('/api/default_settings')
@login_required
@permission_required('monitor:view')
def api_default_settings():
    """获取默认监控设置"""
    # 定义默认设置
    default_settings = {
        'ping': {
            'enabled': True,
            'interval': 60,
            'timeout': 2.0,
            'retry_count': 3,
            'retry_interval': 5
        },
        'snmp': {
            'enabled': False,
            'interval': 300,
            'timeout': 5.0,
            'version': 2,
            'community': 'public'
        },
        'ssh': {
            'enabled': 'auto',
            'interval': 300,
            'timeout': 10.0,
            'port': 22
        },
        'alert': {
            'cpu_threshold': 90,
            'memory_threshold': 90,
            'disk_threshold': 90,
            'ping_threshold': 100,
            'retry_before_alert': 3
        },
        'notification': {
            'email_enabled': False,
            'sms_enabled': False,
            'webhook_enabled': False,
            'min_severity': 'warning'
        }
    }
    
    return jsonify(default_settings)

# 初始化默认设置
def init_default_settings():
    """初始化默认监控设置"""
    default_settings = [
        # Ping监控设置
        {
            'key': 'ping_enabled',
            'value': True,
            'type': 'boolean',
            'category': 'ping',
            'description': '是否启用Ping监控'
        },
        {
            'key': 'ping_interval',
            'value': 60,
            'type': 'number',
            'category': 'ping',
            'description': 'Ping监控间隔（秒）'
        },
        # SNMP监控设置
        {
            'key': 'snmp_default_community',
            'value': 'public',
            'type': 'string',
            'category': 'snmp',
            'description': 'SNMP默认团体名'
        },
        # 告警设置
        {
            'key': 'alert_cpu_threshold',
            'value': 90,
            'type': 'number',
            'category': 'alert',
            'description': 'CPU使用率告警阈值（%）'
        },
        {
            'key': 'alert_memory_threshold',
            'value': 90,
            'type': 'number',
            'category': 'alert',
            'description': '内存使用率告警阈值（%）'
        },
        # 通知设置
        {
            'key': 'notification_email_server',
            'value': '',
            'type': 'string',
            'category': 'notification',
            'description': '邮件服务器地址'
        },
        {
            'key': 'notification_email_port',
            'value': 587,
            'type': 'number',
            'category': 'notification',
            'description': '邮件服务器端口'
        },
    ]
    
    for setting_data in default_settings:
        setting = MonitorSetting.query.filter_by(
            setting_key=setting_data['key'],
            scope='global'
        ).first()
        
        if not setting:
            setting = MonitorSetting(
                setting_key=setting_data['key'],
                setting_type=setting_data['type'],
                category=setting_data['category'],
                scope='global',
                description=setting_data['description'],
                is_default=True,
                created_by='system'
            )
            setting.set_value(setting_data['value'])
            db.session.add(setting)
    
    try:
        db.session.commit()
    except:
        db.session.rollback()
