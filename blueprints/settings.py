# blueprints/settings.py - 设置管理蓝图

from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from extensions import db
from models.models import User, OperationLog
from models.settings_models import SystemConfig
import json
from datetime import datetime
from utils.audit import log_audit
from utils.permission import permission_required

settings_bp = Blueprint('settings', __name__, url_prefix='/settings')

# ==================== 系统设置页面 ====================
@settings_bp.route('/')
@login_required
@permission_required('config:view')
def settings():
    """系统设置页面"""
    # 获取系统配置
    configs = SystemConfig.query.all()
    config_dict = {config.key: config.value for config in configs}
    
    # 获取用户信息
    user = current_user
    
    return render_template('settings/settings.html', 
                          configs=config_dict, 
                          user=user)

# ==================== 修改密码 ====================
@settings_bp.route('/change-password', methods=['GET', 'POST'])
@login_required
@permission_required('config:edit')
def change_password():
    """修改密码"""
    if request.method == 'GET':
        # 显示修改密码页面
        return render_template('settings/change_password.html')
    
    # POST 方法处理密码修改
    current_password = request.form.get('current_password')
    new_password = request.form.get('new_password')
    confirm_password = request.form.get('confirm_password')
    
    if not current_password or not new_password or not confirm_password:
        flash('所有字段都必须填写', 'danger')
        return redirect(url_for('settings.change_password'))
    
    if new_password != confirm_password:
        flash('新密码和确认密码不匹配', 'danger')
        return redirect(url_for('settings.change_password'))
    
    if len(new_password) < 6:
        flash('新密码长度不能少于6位', 'danger')
        return redirect(url_for('settings.change_password'))
    
    # 验证当前密码
    if not current_user.check_password(current_password):
        flash('当前密码不正确', 'danger')
        return redirect(url_for('settings.change_password'))
    
    try:
        # 更新密码
        current_user.set_password(new_password)
        db.session.commit()
        log_audit('update', 'auth', current_user.id, '修改密码', user_id=current_user.id)

        flash('密码修改成功，请重新登录', 'success')
        return redirect(url_for('auth.logout'))
    except Exception as e:
        db.session.rollback()
        flash(f'密码修改失败: {str(e)}', 'danger')
        return redirect(url_for('settings.change_password'))

# ==================== 更新个人信息 ====================
@settings_bp.route('/update-profile', methods=['POST'])
@login_required
@permission_required('config:edit')
def update_profile():
    """更新个人信息"""
    email = request.form.get('email', '').strip()
    full_name = request.form.get('full_name', '').strip()
    phone = request.form.get('phone', '').strip()
    department = request.form.get('department', '').strip()
    
    try:
        # 验证邮箱是否已被其他用户使用
        if email and email != current_user.email:
            existing_user = User.query.filter_by(email=email).first()
            if existing_user and existing_user.id != current_user.id:
                flash('邮箱已被其他用户使用', 'error')
                return redirect(url_for('settings.settings'))
        
        # 更新用户信息
        current_user.email = email
        current_user.full_name = full_name if full_name else None
        current_user.phone = phone if phone else None
        current_user.department = department if department else None
        
        db.session.commit()
        log_audit('update', 'profile', current_user.id, '更新个人信息', details={'username': current_user.username, 'email': email}, user_id=current_user.id)

        # 记录操作日志
        log = OperationLog(
            user_id=current_user.id,
            username=current_user.username,
            action='update_profile',
            target_type='user',
            target_id=current_user.id,
            details='更新个人信息',
            ip_address=request.remote_addr,
            user_agent=request.user_agent.string
        )
        db.session.add(log)
        db.session.commit()
        
        flash('个人信息更新成功', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'个人信息更新失败: {str(e)}', 'error')
    
    return redirect(url_for('settings.settings'))

# ==================== 更新系统设置 ====================
@settings_bp.route('/update-config', methods=['POST'])
@login_required
@permission_required('config:edit')
def update_config():
    """更新系统设置（仅管理员）"""
    if not current_user.is_admin:
        flash('无权限修改系统设置', 'error')
        return redirect(url_for('settings.settings'))
    
    try:
        # 获取表单数据
        site_name = request.form.get('site_name', '').strip()
        site_description = request.form.get('site_description', '').strip()
        items_per_page = request.form.get('items_per_page', '20').strip()
        enable_registration = 'enable_registration' in request.form
        maintenance_mode = 'maintenance_mode' in request.form
        
        # 更新配置
        configs_to_update = {
            'site_name': site_name,
            'site_description': site_description,
            'items_per_page': items_per_page,
            'enable_registration': '1' if enable_registration else '0',
            'maintenance_mode': '1' if maintenance_mode else '0'
        }
        
        for key, value in configs_to_update.items():
            config = SystemConfig.query.filter_by(key=key).first()
            if config:
                config.value = value
            else:
                config = SystemConfig(key=key, value=value)
                db.session.add(config)
        
        db.session.commit()
        log_audit('update', 'system', 0, '更新系统设置', details={'username': current_user.username, 'configs': list(configs_to_update.keys())}, user_id=current_user.id)

        # 记录操作日志
        log = OperationLog(
            user_id=current_user.id,
            username=current_user.username,
            action='update_config',
            target_type='system',
            target_id=0,
            details='更新系统设置',
            ip_address=request.remote_addr,
            user_agent=request.user_agent.string
        )
        db.session.add(log)
        db.session.commit()
        
        flash('系统设置更新成功', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'系统设置更新失败: {str(e)}', 'error')
    
    return redirect(url_for('settings.settings'))

"""
# ==================== 获取操作日志 ====================
@settings_bp.route('/operation-logs')
@login_required
def operation_logs():
    #获取操作日志
    page = request.args.get('page', 1, type=int)
    per_page = 20
    
    # 普通用户只能查看自己的日志，管理员可以查看所有日志
    if current_user.is_admin:
        logs_query = OperationLog.query
    else:
        logs_query = OperationLog.query.filter_by(user_id=current_user.id)
    
    logs = logs_query.order_by(OperationLog.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    
    return render_template('settings/operation_logs.html', logs=logs)
"""
# ==================== 备份设置 ====================
@settings_bp.route('/backup')
@login_required
@permission_required('config:view')
def backup_settings():
    """备份设置页面（仅管理员）"""
    if not current_user.is_admin:
        flash('无权限访问备份设置', 'error')
        return redirect(url_for('settings.settings'))
    
    return render_template('settings/backup.html')

# ==================== 执行备份 ====================
@settings_bp.route('/perform-backup', methods=['POST'])
@login_required
@permission_required('system:admin')
def perform_backup():
    """执行备份（仅管理员）"""
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': '无权限执行备份'})
    
    backup_type = request.form.get('backup_type', 'full')
    
    try:
        # 这里应该实现实际的备份逻辑
        # 例如：备份数据库、备份配置文件等
        
        # 记录操作日志
        log = OperationLog(
            user_id=current_user.id,
            username=current_user.username,
            action='backup',
            target_type='system',
            target_id=0,
            details=f'执行{backup_type}备份',
            ip_address=request.remote_addr,
            user_agent=request.user_agent.string
        )
        db.session.add(log)
        db.session.commit()
        log_audit('execute', 'system', 0, f'执行{backup_type}备份', details={'backup_type': backup_type, 'username': current_user.username}, user_id=current_user.id)

        return jsonify({'success': True, 'message': '备份任务已开始执行'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'备份失败: {str(e)}'})

# ==================== API: 获取配置 ====================
@settings_bp.route('/api/config/<key>')
@login_required
@permission_required('config:view')
def get_config(key):
    """获取指定配置值"""
    config = SystemConfig.query.filter_by(key=key).first()
    if config:
        return jsonify({'key': key, 'value': config.value})
    return jsonify({'key': key, 'value': None}), 404

# ==================== API: 更新配置 ====================
@settings_bp.route('/api/config/<key>', methods=['PUT'])
@login_required
@permission_required('config:edit')
def api_update_config(key):
    """API更新配置（仅管理员）"""
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': '无权限'}), 403
    
    data = request.get_json()
    if not data or 'value' not in data:
        return jsonify({'success': False, 'message': '缺少value参数'}), 400
    
    try:
        config = SystemConfig.query.filter_by(key=key).first()
        if config:
            config.value = str(data['value'])
        else:
            config = SystemConfig(key=key, value=str(data['value']))
            db.session.add(config)
        
        db.session.commit()
        log_audit('update', 'setting', key, f'API更新配置项 {key}', details={'key': key, 'value': data['value']}, user_id=current_user.id)
        return jsonify({'success': True, 'message': '配置更新成功'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'更新失败: {str(e)}'}), 500