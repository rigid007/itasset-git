from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
from datetime import datetime,timedelta
import json
# 正确: 从 extensions 导入 db
from extensions import db
import base64
import re
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from datetime import datetime
from sqlalchemy.exc import IntegrityError
# 如果使用Flask-WTF CSRF保护，导入验证函数
from flask_wtf.csrf import validate_csrf, ValidationError
from utils.audit import log_audit
from utils.permission import permission_required



import csv
import io
from sqlalchemy import  func, or_

from models.models import OperationLog,User,Cabinet
from models.settings_models import SystemConfig
from models.config_models import (SystemSetting,GlobalParameter,DiscoveryConfig,
    BackupConfig,CollectionSetting,MonitoringTemplate,SNMPSetting,AuditLog,Role,Permission,LogSetting,APISetting,IntegrationSetting,
    ThresholdProfile,SystemLog,AlertConfigTemplate,NotificationTemplate,EscalationPolicy,Credential,WebhookSetting)


config_bp = Blueprint('config', __name__, url_prefix='/config')

# ========== 系统配置 ==========

@config_bp.route('/system-settings')
@login_required
@permission_required('config:view')
def system_settings():
    # 获取所有不重复的分类
    categories = db.session.query(SystemConfig.category).distinct().all()
    category_list = [c[0] for c in categories if c[0]]  # 过滤空分类
    
    settings_by_category = {}
    for category in category_list:
        # 如果表中有 sort_order 字段则排序，否则按 key 排序
        settings = SystemConfig.query.filter_by(category=category)\
                     .order_by(SystemConfig.key).all()
        # 转换为字典列表，方便模板使用
        settings_by_category[category] = [{
            'key': s.key,
            'value': s.value,
            'description': s.description,
            'is_public': s.is_public
        } for s in settings]
    
    return render_template('config/system_settings.html',
                         settings_by_category=settings_by_category,
                         categories=category_list)

@config_bp.route('/api/system-settings', methods=['GET'])
@login_required
@permission_required('config:view')
def get_system_settings():
    """获取系统设置API"""
    settings = SystemSetting.query.order_by(SystemSetting.category, SystemSetting.sort_order).all()
    return jsonify([s.to_dict() for s in settings])



@config_bp.route('/api/system-settings/add', methods=['POST'])
@login_required
@permission_required('config:edit')
def add_system_setting():
    """添加系统设置项API"""
    try:
        if not current_user.is_admin:
            return jsonify({
                'success': False,
                'message': '权限不足，只有管理员可以添加设置项'
            }), 403
        
        data = request.get_json()
        
        # 验证必填字段
        required_fields = ['key', 'display_name', 'value', 'category', 'data_type']
        for field in required_fields:
            if field not in data or not data[field]:
                return jsonify({
                    'success': False,
                    'message': f'字段 "{field}" 是必填项'
                }), 400
        
        # 检查key是否已存在
        existing_setting = SystemSetting.query.filter_by(key=data['key']).first()
        if existing_setting:
            return jsonify({
                'success': False,
                'message': f'设置键名 "{data["key"]}" 已存在'
            }), 400
        
        # 创建新的设置项
        new_setting = SystemSetting(
            key=data['key'],
            value=data['value'],
            data_type=data['data_type'],
            category=data['category'],
            display_name=data['display_name'],
            description=data.get('description', ''),
            options=json.dumps(data.get('options', [])) if data.get('options') else None,
            is_encrypted=data.get('is_encrypted', False),
            is_required=data.get('is_required', True),
            sort_order=data.get('sort_order', 0)
        )
        
        db.session.add(new_setting)
        db.session.commit()

        log_audit('create', 'system_setting', new_setting.id,
                  f'添加系统设置项: {data["key"]}',
                  details={'key': data['key'], 'category': data['category'], 'data_type': data['data_type']})

        return jsonify({
            'success': True,
            'message': '设置项添加成功',
            'setting_id': new_setting.id
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'添加失败: {str(e)}'
        }), 500

#==============

@config_bp.route('/global-settings')
@login_required
@permission_required('config:view')
def global_settings():
    categories = db.session.query(GlobalParameter.category).distinct().all()
    category_list = [c[0] for c in categories]
    
    params_by_category = {}
    for category in category_list:
        params = GlobalParameter.query.filter_by(category=category, enabled=True).all()
        params_by_category[category] = [p.to_dict() for p in params]
    
    return render_template('config/global_settings.html',
                         params_by_category=params_by_category,
                         categories=category_list)



# -------------------- 更新参数 --------------------
@config_bp.route('/api/global-parameters/update', methods=['POST'])
@login_required
@permission_required('config:edit')
def update_params():
    """批量更新全局参数"""
    try:
        data = request.get_json()
        if not data or 'params' not in data:
            return jsonify({'success': False, 'message': '无效的请求数据'}), 400

        params = data['params']
        category = data.get('category')

        updated_count = 0
        for param_id, new_value in params.items():
            param = GlobalParameter.query.get(param_id)
            if param:
                param.value = str(new_value)
                db.session.add(param)
                updated_count += 1

        db.session.commit()

        log_audit('update', 'global_parameter', 0,
                  f"批量更新 {updated_count} 个全局参数",
                  details={'count': updated_count, 'category': category})

        return jsonify({
            'success': True,
            'message': f'成功更新 {updated_count} 个参数',
            'stats': {
                'enabled_count': GlobalParameter.query.filter_by(enabled=True).count()
            }
        })
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"更新参数失败: {str(e)}")
        return jsonify({'success': False, 'message': f'更新失败: {str(e)}'}), 500

# -------------------- 导出配置 --------------------
@config_bp.route('/api/global-parameters/export', methods=['GET'])
@login_required
@permission_required('config:view')
def export_params():
    """导出所有参数为 JSON"""
    try:
        params = GlobalParameter.query.all()
        data = [{
            'name': p.name,
            'value': p.value,
            'data_type': p.data_type,
            'category': p.category,
            'description': p.description,
            'default_value': p.default_value,
            'min_value': p.min_value,
            'max_value': p.max_value,
            'unit': p.unit,
            'enabled': p.enabled
        } for p in params]
        return jsonify({'success': True, 'data': data})
    except Exception as e:
        current_app.logger.error(f"导出失败: {str(e)}")
        return jsonify({'success': False, 'message': f'导出失败: {str(e)}'}), 500

# -------------------- 导入配置 --------------------
@config_bp.route('/api/global-parameters/import', methods=['POST'])
@login_required
@permission_required('config:edit')
def import_params():
    """导入配置 JSON"""
    try:
        data = request.get_json()
        if not data or 'config' not in data:
            return jsonify({'success': False, 'message': '无效的请求数据'}), 400

        config_list = data['config']
        overwrite = data.get('overwrite', True)

        imported = 0
        for item in config_list:
            existing = GlobalParameter.query.filter_by(name=item['name']).first()
            if existing:
                if overwrite:
                    for key, value in item.items():
                        if hasattr(existing, key):
                            setattr(existing, key, value)
                    db.session.add(existing)
                    imported += 1
            else:
                new_param = GlobalParameter(**item)
                db.session.add(new_param)
                imported += 1

        db.session.commit()

        log_audit('create', 'global_parameter', 0,
                  f"导入 {imported} 个全局参数",
                  details={'imported_count': imported, 'overwrite': overwrite})

        return jsonify({
            'success': True,
            'message': f'成功导入 {imported} 个参数',
            'stats': {
                'enabled_count': GlobalParameter.query.filter_by(enabled=True).count()
            }
        })
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"导入失败: {str(e)}")
        return jsonify({'success': False, 'message': f'导入失败: {str(e)}'}), 500


@config_bp.route('/api/global-parameters/initialize-defaults', methods=['POST'])
@login_required
@permission_required('system:admin')
def initialize_default_parameters():
    """初始化默认参数"""
    try:
        if not current_user.is_admin:
            return jsonify({
                'success': False,
                'message': '权限不足，只有管理员可以初始化默认参数'
            }), 403
        
        # 这里可以定义默认参数
        default_params = [
            {
                'name': '系统名称',
                'value': '网络资产管理系统',
                'data_type': 'string',
                'category': 'system',
                'description': '系统显示名称',
                'default_value': '网络资产管理系统'
            },
            {
                'name': '分页大小',
                'value': '20',
                'data_type': 'integer',
                'category': 'ui',
                'description': '列表分页每页显示数量',
                'default_value': '20',
                'min_value': '5',
                'max_value': '100'
            },
            # 添加更多默认参数...
        ]
        
        initialized_count = 0
        
        for param_data in default_params:
            # 检查参数是否已存在
            existing_param = GlobalParameter.query.filter_by(name=param_data['name']).first()
            
            if not existing_param:
                new_param = GlobalParameter(**param_data)
                db.session.add(new_param)
                initialized_count += 1
        
        db.session.commit()

        log_audit('create', 'global_parameter', 0,
                  f"初始化 {initialized_count} 个默认全局参数",
                  details={'initialized_count': initialized_count})

        return jsonify({
            'success': True,
            'message': f'初始化完成，添加了 {initialized_count} 个默认参数'
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'初始化失败: {str(e)}'
        }), 500

@config_bp.route('/backup-restore')
@login_required
@permission_required('config:view')
def backup_restore():
    """备份与恢复页面"""
    backups = BackupConfig.query.order_by(BackupConfig.created_at.desc()).all()
    return render_template('config/backup_restore.html', backups=backups)
@config_bp.route('/api/backup-configs/<int:config_id>', methods=['GET'])
@login_required
@permission_required('config:view')
def get_backup_config(config_id):
    """获取单个备份配置"""
    config = BackupConfig.query.get_or_404(config_id)
    return jsonify(config.to_dict())


@config_bp.route('/api/backup-configs/quick-backup', methods=['POST'])
@login_required
@permission_required('system:admin')
def quick_backup():
    """快速备份"""
    # 查找默认配置或创建一个快速备份
    default_config = BackupConfig.query.filter_by(name='快速备份').first()
    
    if not default_config:
        default_config = BackupConfig(
            name='快速备份',
            backup_type='full',
            schedule_type='manual',
            schedule_config=json.dumps({}),
            retention_days=7,
            include_database=True,
            include_files=True,
            include_logs=True,
            storage_path='/backups/quick/',
            storage_type='local',
            storage_config=json.dumps({}),
            enabled=True
        )
        db.session.add(default_config)
        db.session.commit()
    
    # 执行备份
    default_config.last_backup_at = datetime.utcnow()
    default_config.last_backup_status = 'running'
    db.session.commit()
    
    # 创建备份任务记录
    backup_task = BackupTask(
        config_id=default_config.id,
        task_id=str(uuid.uuid4()),
        status='running',
        start_time=datetime.utcnow()
    )
    db.session.add(backup_task)
    db.session.commit()
    
    # TODO: 异步执行备份任务
    # background_tasks.add_task(perform_backup, default_config.id, backup_task.task_id)
    
    log_audit('execute', 'quick_backup', default_config.id, "执行快速备份")
    
    return jsonify({
        'success': True, 
        'message': '快速备份已启动',
        'task_id': backup_task.task_id
    })

@config_bp.route('/api/backup-files', methods=['GET'])
@login_required
@permission_required('config:view')
def get_backup_files():
    """获取备份文件列表"""
    backup_dir = current_app.config.get('BACKUP_DIR', '/backups')
    
    if not os.path.exists(backup_dir):
        return jsonify({'success': True, 'files': []})
    
    files = []
    for filename in os.listdir(backup_dir):
        filepath = os.path.join(backup_dir, filename)
        if os.path.isfile(filepath) and filename.endswith(('.zip', '.tar', '.gz', '.backup')):
            stat = os.stat(filepath)
            files.append({
                'name': filename,
                'path': filename,
                'size': format_file_size(stat.st_size),
                'modified': datetime.fromtimestamp(stat.st_mtime).isoformat()
            })
    
    return jsonify({'success': True, 'files': files})

@config_bp.route('/api/backup-files/<path:filepath>/info', methods=['GET'])
@login_required
@permission_required('config:view')
def get_backup_file_info(filepath):
    """获取备份文件信息（限制在 BACKUP_DIR 内，防止路径遍历读取任意文件）"""
    backup_dir = os.path.abspath(current_app.config.get('BACKUP_DIR', '/backups'))
    candidate = os.path.normpath(os.path.join(backup_dir, filepath))
    if candidate != backup_dir and not candidate.startswith(backup_dir + os.sep):
        return jsonify({'success': False, 'message': '非法文件路径'}), 400
    if not os.path.isfile(candidate):
        return jsonify({'success': False, 'message': '文件不存在'}), 404

    try:
        stat = os.stat(candidate)

        # 尝试从文件名解析信息
        filename = os.path.basename(candidate)
        backup_type = 'full'
        if 'incremental' in filename.lower():
            backup_type = 'incremental'
        elif 'differential' in filename.lower():
            backup_type = 'differential'
        
        # 简单的内容判断
        contents = []
        if 'database' in filename.lower():
            contents.append('database')
        if 'files' in filename.lower():
            contents.append('files')
        if 'logs' in filename.lower():
            contents.append('logs')
        
        return jsonify({
            'success': True,
            'name': filename,
            'size': format_file_size(stat.st_size),
            'created_at': datetime.fromtimestamp(stat.st_ctime).strftime('%Y-%m-%d %H:%M:%S'),
            'backup_type': backup_type,
            'contents': contents
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@config_bp.route('/api/backup-history', methods=['GET'])
@login_required
@permission_required('config:view')
def get_backup_history():
    """获取备份历史"""
    # 这里应该从数据库获取备份历史记录
    # 暂时返回模拟数据
    history = []
    
    for config in BackupConfig.query.all():
        if config.last_backup_at:
            history.append({
                'id': config.id,
                'name': f"{config.name}备份",
                'backup_type': config.backup_type,
                'config_name': config.name,
                'start_time': config.last_backup_at.strftime('%Y-%m-%d %H:%M:%S'),
                'end_time': config.last_backup_at.strftime('%Y-%m-%d %H:%M:%S'),
                'size': '1.2 GB',
                'status': config.last_backup_status or 'unknown'
            })
    
    return jsonify({'success': True, 'history': history})

@config_bp.route('/api/backup-history/recent', methods=['GET'])
@login_required
@permission_required('config:view')
def get_recent_backups():
    """获取最近备份"""
    # 这里应该从数据库获取最近的备份记录
    # 暂时返回模拟数据
    backups = []
    
    for i, config in enumerate(BackupConfig.query.all()[:5]):
        if config.last_backup_at:
            backups.append({
                'id': config.id,
                'name': f"{config.name}备份",
                'start_time': config.last_backup_at.strftime('%Y-%m-%d %H:%M:%S'),
                'size': f"{i+1}.{i} GB",
                'status': config.last_backup_status or 'success'
            })
    
    return jsonify({'success': True, 'backups': backups})


@config_bp.route('/api/restore-history', methods=['GET'])
@login_required
@permission_required('config:view')
def get_restore_history():
    """获取恢复历史"""
    # 这里应该从数据库获取恢复历史记录
    # 暂时返回模拟数据
    history = [
        {
            'backup_name': '完整备份_20240101',
            'start_time': '2024-01-02 10:30:00',
            'status': 'success',
            'strategy': '合并恢复'
        }
    ]
    
    return jsonify({'success': True, 'history': history})

# 辅助函数
def format_file_size(size):
    """格式化文件大小"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0:
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} PB"

# ========== 监控配置 ==========

@config_bp.route('/monitoring-templates')
@login_required
@permission_required('config:view')
def monitoring_templates():
    """监控模板页面"""
    templates = MonitoringTemplate.query.order_by(MonitoringTemplate.name).all()
    return render_template('config/monitoring_templates.html', templates=templates)

@config_bp.route('/api/monitoring-templates', methods=['GET'])
@login_required
@permission_required('config:view')
def get_monitoring_templates():
    """获取监控模板"""
    templates = MonitoringTemplate.query.all()
    return jsonify([t.to_dict() for t in templates])

@config_bp.route('/api/monitoring-templates', methods=['POST'])
@login_required
@permission_required('config:edit')
def create_monitoring_template():
    """创建监控模板"""
    data = request.get_json()
    
    template = MonitoringTemplate(
        name=data.get('name'),
        description=data.get('description'),
        device_type=data.get('device_type'),
        vendor=data.get('vendor'),
        model=data.get('model'),
        monitoring_items=json.dumps(data.get('monitoring_items', [])),
        threshold_config=json.dumps(data.get('threshold_config', {})),
        polling_interval=data.get('polling_interval', 300),
        timeout=data.get('timeout', 30),
        enabled=data.get('enabled', True),
        is_default=data.get('is_default', False)
    )
    
    db.session.add(template)
    db.session.commit()
    
    log_audit('create', 'monitoring_template', template.id, 
              f"创建监控模板: {template.name}")
    
    return jsonify({'success': True, 'message': '监控模板已创建', 'id': template.id})

@config_bp.route('/collection-settings')
@login_required
@permission_required('config:view')
def collection_settings():
    """采集设置页面"""
    settings = CollectionSetting.query.order_by(CollectionSetting.name).all()
    return render_template('config/collection_settings.html', settings=settings)

@config_bp.route('/api/collection-settings', methods=['GET'])
@login_required
@permission_required('config:view')
def get_collection_settings():
    """获取采集设置"""
    settings = CollectionSetting.query.all()
    return jsonify([s.to_dict() for s in settings])

# 获取单个采集设置
@config_bp.route('/api/collection-settings/<int:setting_id>', methods=['GET'])
@login_required
@permission_required('config:view')
def get_collection_setting(setting_id):
    """获取单个采集设置"""
    setting = CollectionSetting.query.get_or_404(setting_id)
    return jsonify(setting.to_dict())

# 创建采集设置
@config_bp.route('/api/collection-settings', methods=['POST'])
@login_required
@permission_required('config:edit')
def create_collection_setting():
    """创建采集设置"""
    data = request.get_json()
    
    # 验证必要字段
    if not data.get('name') or not data.get('collection_type'):
        return jsonify({'message': '名称和采集类型是必填项'}), 400
    
    setting = CollectionSetting(
        name=data['name'],
        collection_type=data['collection_type'],
        protocol=data.get('protocol'),
        port=data.get('port'),
        timeout=data.get('timeout', 30),
        retries=data.get('retries', 3),
        polling_interval=data.get('polling_interval', 300),
        bulk_collection=data.get('bulk_collection', False),
        max_concurrent=data.get('max_concurrent', 10),
        data_retention_days=data.get('data_retention_days', 30),
        compression_enabled=data.get('compression_enabled', True),
        enabled=data.get('enabled', True),
        config=json.dumps(data.get('config', {}))
    )
    
    db.session.add(setting)
    db.session.commit()

    log_audit('create', 'collection_setting', setting.id,
              f"创建采集设置: {setting.name}",
              details={'name': setting.name, 'collection_type': setting.collection_type})

    return jsonify(setting.to_dict()), 201

# 更新采集设置
@config_bp.route('/api/collection-settings/<int:setting_id>', methods=['PUT'])
@login_required
@permission_required('config:edit')
def update_collection_setting(setting_id):
    """更新采集设置"""
    setting = CollectionSetting.query.get_or_404(setting_id)
    data = request.get_json()
    
    # 更新字段
    setting.name = data.get('name', setting.name)
    setting.collection_type = data.get('collection_type', setting.collection_type)
    setting.protocol = data.get('protocol', setting.protocol)
    setting.port = data.get('port', setting.port)
    setting.timeout = data.get('timeout', setting.timeout)
    setting.retries = data.get('retries', setting.retries)
    setting.polling_interval = data.get('polling_interval', setting.polling_interval)
    setting.bulk_collection = data.get('bulk_collection', setting.bulk_collection)
    setting.max_concurrent = data.get('max_concurrent', setting.max_concurrent)
    setting.data_retention_days = data.get('data_retention_days', setting.data_retention_days)
    setting.compression_enabled = data.get('compression_enabled', setting.compression_enabled)
    setting.enabled = data.get('enabled', setting.enabled)
    setting.config = json.dumps(data.get('config', {}))
    setting.updated_at = datetime.utcnow()
    
    db.session.commit()

    log_audit('update', 'collection_setting', setting.id,
              f"更新采集设置: {setting.name}",
              details={'name': setting.name, 'collection_type': setting.collection_type})

    return jsonify(setting.to_dict())

# 删除采集设置
@config_bp.route('/api/collection-settings/<int:setting_id>', methods=['DELETE'])
@login_required
@permission_required('config:edit')
def delete_collection_setting(setting_id):
    """删除采集设置"""
    setting = CollectionSetting.query.get_or_404(setting_id)

    log_audit('delete', 'collection_setting', setting.id,
              f"删除采集设置: {setting.name}",
              details={'name': setting.name, 'collection_type': setting.collection_type})

    db.session.delete(setting)
    db.session.commit()

    return jsonify({'message': '采集设置已删除'}), 200




@config_bp.route('/threshold-profiles')
@login_required
@permission_required('config:view')
def threshold_profiles():
    """阈值配置页面"""
    profiles = ThresholdProfile.query.order_by(ThresholdProfile.metric_type).all()
    return render_template('config/threshold_profiles.html', profiles=profiles)

@config_bp.route('/api/threshold-profiles', methods=['GET'])
@login_required
@permission_required('config:view')
def get_threshold_profiles():
    """获取阈值配置"""
    profiles = ThresholdProfile.query.all()
    return jsonify([p.to_dict() for p in profiles])

# 获取单个阈值配置
@config_bp.route('/api/threshold-profiles/<int:profile_id>', methods=['GET'])
@login_required
@permission_required('config:view')
def get_threshold_profile(profile_id):
    """获取单个阈值配置"""
    profile = ThresholdProfile.query.get_or_404(profile_id)
    return jsonify(profile.to_dict())

# 创建阈值配置
@config_bp.route('/api/threshold-profiles', methods=['POST'])
@login_required
@permission_required('config:edit')
def create_threshold_profile():
    """创建阈值配置"""
    data = request.get_json()
    
    # 验证必要字段
    if not data.get('name') or not data.get('metric_type'):
        return jsonify({'message': '名称和指标类型是必填项'}), 400
    
    # 如果设置为默认配置，需要检查是否已存在同类型的默认配置
    if data.get('is_default'):
        existing_default = ThresholdProfile.query.filter_by(
            metric_type=data['metric_type'],
            is_default=True
        ).first()
        
        if existing_default:
            return jsonify({'message': f'该指标类型已存在默认配置: {existing_default.name}'}), 400
    
    profile = ThresholdProfile(
        name=data['name'],
        description=data.get('description'),
        metric_type=data['metric_type'],
        warning_threshold=data.get('warning_threshold'),
        critical_threshold=data.get('critical_threshold'),
        recovery_threshold=data.get('recovery_threshold'),
        duration=data.get('duration', 300),
        condition_type=data.get('condition_type', 'greater'),
        unit=data.get('unit'),
        enabled=data.get('enabled', True),
        is_default=data.get('is_default', False),
        apply_to_all=data.get('apply_to_all', False)
    )
    
    db.session.add(profile)
    db.session.commit()

    log_audit('create', 'threshold_profile', profile.id,
              f"创建阈值配置: {profile.name}",
              details={'name': profile.name, 'metric_type': profile.metric_type})

    return jsonify(profile.to_dict()), 201

# 更新阈值配置
@config_bp.route('/api/threshold-profiles/<int:profile_id>', methods=['PUT'])
@login_required
@permission_required('config:edit')
def update_threshold_profile(profile_id):
    """更新阈值配置"""
    profile = ThresholdProfile.query.get_or_404(profile_id)
    data = request.get_json()
    
    # 如果修改为默认配置，需要检查是否已存在同类型的默认配置
    if data.get('is_default') and (not profile.is_default or profile.metric_type != data.get('metric_type', profile.metric_type)):
        existing_default = ThresholdProfile.query.filter(
            ThresholdProfile.id != profile_id,
            ThresholdProfile.metric_type == data.get('metric_type', profile.metric_type),
            ThresholdProfile.is_default == True
        ).first()
        
        if existing_default:
            return jsonify({'message': f'该指标类型已存在默认配置: {existing_default.name}'}), 400
    
    # 更新字段
    profile.name = data.get('name', profile.name)
    profile.description = data.get('description', profile.description)
    profile.metric_type = data.get('metric_type', profile.metric_type)
    profile.warning_threshold = data.get('warning_threshold', profile.warning_threshold)
    profile.critical_threshold = data.get('critical_threshold', profile.critical_threshold)
    profile.recovery_threshold = data.get('recovery_threshold', profile.recovery_threshold)
    profile.duration = data.get('duration', profile.duration)
    profile.condition_type = data.get('condition_type', profile.condition_type)
    profile.unit = data.get('unit', profile.unit)
    profile.enabled = data.get('enabled', profile.enabled)
    profile.is_default = data.get('is_default', profile.is_default)
    profile.apply_to_all = data.get('apply_to_all', profile.apply_to_all)
    profile.updated_at = datetime.utcnow()
    
    db.session.commit()

    log_audit('update', 'threshold_profile', profile.id,
              f"更新阈值配置: {profile.name}",
              details={'name': profile.name, 'metric_type': profile.metric_type})

    return jsonify(profile.to_dict())

# 删除阈值配置
@config_bp.route('/api/threshold-profiles/<int:profile_id>', methods=['DELETE'])
@login_required
@permission_required('config:edit')
def delete_threshold_profile(profile_id):
    """删除阈值配置"""
    profile = ThresholdProfile.query.get_or_404(profile_id)

    log_audit('delete', 'threshold_profile', profile.id,
              f"删除阈值配置: {profile.name}",
              details={'name': profile.name, 'metric_type': profile.metric_type})

    db.session.delete(profile)
    db.session.commit()

    return jsonify({'message': '阈值配置已删除'}), 200


#====================-=---=====================

@config_bp.route('/api/monitoring-templates/<int:template_id>', methods=['GET'])
@login_required
@permission_required('config:view')
def get_monitoring_template(template_id):
    """获取单个监控模板"""
    template = MonitoringTemplate.query.get_or_404(template_id)
    return jsonify(template.to_dict())

@config_bp.route('/api/monitoring-templates/<int:template_id>', methods=['PUT'])
@login_required
@permission_required('config:edit')
def update_monitoring_template(template_id):
    """更新监控模板"""
    template = MonitoringTemplate.query.get_or_404(template_id)
    data = request.get_json()
    
    for key in ['name', 'description', 'device_type', 'vendor', 'model',
                'polling_interval', 'timeout', 'enabled', 'is_default']:
        if key in data:
            setattr(template, key, data[key])
    
    if 'monitoring_items' in data:
        template.monitoring_items = json.dumps(data['monitoring_items'])
    
    if 'threshold_config' in data:
        template.threshold_config = json.dumps(data['threshold_config'])
    
    template.updated_at = datetime.utcnow()
    db.session.commit()
    
    log_audit('update', 'monitoring_template', template.id, 
              f"更新监控模板: {template.name}")
    
    return jsonify({'success': True, 'message': '监控模板已更新'})

@config_bp.route('/api/monitoring-templates/<int:template_id>', methods=['DELETE'])
@login_required
@permission_required('config:edit')
def delete_monitoring_template(template_id):
    """删除监控模板"""
    template = MonitoringTemplate.query.get_or_404(template_id)
    
    db.session.delete(template)
    db.session.commit()
    
    log_audit('delete', 'monitoring_template', template_id, 
              f"删除监控模板: {template.name}")
    
    return jsonify({'success': True, 'message': '监控模板已删除'})

@config_bp.route('/api/monitoring-templates/<int:template_id>/apply', methods=['POST'])
@login_required
@permission_required('config:edit')
def apply_monitoring_template(template_id):
    """应用监控模板到设备"""
    template = MonitoringTemplate.query.get_or_404(template_id)
    data = request.get_json()
    device_ids = data.get('device_ids', [])
    override = data.get('override', False)
    
    if not device_ids:
        return jsonify({'success': False, 'message': '请选择要应用模板的设备'}), 400
    
    # 这里需要实现将模板应用到设备的逻辑
    # 例如，更新设备的监控配置

    log_audit('execute', 'monitoring_template', template_id,
              f"应用监控模板: {template.name}",
              details={'device_count': len(device_ids), 'override': override, 'device_ids': device_ids})

    return jsonify({
        'success': True,
        'message': f'模板已应用到 {len(device_ids)} 台设备'
    })

@config_bp.route('/api/monitoring-templates/import', methods=['POST'])
@login_required
@permission_required('system:admin')
def import_monitoring_template():
    """导入监控模板"""
    try:
        if not current_user.is_admin:
            return jsonify({
                'success': False,
                'message': '权限不足，只有管理员可以导入模板'
            }), 403
        
        data = request.get_json()
        template_data = data.get('template', {})
        overwrite = data.get('overwrite', False)
        
        # 验证必填字段
        required_fields = ['name', 'monitoring_items']
        for field in required_fields:
            if field not in template_data:
                return jsonify({
                    'success': False,
                    'message': f'模板数据缺少必填字段: {field}'
                }), 400
        
        # 检查是否已存在同名模板
        existing_template = MonitoringTemplate.query.filter_by(
            name=template_data['name']).first()
        
        if existing_template:
            if overwrite:
                # 更新现有模板
                for key in ['description', 'device_type', 'vendor', 'model',
                           'polling_interval', 'timeout', 'enabled', 'is_default']:
                    if key in template_data:
                        setattr(existing_template, key, template_data[key])
                
                if 'monitoring_items' in template_data:
                    existing_template.monitoring_items = json.dumps(
                        template_data['monitoring_items'])
                
                if 'threshold_config' in template_data:
                    existing_template.threshold_config = json.dumps(
                        template_data['threshold_config'])
                
                existing_template.updated_at = datetime.utcnow()
                
                log_audit('update', 'monitoring_template', existing_template.id,
                         f"通过导入更新监控模板: {existing_template.name}")
            else:
                return jsonify({
                    'success': False,
                    'message': f'模板 "{template_data["name"]}" 已存在'
                }), 400
        else:
            # 创建新模板
            new_template = MonitoringTemplate(
                name=template_data['name'],
                description=template_data.get('description'),
                device_type=template_data.get('device_type'),
                vendor=template_data.get('vendor'),
                model=template_data.get('model'),
                monitoring_items=json.dumps(template_data.get('monitoring_items', [])),
                threshold_config=json.dumps(template_data.get('threshold_config', {})),
                polling_interval=template_data.get('polling_interval', 300),
                timeout=template_data.get('timeout', 30),
                enabled=template_data.get('enabled', True),
                is_default=template_data.get('is_default', False)
            )
            db.session.add(new_template)
            
            log_audit('create', 'monitoring_template', new_template.id,
                     f"通过导入创建监控模板: {new_template.name}")

        db.session.commit()

        log_audit('create', 'monitoring_template', 0,
                  f"导入监控模板: {template_data['name']}",
                  details={'overwrite': overwrite, 'template_name': template_data['name']})

        return jsonify({
            'success': True,
            'message': '模板导入成功'
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'导入失败: {str(e)}'
        }), 500




# ========== 告警配置 ==========

@config_bp.route('/alert-config-templates')
@login_required
@permission_required('config:view')
def alert_templates():
    """告警模板页面"""
    templates = AlertConfigTemplate.query.order_by(AlertConfigTemplate.name).all()
    templates_dict = [t.to_dict() for t in templates]  # 转换为字典列表
    return render_template('config/alert_templates.html', templates=templates_dict)

@config_bp.route('/notification-templates')
@login_required
@permission_required('config:view')
def notification_templates():
    """通知模板页面"""
    templates = NotificationTemplate.query.order_by(NotificationTemplate.name).all()
    return render_template('config/notification_templates.html', templates=templates)


@config_bp.route('/escalation-policies')
@login_required
@permission_required('config:view')
def escalation_policies():
    """升级策略页面"""
    policies = EscalationPolicy.query.order_by(EscalationPolicy.name).all()
    return render_template('config/escalation_policies.html', policies=policies)


# ==================== 告警通知设置 ====================

@config_bp.route('/alert-settings')
@login_required
@permission_required('config:view')
def alert_settings():
    """告警通知设置页面"""
    from services.notification_service import get_alert_settings
    settings = get_alert_settings()
    return render_template('config/alert_settings.html', settings=settings)


@config_bp.route('/alert-settings/save', methods=['POST'])
@login_required
@permission_required('config:edit')
def alert_settings_save():
    """保存告警通知设置"""
    from services.notification_service import save_alert_settings
    try:
        settings = {}
        for key in ['smtp_server', 'smtp_port', 'smtp_use_tls', 'smtp_user',
                     'smtp_password', 'smtp_from_addr', 'smtp_from_name',
                     'wechat_webhook_url', 'wechat_proxy',
                     'slack_webhook_url', 'webhook_default_url', 'webhook_default_headers']:
            settings[key] = request.form.get(key, '')
        save_alert_settings(settings)
        log_audit('update', 'alert_settings', 0, '更新告警通知设置', user_id=current_user.id)
        flash('告警通知设置已保存', 'success')
    except Exception as e:
        flash(f'保存失败: {str(e)}', 'danger')
    return redirect(url_for('config.alert_settings'))


@config_bp.route('/alert-settings/test', methods=['POST'])
@login_required
@permission_required('config:edit')
def alert_settings_test():
    """测试发送告警通知"""
    from services.notification_service import send_email, send_wechat, send_slack, send_webhook
    channel = request.form.get('channel', '')
    test_recipient = request.form.get('test_recipient', '')

    title = '【测试通知】告警系统测试消息'
    content = '<h3>告警系统测试</h3><p>这是一条测试消息，用于验证通知渠道配置是否正确。</p><p>发送时间: {}</p>'.format(
        datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    )

    try:
        if channel == 'email':
            if not test_recipient:
                flash('请填写测试接收邮箱', 'danger')
                return redirect(url_for('config.alert_settings'))
            success, msg = send_email(test_recipient, title, content)
        elif channel == 'wechat':
            success, msg = send_wechat([], title, '这是一条来自告警系统的测试消息，用于验证企业微信配置是否正确。')
        elif channel == 'slack':
            success, msg = send_slack([], '#general', '告警系统测试：通知配置验证通过 ✓')
        elif channel == 'webhook':
            success, msg = send_webhook(test_recipient or '', content)
        else:
            flash('请选择测试渠道', 'danger')
            return redirect(url_for('config.alert_settings'))

        if success:
            flash(f'测试发送成功: {msg}', 'success')
        else:
            flash(f'测试发送失败: {msg}', 'danger')
    except Exception as e:
        flash(f'测试发送异常: {str(e)}', 'danger')

    return redirect(url_for('config.alert_settings'))


# ========== 升级策略 API ==========

@config_bp.route('/api/escalation-policies', methods=['GET'])
@login_required
@permission_required('config:view')
def get_escalation_policies():
    """获取所有升级策略"""
    policies = EscalationPolicy.query.order_by(EscalationPolicy.name).all()
    return jsonify([p.to_dict() for p in policies])

@config_bp.route('/api/escalation-policies/<int:policy_id>', methods=['GET'])
@login_required
@permission_required('config:view')
def get_escalation_policy(policy_id):
    """获取单个升级策略"""
    policy = EscalationPolicy.query.get_or_404(policy_id)
    return jsonify({'success': True, 'policy': policy.to_dict()})

@config_bp.route('/api/escalation-policies', methods=['POST'])
@login_required
@permission_required('config:edit')
def create_escalation_policy():
    """创建升级策略"""
    try:
        data = request.get_json()
        
        # 验证必要字段
        required_fields = ['name', 'severity_levels', 'escalation_steps']
        for field in required_fields:
            if field not in data:
                return jsonify({'success': False, 'message': f'缺少必要字段: {field}'}), 400
        
        # 检查名称是否已存在
        existing_policy = EscalationPolicy.query.filter_by(name=data['name']).first()
        if existing_policy:
            return jsonify({'success': False, 'message': f'策略名称"{data["name"]}"已存在'}), 400
        
        # 创建新策略
        policy = EscalationPolicy(
            name=data['name'],
            description=data.get('description', ''),
            severity_levels=json.dumps(data['severity_levels']),
            escalation_steps=json.dumps(data['escalation_steps']),
            repeat_interval=data.get('repeat_interval', 3600),
            max_escalations=data.get('max_escalations', 3),
            notify_on_resolve=data.get('notify_on_resolve', True),
            enabled=data.get('enabled', True)
        )
        
        db.session.add(policy)
        db.session.commit()
        
        log_audit('create', 'escalation_policy', policy.id, f"创建升级策略: {policy.name}")
        
        return jsonify({'success': True, 'message': '升级策略创建成功', 'id': policy.id})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'创建失败: {str(e)}'}), 500

@config_bp.route('/api/escalation-policies/<int:policy_id>', methods=['PUT'])
@login_required
@permission_required('config:edit')
def update_escalation_policy(policy_id):
    """更新升级策略"""
    try:
        policy = EscalationPolicy.query.get_or_404(policy_id)
        data = request.get_json()
        
        # 更新字段
        if 'name' in data and data['name'] != policy.name:
            # 检查新名称是否已存在
            existing_policy = EscalationPolicy.query.filter_by(name=data['name']).first()
            if existing_policy and existing_policy.id != policy_id:
                return jsonify({'success': False, 'message': f'策略名称"{data["name"]}"已存在'}), 400
            policy.name = data['name']
        
        if 'description' in data:
            policy.description = data['description']
        
        if 'severity_levels' in data:
            policy.severity_levels = json.dumps(data['severity_levels'])
        
        if 'escalation_steps' in data:
            policy.escalation_steps = json.dumps(data['escalation_steps'])
        
        if 'repeat_interval' in data:
            policy.repeat_interval = data['repeat_interval']
        
        if 'max_escalations' in data:
            policy.max_escalations = data['max_escalations']
        
        if 'notify_on_resolve' in data:
            policy.notify_on_resolve = data['notify_on_resolve']
        
        if 'enabled' in data:
            policy.enabled = data['enabled']
        
        policy.updated_at = datetime.utcnow()
        db.session.commit()
        
        log_audit('update', 'escalation_policy', policy.id, f"更新升级策略: {policy.name}")
        
        return jsonify({'success': True, 'message': '升级策略更新成功'})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'更新失败: {str(e)}'}), 500

@config_bp.route('/api/escalation-policies/<int:policy_id>/status', methods=['PUT'])
@login_required
@permission_required('config:edit')
def update_escalation_policy_status(policy_id):
    """更新升级策略状态"""
    try:
        policy = EscalationPolicy.query.get_or_404(policy_id)
        data = request.get_json()
        
        if 'enabled' in data:
            policy.enabled = data['enabled']
            policy.updated_at = datetime.utcnow()
            
            db.session.commit()
            
            log_audit('update', 'escalation_policy_status', policy.id, 
                     f"更新升级策略状态: {policy.name} -> {'启用' if policy.enabled else '禁用'}")
            
            return jsonify({'success': True, 'message': '策略状态更新成功'})
        
        return jsonify({'success': False, 'message': '缺少参数'}), 400
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'状态更新失败: {str(e)}'}), 500

@config_bp.route('/api/escalation-policies/<int:policy_id>', methods=['DELETE'])
@login_required
@permission_required('config:edit')
def delete_escalation_policy(policy_id):
    """删除升级策略"""
    try:
        policy = EscalationPolicy.query.get_or_404(policy_id)
        
        db.session.delete(policy)
        db.session.commit()
        
        log_audit('delete', 'escalation_policy', policy_id, f"删除升级策略: {policy.name}")
        
        return jsonify({'success': True, 'message': '升级策略删除成功'})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'删除失败: {str(e)}'}), 500

# ========== 网络配置 ==========


@config_bp.route('/snmp-settings')
@login_required
@permission_required('config:view')
def snmp_settings():
    """SNMP配置页面"""
    settings = SNMPSetting.query.order_by(SNMPSetting.name).all()
    return render_template('config/snmp_settings.html', settings=settings)

@config_bp.route('/api/snmp-settings', methods=['GET'])
@login_required
@permission_required('config:view')
def get_snmp_settings():
    """获取SNMP配置"""
    settings = SNMPSetting.query.all()
    return jsonify([s.to_dict() for s in settings])


@config_bp.route('/api/snmp-settings/<int:setting_id>', methods=['GET'])
@login_required
@permission_required('config:view')
def get_snmp_setting(setting_id):
    """获取单个SNMP配置"""
    setting = SNMPSetting.query.get_or_404(setting_id)
    return jsonify({'success': True, 'config': setting.to_dict()})

@config_bp.route('/api/snmp-settings', methods=['POST'])
@login_required
@permission_required('config:edit')
def create_snmp_setting():
    """创建SNMP配置"""
    try:
        data = request.get_json()
        
        # 验证必要字段
        required_fields = ['name', 'version']
        for field in required_fields:
            if field not in data:
                return jsonify({'success': False, 'message': f'缺少必要字段: {field}'}), 400
        
        # 检查名称是否已存在
        existing_setting = SNMPSetting.query.filter_by(name=data['name']).first()
        if existing_setting:
            return jsonify({'success': False, 'message': f'配置名称"{data["name"]}"已存在'}), 400
        
        # 验证版本特定字段
        if data['version'] in ['v1', 'v2c']:
            if not data.get('community'):
                return jsonify({'success': False, 'message': 'v1/v2c版本需要社区字符串'}), 400
        elif data['version'] == 'v3':
            if not data.get('username'):
                return jsonify({'success': False, 'message': 'v3版本需要用户名'}), 400
            
            # 根据安全级别验证字段
            security_level = data.get('security_level', 'authPriv')
            if security_level in ['authNoPriv', 'authPriv']:
                if not data.get('auth_protocol') or not data.get('auth_password'):
                    return jsonify({'success': False, 'message': '认证级别需要认证协议和密码'}), 400
            if security_level == 'authPriv':
                if not data.get('priv_protocol') or not data.get('priv_password'):
                    return jsonify({'success': False, 'message': '加密级别需要加密协议和密码'}), 400
        
        # 创建新配置
        setting = SNMPSetting(
            name=data['name'],
            version=data['version'],
            community=data.get('community'),
            security_level=data.get('security_level'),
            auth_protocol=data.get('auth_protocol'),
            auth_password=data.get('auth_password'),
            priv_protocol=data.get('priv_protocol'),
            priv_password=data.get('priv_password'),
            username=data.get('username'),
            context_name=data.get('context_name'),
            timeout=data.get('timeout', 5),
            retries=data.get('retries', 3),
            port=data.get('port', 161),
            enabled=data.get('enabled', True)
        )
        
        db.session.add(setting)
        db.session.commit()
        
        log_audit('create', 'snmp_setting', setting.id, f"创建SNMP配置: {setting.name}")
        
        return jsonify({'success': True, 'message': 'SNMP配置创建成功', 'id': setting.id})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'创建失败: {str(e)}'}), 500

@config_bp.route('/api/snmp-settings/<int:setting_id>', methods=['PUT'])
@login_required
@permission_required('config:edit')
def update_snmp_setting(setting_id):
    """更新SNMP配置"""
    try:
        setting = SNMPSetting.query.get_or_404(setting_id)
        data = request.get_json()
        
        # 更新字段
        if 'name' in data and data['name'] != setting.name:
            # 检查新名称是否已存在
            existing_setting = SNMPSetting.query.filter_by(name=data['name']).first()
            if existing_setting and existing_setting.id != setting_id:
                return jsonify({'success': False, 'message': f'配置名称"{data["name"]}"已存在'}), 400
            setting.name = data['name']
        
        if 'version' in data:
            setting.version = data['version']
        
        # 根据版本更新相应字段
        if setting.version in ['v1', 'v2c']:
            setting.community = data.get('community', setting.community)
            # 清空v3特有字段
            setting.security_level = None
            setting.auth_protocol = None
            setting.auth_password = None
            setting.priv_protocol = None
            setting.priv_password = None
            setting.username = None
            setting.context_name = None
        elif setting.version == 'v3':
            setting.username = data.get('username', setting.username)
            setting.security_level = data.get('security_level', setting.security_level)
            setting.auth_protocol = data.get('auth_protocol', setting.auth_protocol)
            setting.auth_password = data.get('auth_password', setting.auth_password)
            setting.priv_protocol = data.get('priv_protocol', setting.priv_protocol)
            setting.priv_password = data.get('priv_password', setting.priv_password)
            setting.context_name = data.get('context_name', setting.context_name)
            setting.community = None
        
        # 更新通用字段
        setting.timeout = data.get('timeout', setting.timeout)
        setting.retries = data.get('retries', setting.retries)
        setting.port = data.get('port', setting.port)
        
        if 'enabled' in data:
            setting.enabled = data['enabled']
        
        setting.updated_at = datetime.utcnow()
        db.session.commit()
        
        log_audit('update', 'snmp_setting', setting.id, f"更新SNMP配置: {setting.name}")
        
        return jsonify({'success': True, 'message': 'SNMP配置更新成功'})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'更新失败: {str(e)}'}), 500

@config_bp.route('/api/snmp-settings/<int:setting_id>/status', methods=['PUT'])
@login_required
@permission_required('config:edit')
def update_snmp_setting_status(setting_id):
    """更新SNMP配置状态"""
    try:
        setting = SNMPSetting.query.get_or_404(setting_id)
        data = request.get_json()
        
        if 'enabled' in data:
            setting.enabled = data['enabled']
            setting.updated_at = datetime.utcnow()
            
            db.session.commit()
            
            log_audit('update', 'snmp_setting_status', setting.id, 
                     f"更新SNMP配置状态: {setting.name} -> {'启用' if setting.enabled else '禁用'}")
            
            return jsonify({'success': True, 'message': '配置状态更新成功'})
        
        return jsonify({'success': False, 'message': '缺少参数'}), 400
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'状态更新失败: {str(e)}'}), 500

@config_bp.route('/api/snmp-settings/<int:setting_id>', methods=['DELETE'])
@login_required
@permission_required('config:edit')
def delete_snmp_setting(setting_id):
    """删除SNMP配置"""
    try:
        setting = SNMPSetting.query.get_or_404(setting_id)
        
        # 记录审计日志
        log_audit('delete', 'snmp_setting', setting_id, f"删除SNMP配置: {setting.name}")
        
        db.session.delete(setting)
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'SNMP配置删除成功'})
        
    except Exception as e:
        db.session.rollback()
        print(f"删除SNMP配置异常: {str(e)}")  # 查看具体错误
        return jsonify({'success': False, 'message': f'删除失败: {str(e)}'}), 500

from concurrent.futures import ThreadPoolExecutor, TimeoutError
import time

@config_bp.route('/api/snmp-settings/test', methods=['POST'])
@login_required
@permission_required('config:edit')
def test_snmp_connection():
    try:
        data = request.get_json()
        host = data.get('host')
        config = data.get('config', {})

        if not host:
            return jsonify({'success': False, 'message': '请提供测试主机地址'}), 400

        version = config.get('version', 'v2c')
        if version == 'v3':
            return jsonify({'success': False, 'message': '暂不支持SNMP v3测试'})

        timeout = min(config.get('timeout', 3), 5)
        retries = min(config.get('retries', 1), 2)
        community = config.get('community', 'public')

        from utils.utils import snmp_get_device_info

        def _snmp_query():
            # 调用你的同步函数
            return snmp_get_device_info(
                ip=host,
                community=community,
                version=version[1:],  # 'v2c' -> '2c'
                timeout=timeout,
                retries=retries
            )

        # 计算最大等待时间（理论最大 + 2秒缓冲）
        max_wait = timeout * (retries + 1) + 2  # 例如 3*2+2 = 8秒

        # 使用线程池执行，并设置超时
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_snmp_query)
            try:
                success, device_info = future.result(timeout=max_wait)
            except TimeoutError:
                print(f"[SNMP测试] 超时: {host}")
                return jsonify({'success': False, 'message': f'连接 {host} 超时（{max_wait}秒）'})
            except Exception as e:
                print(f"[SNMP测试] 异常: {host} - {str(e)}")
                return jsonify({'success': False, 'message': f'测试异常: {str(e)}'})

        if success and device_info:
            return jsonify({
                'success': True,
                'message': f'成功连接到 {host}',
                'sys_info': device_info.get('sys_descr', '')[:200]
            })
        else:
            return jsonify({
                'success': False,
                'message': f'无法连接到 {host}，请检查网络或SNMP配置'
            })

    except Exception as e:
        return jsonify({'success': False, 'message': f'测试失败: {str(e)}'}), 500

#=================---++++++++++++++++++++++++

@config_bp.route('/credential-management')
@login_required
@permission_required('config:view')
def credential_management():
    """凭据管理页面"""
    credentials = Credential.query.order_by(Credential.name).all()
    return render_template('config/credential_management.html', credentials=credentials)

@config_bp.route('/api/credentials', methods=['GET'])
@login_required
@permission_required('config:view')
def get_credentials():
    """获取凭据"""
    credentials = Credential.query.all()
    # 安全考虑，不返回实际密码
    cred_dicts = []
    for cred in credentials:
        cred_dict = cred.to_dict()
        cred_dicts.append(cred_dict)
    return jsonify(cred_dicts)



def get_cipher():
    """获取加密器实例"""
    # 使用应用密钥派生加密密钥
    secret_key = current_app.config.get('SECRET_KEY', 'default-secret-key-change-in-production')
    
    # 使用PBKDF2派生固定长度的密钥
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b'credential_salt',  # 生产环境中应该使用随机salt并存储
        iterations=100000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(secret_key.encode()))
    return Fernet(key)

def encrypt_data(data):
    """加密数据"""
    if not data:
        return None
    cipher = get_cipher()
    return cipher.encrypt(data.encode()).decode()

def decrypt_data(encrypted_data):
    """解密数据"""
    if not encrypted_data:
        return None
    try:
        cipher = get_cipher()
        return cipher.decrypt(encrypted_data.encode()).decode()
    except Exception as e:
        current_app.logger.error(f"解密失败: {str(e)}")
        return None

@config_bp.route('/api/credentials', methods=['POST'])
@login_required
@permission_required('config:edit')
def add_credential():
    """添加新凭据"""
    try:
        data = request.get_json()
        
        # 验证必填字段
        required_fields = ['name', 'credential_type', 'username']
        for field in required_fields:
            if field not in data or not data[field]:
                return jsonify({'error': f'字段 "{field}" 是必填项'}), 400
        
        # 检查凭据名称是否已存在
        existing_credential = Credential.query.filter_by(name=data['name']).first()
        if existing_credential:
            return jsonify({'error': '凭据名称已存在'}), 400
        
        # 根据凭据类型验证密码字段
        credential_type = data['credential_type']
        
        # 密码类型需要密码
        if credential_type == 'password':
            if 'password' not in data or not data['password']:
                return jsonify({'error': '密码是必填项'}), 400
        
        # 创建新凭据
        new_credential = Credential(
            name=data['name'],
            username=data['username'],
            credential_type=credential_type,
            protocol=data.get('protocol'),
            port=data.get('port'),
            domain=data.get('domain'),
            description=data.get('description'),
            enabled=data.get('enabled', True)
        )
        
        # 处理密码字段
        if credential_type == 'password' and data.get('password'):
            new_credential.password = encrypt_data(data['password'])
        elif credential_type == 'ssh_key':
            if data.get('private_key'):
                new_credential.private_key = encrypt_data(data['private_key'])
            if data.get('passphrase'):
                new_credential.passphrase = encrypt_data(data['passphrase'])
            # SSH密钥也可以有密码
            if data.get('password'):
                new_credential.password = encrypt_data(data['password'])
        
        # 处理标签
        if 'tags' in data:
            if isinstance(data['tags'], str):
                try:
                    tags_list = json.loads(data['tags'])
                    new_credential.tags = json.dumps(tags_list, ensure_ascii=False)
                except json.JSONDecodeError:
                    new_credential.tags = json.dumps([], ensure_ascii=False)
            elif isinstance(data['tags'], list):
                new_credential.tags = json.dumps(data['tags'], ensure_ascii=False)
            else:
                new_credential.tags = json.dumps([], ensure_ascii=False)
        
        # 保存到数据库
        db.session.add(new_credential)
        db.session.commit()

        log_audit('create', 'credential', new_credential.id,
                  f"创建凭据: {new_credential.name}",
                  details={'name': new_credential.name, 'type': new_credential.credential_type})

        return jsonify({
            'success': True,
            'message': '凭据添加成功',
            'credential': new_credential.to_dict()
        }), 201

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"添加凭据失败: {str(e)}")
        return jsonify({'error': '服务器内部错误', 'details': str(e)}), 500

@config_bp.route('/api/credentials/<int:credential_id>', methods=['PUT'])
@login_required
@permission_required('config:edit')
def update_credential(credential_id):
    """更新凭据"""
    try:
        credential = Credential.query.get_or_404(credential_id)
        data = request.get_json()
        
        # 验证必填字段
        if 'name' in data and (not data['name'] or data['name'].strip() == ''):
            return jsonify({'error': '凭据名称不能为空'}), 400
        
        if 'username' in data and (not data['username'] or data['username'].strip() == ''):
            return jsonify({'error': '用户名不能为空'}), 400
        
        # 检查凭据名称是否已被其他凭据使用
        if 'name' in data and data['name'] != credential.name:
            existing_credential = Credential.query.filter_by(name=data['name']).first()
            if existing_credential and existing_credential.id != credential_id:
                return jsonify({'error': '凭据名称已存在'}), 400
        
        # 更新字段
        if 'name' in data:
            credential.name = data['name']
        
        if 'username' in data:
            credential.username = data['username']
        
        if 'credential_type' in data:
            credential.credential_type = data['credential_type']
        
        if 'protocol' in data:
            credential.protocol = data['protocol']
        
        if 'port' in data:
            credential.port = data['port']
        
        if 'domain' in data:
            credential.domain = data['domain']
        
        if 'description' in data:
            credential.description = data['description']
        
        if 'enabled' in data:
            credential.enabled = data['enabled']
        
        # 处理密码字段 - 只有当提供了新密码时才更新
        if 'password' in data:
            # 前端发送空字符串表示不更新，发送非空字符串表示更新
            if data['password'] != '':
                credential.password = encrypt_data(data['password'])
        
        # 处理SSH密钥字段
        if credential.credential_type == 'ssh_key':
            if 'private_key' in data and data['private_key'] != '':
                credential.private_key = encrypt_data(data['private_key'])
            
            if 'passphrase' in data and data['passphrase'] != '':
                credential.passphrase = encrypt_data(data['passphrase'])
        
        # 处理标签
        if 'tags' in data:
            if isinstance(data['tags'], str):
                try:
                    tags_list = json.loads(data['tags'])
                    credential.tags = json.dumps(tags_list, ensure_ascii=False)
                except json.JSONDecodeError:
                    credential.tags = json.dumps([], ensure_ascii=False)
            elif isinstance(data['tags'], list):
                credential.tags = json.dumps(data['tags'], ensure_ascii=False)
        
        # 更新更新时间
        credential.updated_at = datetime.utcnow()
        
        # 保存到数据库
        db.session.commit()

        log_audit('update', 'credential', credential.id,
                  f"更新凭据: {credential.name}",
                  details={'name': credential.name, 'type': credential.credential_type})

        return jsonify({
            'success': True,
            'message': '凭据更新成功',
            'credential': credential.to_dict()
        }), 200

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"更新凭据失败: {str(e)}")
        return jsonify({'error': '服务器内部错误', 'details': str(e)}), 500

@config_bp.route('/api/credentials/<int:credential_id>', methods=['DELETE'])
@login_required
@permission_required('config:edit')
def delete_credential(credential_id):
    """删除凭据"""
    try:
        credential = Credential.query.get_or_404(credential_id)
        
        # 检查凭据是否正在被使用（这里需要根据您的业务逻辑实现）
        # 例如：if credential.in_use:
        #     return jsonify({'error': '凭据正在被使用，无法删除'}), 400
        
        log_audit('delete', 'credential', credential.id,
                  f"删除凭据: {credential.name}",
                  details={'name': credential.name, 'type': credential.credential_type})

        # 删除凭据
        db.session.delete(credential)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': '凭据删除成功'
        }), 200

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"删除凭据失败: {str(e)}")
        return jsonify({'error': '服务器内部错误', 'details': str(e)}), 500

@config_bp.route('/api/credentials/<int:credential_id>', methods=['GET'])
@login_required
@permission_required('config:view')
def get_credential_detail(credential_id):
    """获取凭据详情（包含解密后的敏感信息）"""
    try:
        credential = Credential.query.get_or_404(credential_id)
        credential_dict = credential.to_dict_with_decrypted()
        return jsonify(credential_dict), 200
        
    except Exception as e:
        current_app.logger.error(f"获取凭据详情失败: {str(e)}")
        return jsonify({'error': '服务器内部错误'}), 500

@config_bp.route('/api/credentials/validate', methods=['POST'])
@login_required
@permission_required('config:edit')
def validate_credential():
    """验证凭据（测试连接）"""
    try:
        data = request.get_json()
        credential_id = data.get('credential_id')
        
        if not credential_id:
            return jsonify({'error': '凭据ID是必填项'}), 400
        
        credential = Credential.query.get_or_404(credential_id)
        
        # 根据凭据类型进行验证
        if credential.credential_type == 'ssh_key':
            # SSH密钥验证逻辑
            # 这里可以添加SSH连接测试代码
            return jsonify({
                'success': True,
                'message': 'SSH凭据验证功能待实现'
            })
        else:
            # 密码验证逻辑
            # 这里可以添加对应的协议连接测试代码
            return jsonify({
                'success': True,
                'message': '密码凭据验证功能待实现'
            })
            
    except Exception as e:
        current_app.logger.error(f"验证凭据失败: {str(e)}")
        return jsonify({'error': '验证失败', 'details': str(e)}), 500



@config_bp.route('/network-discovery')
@login_required
@permission_required('config:view')
def network_discovery():
    """发现配置页面"""
    configs = DiscoveryConfig.query.order_by(DiscoveryConfig.name).all()
    cabinets = Cabinet.query.order_by(Cabinet.name).all()
    return render_template('config/network_discovery.html', configs=configs, cabinets=cabinets)

@config_bp.route('/api/discovery-configs', methods=['GET'])
@login_required
@permission_required('config:view')
def get_discovery_configs():
    """获取发现配置"""
    configs = DiscoveryConfig.query.all()
    return jsonify([c.to_dict() for c in configs])

@config_bp.route('/api/discovery-configs', methods=['POST'])
@login_required
@permission_required('config:edit')
def add_discovery_config():
    """添加发现配置"""
    try:
        data = request.get_json()
        
        # 验证必填字段
        required_fields = ['name', 'scan_type', 'target_range']
        for field in required_fields:
            if field not in data or not data[field]:
                return jsonify({'error': f'字段 "{field}" 是必填项'}), 400
        
        # 检查配置名称是否已存在
        existing_config = DiscoveryConfig.query.filter_by(name=data['name']).first()
        if existing_config:
            return jsonify({'error': '配置名称已存在'}), 400
        
        # 验证目标范围格式
        target_range = data['target_range'].strip()
        if not validate_target_range(target_range):
            return jsonify({'error': '目标范围格式无效，请使用IP范围、CIDR或逗号分隔的IP地址'}), 400
        
        # 创建新配置
        new_config = DiscoveryConfig(
            name=data['name'],
            scan_type=data['scan_type'],
            target_range=target_range,
            snmp_community=data.get('snmp_community'),
            snmp_version=data.get('snmp_version', '2c'),
            snmp_retries=data.get('snmp_retries', 2),
            timeout=data.get('timeout', 5),
            max_threads=data.get('max_threads', 50),
            device_type=data.get('device_type', 'unknown'),
            cabinet_id=data.get('cabinet_id', type=int) if data.get('cabinet_id') else None,
            manufacturer=data.get('manufacturer', ''),
            use_ping=data.get('use_ping', True),
            auto_naming=data.get('auto_naming', True),
            schedule_type=data.get('schedule_type', 'manual'),
            auto_add_devices=data.get('auto_add_devices', False),
            enabled=data.get('enabled', True)
        )
        
        # 处理端口列表
        if 'ports' in data and data['ports']:
            if isinstance(data['ports'], list):
                new_config.ports = json.dumps(data['ports'])
            else:
                # 尝试解析字符串
                try:
                    ports_list = json.loads(data['ports'])
                    new_config.ports = json.dumps(ports_list)
                except json.JSONDecodeError:
                    # 如果是逗号分隔的字符串
                    ports_str = str(data['ports'])
                    ports_list = [p.strip() for p in ports_str.split(',') if p.strip()]
                    new_config.ports = json.dumps(ports_list)
        
        # 处理调度配置
        if 'schedule_config' in data and data['schedule_config']:
            if isinstance(data['schedule_config'], dict):
                new_config.schedule_config = json.dumps(data['schedule_config'])
            else:
                try:
                    schedule_dict = json.loads(data['schedule_config'])
                    new_config.schedule_config = json.dumps(schedule_dict)
                except json.JSONDecodeError:
                    new_config.schedule_config = json.dumps({})
        
        # 保存到数据库
        db.session.add(new_config)
        db.session.commit()

        log_audit('create', 'discovery_config', new_config.id,
                  f"创建发现配置: {new_config.name}",
                  details={'name': new_config.name, 'scan_type': new_config.scan_type, 'target_range': new_config.target_range})

        return jsonify({
            'success': True,
            'message': '发现配置添加成功',
            'config': new_config.to_dict()
        }), 201

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"添加发现配置失败: {str(e)}")
        return jsonify({'error': '服务器内部错误', 'details': str(e)}), 500

@config_bp.route('/api/discovery-configs/<int:config_id>', methods=['PUT'])
@login_required
@permission_required('config:edit')
def update_discovery_config(config_id):
    """更新发现配置"""
    try:
        config = DiscoveryConfig.query.get_or_404(config_id)
        data = request.get_json()
        
        # 验证必填字段
        if 'name' in data and (not data['name'] or data['name'].strip() == ''):
            return jsonify({'error': '配置名称不能为空'}), 400
        
        if 'target_range' in data and (not data['target_range'] or data['target_range'].strip() == ''):
            return jsonify({'error': '目标范围不能为空'}), 400
        
        # 验证目标范围格式
        if 'target_range' in data and not validate_target_range(data['target_range']):
            return jsonify({'error': '目标范围格式无效，请使用IP范围、CIDR或逗号分隔的IP地址'}), 400
        
        # 检查配置名称是否已被其他配置使用
        if 'name' in data and data['name'] != config.name:
            existing_config = DiscoveryConfig.query.filter_by(name=data['name']).first()
            if existing_config and existing_config.id != config_id:
                return jsonify({'error': '配置名称已存在'}), 400
        
        # 更新字段
        if 'name' in data:
            config.name = data['name']
        
        if 'scan_type' in data:
            config.scan_type = data['scan_type']
        
        if 'target_range' in data:
            config.target_range = data['target_range'].strip()

        if 'snmp_community' in data:
            config.snmp_community = data['snmp_community']
        
        if 'timeout' in data:
            config.timeout = data['timeout']
        
        if 'max_threads' in data:
            config.max_threads = data['max_threads']
        
        if 'schedule_type' in data:
            config.schedule_type = data['schedule_type']
        
        if 'auto_add_devices' in data:
            config.auto_add_devices = data['auto_add_devices']
        
        if 'enabled' in data:
            config.enabled = data['enabled']

        if 'snmp_version' in data:
            config.snmp_version = data['snmp_version']

        if 'snmp_retries' in data:
            config.snmp_retries = data['snmp_retries']

        if 'device_type' in data:
            config.device_type = data['device_type']

        if 'cabinet_id' in data:
            config.cabinet_id = data['cabinet_id']

        if 'manufacturer' in data:
            config.manufacturer = data['manufacturer']

        if 'use_ping' in data:
            config.use_ping = data['use_ping']

        if 'auto_naming' in data:
            config.auto_naming = data['auto_naming']
        
        # 处理端口列表
        if 'ports' in data:
            if isinstance(data['ports'], list):
                config.ports = json.dumps(data['ports'])
            else:
                try:
                    ports_list = json.loads(data['ports']) if data['ports'] else []
                    config.ports = json.dumps(ports_list)
                except json.JSONDecodeError:
                    # 如果是逗号分隔的字符串
                    ports_str = str(data['ports'])
                    ports_list = [p.strip() for p in ports_str.split(',') if p.strip()]
                    config.ports = json.dumps(ports_list)
        
        # 处理调度配置
        if 'schedule_config' in data:
            if isinstance(data['schedule_config'], dict):
                config.schedule_config = json.dumps(data['schedule_config'])
            else:
                try:
                    schedule_dict = json.loads(data['schedule_config']) if data['schedule_config'] else {}
                    config.schedule_config = json.dumps(schedule_dict)
                except json.JSONDecodeError:
                    config.schedule_config = json.dumps({})
        
        # 更新更新时间
        config.updated_at = datetime.utcnow()
        
        # 保存到数据库
        db.session.commit()

        log_audit('update', 'discovery_config', config.id,
                  f"更新发现配置: {config.name}",
                  details={'name': config.name, 'scan_type': config.scan_type, 'target_range': config.target_range})

        return jsonify({
            'success': True,
            'message': '发现配置更新成功',
            'config': config.to_dict()
        }), 200

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"更新发现配置失败: {str(e)}")
        return jsonify({'error': '服务器内部错误', 'details': str(e)}), 500

@config_bp.route('/api/discovery-configs/<int:config_id>', methods=['DELETE'])
@login_required
@permission_required('config:edit')
def delete_discovery_config(config_id):
    """删除发现配置"""
    try:
        config = DiscoveryConfig.query.get_or_404(config_id)
        
        log_audit('delete', 'discovery_config', config.id,
                  f"删除发现配置: {config.name}",
                  details={'name': config.name, 'scan_type': config.scan_type})

        # 删除配置
        db.session.delete(config)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': '发现配置删除成功'
        }), 200

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"删除发现配置失败: {str(e)}")
        return jsonify({'error': '服务器内部错误', 'details': str(e)}), 500

@config_bp.route('/api/discovery-configs/<int:config_id>', methods=['GET'])
@login_required
@permission_required('config:view')
def get_discovery_config_detail(config_id):
    """获取发现配置详情"""
    try:
        config = DiscoveryConfig.query.get_or_404(config_id)
        return jsonify(config.to_dict()), 200
        
    except Exception as e:
        current_app.logger.error(f"获取发现配置详情失败: {str(e)}")
        return jsonify({'error': '服务器内部错误'}), 500

@config_bp.route('/api/discovery-configs/<int:config_id>/run', methods=['POST'])
@login_required
@permission_required('config:edit')
def run_discovery(config_id):
    """执行发现任务 - 调用设备批量导入或SNMP扫描"""
    import threading
    from blueprints.device import (
        progress_manager,
        _run_import_task_with_app,
        _run_snmp_scan_task_with_app,
    )

    try:
        config = DiscoveryConfig.query.get_or_404(config_id)
        app = current_app._get_current_object()

        if config.scan_type == 'snmp':
            # === IP段SNMP扫描 ===
            scan_params = {
                'ip_range': config.target_range,
                'snmp_community': config.snmp_community or 'public',
                'snmp_version': getattr(config, 'snmp_version', '2c'),
                'auto_add': config.auto_add_devices,
                'skip_existing': True,
                'snmp_timeout': config.timeout or 2,
                'snmp_retries': getattr(config, 'snmp_retries', 2),
            }
            task_id = progress_manager.create_task('snmp_scan')
            thread = threading.Thread(
                target=_run_snmp_scan_task_with_app,
                args=(app, task_id, scan_params)
            )
            thread.daemon = True
            thread.start()
        else:
            # === IP段批量导入（ping扫描/其他） ===
            form_data = {
                'ip_range': config.target_range,
                'device_type': getattr(config, 'device_type', 'unknown'),
                'cabinet_id': str(getattr(config, 'cabinet_id', '') or ''),
                'manufacturer': getattr(config, 'manufacturer', ''),
                'use_ping': str(getattr(config, 'use_ping', True)),
                'auto_naming': str(getattr(config, 'auto_naming', True)),
                'concurrent': str(config.max_threads or 20),
                'ping_timeout': str(config.timeout or 2),
                'auto_add_devices': str(config.auto_add_devices),
            }
            task_id = progress_manager.create_task('import')
            thread = threading.Thread(
                target=_run_import_task_with_app,
                args=(app, task_id, form_data)
            )
            thread.daemon = True
            thread.start()

        # 更新 config 状态
        config.last_run_at = datetime.utcnow()
        config.last_run_status = 'running'
        db.session.commit()

        # 记录审计日志
        try:
            log_audit('execute', 'discovery', config.id, f"执行{config.scan_type}发现: {config.name}")
        except Exception:
            pass

        return jsonify({
            'success': True,
            'task_id': task_id,
            'message': '发现任务已启动',
            'config_id': config_id,
            'config_name': config.name,
            'scan_type': config.scan_type,
        })

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"执行发现任务失败: {str(e)}", exc_info=True)
        return jsonify({'error': '服务器内部错误', 'details': str(e)}), 500
@config_bp.route('/api/discovery-configs/<int:config_id>/results', methods=['GET'])
@login_required
@permission_required('config:view')
def get_discovery_results(config_id):
    """获取发现结果 - 查询设备扫描/导入进度"""
    try:
        config = DiscoveryConfig.query.get_or_404(config_id)
        from blueprints.device import progress_manager

        # 查找最近的进度任务（通过 config 的最后运行时间关联）
        # 遍历所有进度任务，找到时间匹配的
        tasks = progress_manager.get_all_tasks()
        matched_task = None
        if config.last_run_at:
            last_run_ts = config.last_run_at.timestamp()
            for tid, tdata in tasks.items():
                start_time = tdata.get('start_time', '')
                if start_time:
                    try:
                        from datetime import datetime
                        st = datetime.fromisoformat(start_time)
                        if abs(st.timestamp() - last_run_ts) < 30:
                            matched_task = tdata
                            matched_task['task_id'] = tid
                            break
                    except Exception:
                        continue

        if not matched_task:
            return jsonify({
                'config_id': config_id,
                'config_name': config.name,
                'last_run': config.last_run_at.isoformat() if config.last_run_at else None,
                'task_status': 'no_task',
                'total_targets': 0,
                'results': []
            }), 200

        return jsonify({
            'config_id': config_id,
            'config_name': config.name,
            'last_run': config.last_run_at.isoformat() if config.last_run_at else None,
            'task_id': matched_task.get('task_id'),
            'task_status': matched_task.get('status', 'unknown'),
            'task_progress': matched_task.get('progress', 0),
            'total_targets': matched_task.get('total', 0),
            'processed': matched_task.get('processed', 0),
            'added': matched_task.get('added', 0),
            'skipped': matched_task.get('skipped', 0),
            'failed': matched_task.get('failed', 0),
            'results': matched_task.get('results', []),
            'message': matched_task.get('message', ''),
            'current_step': matched_task.get('current_step', ''),
        }), 200

    except Exception as e:
        current_app.logger.error(f"获取发现结果失败: {str(e)}")
        return jsonify({'error': '服务器内部错误'}), 500

def validate_target_range(target_range):
    """验证目标范围格式"""
    if not target_range or not target_range.strip():
        return False
    
    # 支持多种格式：IP范围、CIDR、逗号分隔的IP地址
    patterns = [
        r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(-\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})?$',  # IP范围
        r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}/\d{1,2}$',  # CIDR
        r'^(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})(,\s*\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})*$'  # 逗号分隔
    ]
    
    # 检查是否符合任一格式
    for pattern in patterns:
        if re.match(pattern, target_range.replace(' ', '')):
            return True
    
    return False

def parse_target_range(target_range):
    """解析目标范围，返回IP地址列表"""
    # 简化实现，实际应用中需要更完整的解析
    if '-' in target_range:  # IP范围
        start, end = target_range.split('-')
        return [start.strip()]
    elif '/' in target_range:  # CIDR
        return [target_range]
    else:  # 逗号分隔
        return [ip.strip() for ip in target_range.split(',') if ip.strip()]



# ========== 用户与权限 ==========

@config_bp.route('/user-management')
@login_required
@permission_required('system:admin')
def user_management():
    """用户管理页面"""
    
    users = User.query.order_by(User.username).all()
    roles = Role.query.order_by(Role.name).all()
    
    return render_template('config/user_management.html', users=users, roles=roles)


@config_bp.route('/api/users', methods=['GET'])
@login_required
@permission_required('system:admin')
def get_users_api():
    """获取用户列表（API版本）"""
    try:
        # 检查是否为管理员
        if not current_user.is_admin:
            return jsonify({'error': '权限不足，只有管理员可以访问用户管理'}), 403
        
        users = User.query.order_by(User.username).all()
        users_data = []
        
        for user in users:
            users_data.append({
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'role': user.role,
                'department': user.department,
                'phone': user.phone,
                'is_active': user.is_active,
                'last_login': user.last_login.isoformat() if user.last_login else None,
                'created_at': user.created_at.isoformat() if user.created_at else None,
                'updated_at': user.updated_at.isoformat() if user.updated_at else None
            })
        
        return jsonify(users_data), 200
        
    except Exception as e:
        current_app.logger.error(f"获取用户列表失败: {str(e)}")
        return jsonify({'error': '服务器内部错误'}), 500

@config_bp.route('/api/users/<int:user_id>', methods=['GET'])
@login_required
@permission_required('system:admin')
def get_user_detail(user_id):
    """获取用户详情"""
    try:
        # 检查是否为管理员
        if not current_user.is_admin:
            return jsonify({'error': '权限不足'}), 403
        
        user = User.query.get_or_404(user_id)
        
        return jsonify({
            'id': user.id,
            'username': user.username,
            'email': user.email,
            'role': user.role,
            'department': user.department,
            'phone': user.phone,
            'is_active': user.is_active,
            'last_login': user.last_login.isoformat() if user.last_login else None,
            'created_at': user.created_at.isoformat() if user.created_at else None,
            'updated_at': user.updated_at.isoformat() if user.updated_at else None
        }), 200
        
    except Exception as e:
        current_app.logger.error(f"获取用户详情失败: {str(e)}")
        return jsonify({'error': '服务器内部错误'}), 500

@config_bp.route('/api/users', methods=['POST'])
@login_required
@permission_required('system:admin')
def add_user():
    """添加新用户"""
    try:
        # 检查是否为管理员
        if not current_user.is_admin:
            return jsonify({'error': '权限不足，只有管理员可以添加用户'}), 403
        
        data = request.get_json()
        
        # 验证必填字段
        required_fields = ['username', 'email', 'password', 'role']
        for field in required_fields:
            if field not in data or not data[field]:
                return jsonify({'error': f'字段 "{field}" 是必填项'}), 400
        
        # 验证用户名格式
        if not re.match(r'^[a-zA-Z0-9_]{3,20}$', data['username']):
            return jsonify({'error': '用户名只能包含字母、数字和下划线，长度为3-20个字符'}), 400
        
        # 验证邮箱格式
        email_regex = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_regex, data['email']):
            return jsonify({'error': '邮箱格式无效'}), 400
        
        # 验证角色
        valid_roles = ['admin', 'user', 'operator', 'viewer']
        if data['role'] not in valid_roles:
            return jsonify({'error': f'角色无效，可选值: {", ".join(valid_roles)}'}), 400
        
        # 验证密码强度
        if len(data['password']) < 6:
            return jsonify({'error': '密码长度至少为6个字符'}), 400
        
        # 检查用户名是否已存在
        existing_user = User.query.filter_by(username=data['username']).first()
        if existing_user:
            return jsonify({'error': '用户名已存在'}), 400
        
        # 检查邮箱是否已存在
        existing_email = User.query.filter_by(email=data['email']).first()
        if existing_email:
            return jsonify({'error': '邮箱已存在'}), 400
        
        # 创建新用户
        new_user = User(
            username=data['username'],
            email=data['email'],
            role=data['role'],
            department=data.get('department'),
            phone=data.get('phone'),
            is_active=data.get('is_active', True)
        )
        
        # 设置密码
        new_user.set_password(data['password'])
        
        # 保存到数据库
        db.session.add(new_user)
        db.session.commit()

        log_audit('create', 'user', new_user.id,
                  f"创建用户: {new_user.username}",
                  details={'username': new_user.username, 'email': new_user.email, 'role': new_user.role})

        return jsonify({
            'success': True,
            'message': '用户添加成功',
            'user': {
                'id': new_user.id,
                'username': new_user.username,
                'email': new_user.email,
                'role': new_user.role,
                'is_active': new_user.is_active
            }
        }), 201

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"添加用户失败: {str(e)}")
        return jsonify({'error': '服务器内部错误', 'details': str(e)}), 500

@config_bp.route('/api/users/<int:user_id>', methods=['PUT'])
@login_required
@permission_required('system:admin')
def update_user(user_id):
    """更新用户信息"""
    try:
        # 检查是否为管理员
        if not current_user.is_admin:
            return jsonify({'error': '权限不足，只有管理员可以修改用户'}), 403
        
        # 不允许修改自己的角色或禁用自己
        if user_id == current_user.id:
            return jsonify({'error': '不能修改自己的账户信息'}), 400
        
        user = User.query.get_or_404(user_id)
        data = request.get_json()
        
        # 验证用户名格式
        if 'username' in data and data['username'] != user.username:
            if not re.match(r'^[a-zA-Z0-9_]{3,20}$', data['username']):
                return jsonify({'error': '用户名只能包含字母、数字和下划线，长度为3-20个字符'}), 400
            
            # 检查用户名是否已被其他用户使用
            existing_user = User.query.filter_by(username=data['username']).first()
            if existing_user and existing_user.id != user_id:
                return jsonify({'error': '用户名已存在'}), 400
            
            user.username = data['username']
        
        # 验证邮箱格式
        if 'email' in data and data['email'] != user.email:
            email_regex = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
            if not re.match(email_regex, data['email']):
                return jsonify({'error': '邮箱格式无效'}), 400
            
            # 检查邮箱是否已被其他用户使用
            existing_email = User.query.filter_by(email=data['email']).first()
            if existing_email and existing_email.id != user_id:
                return jsonify({'error': '邮箱已存在'}), 400
            
            user.email = data['email']
        
        # 更新其他字段
        if 'role' in data:
            valid_roles = ['admin', 'user', 'operator', 'viewer']
            if data['role'] not in valid_roles:
                return jsonify({'error': f'角色无效，可选值: {", ".join(valid_roles)}'}), 400
            user.role = data['role']
        
        if 'department' in data:
            user.department = data['department']
        
        if 'phone' in data:
            user.phone = data['phone']
        
        if 'is_active' in data:
            user.is_active = data['is_active']
        
        # 更新密码（如果提供了新密码）
        if 'password' in data and data['password']:
            if len(data['password']) < 6:
                return jsonify({'error': '密码长度至少为6个字符'}), 400
            user.set_password(data['password'])
        
        # 更新更新时间
        user.updated_at = datetime.utcnow()
        
        # 保存到数据库
        db.session.commit()

        log_audit('update', 'user', user.id,
                  f"更新用户: {user.username}",
                  details={'username': user.username, 'email': user.email, 'role': user.role, 'is_active': user.is_active})

        return jsonify({
            'success': True,
            'message': '用户信息更新成功',
            'user': {
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'role': user.role,
                'is_active': user.is_active
            }
        }), 200

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"更新用户失败: {str(e)}")
        return jsonify({'error': '服务器内部错误', 'details': str(e)}), 500

@config_bp.route('/api/users/<int:user_id>', methods=['DELETE'])
@login_required
@permission_required('system:admin')
def delete_user(user_id):
    """删除用户"""
    try:
        # 检查是否为管理员
        if not current_user.is_admin:
            return jsonify({'error': '权限不足，只有管理员可以删除用户'}), 403
        
        # 不允许删除自己
        if user_id == current_user.id:
            return jsonify({'error': '不能删除自己的账户'}), 400
        
        user = User.query.get_or_404(user_id)
        
        # 检查是否是最后一个管理员
        if user.role == 'admin':
            admin_count = User.query.filter_by(role='admin').count()
            if admin_count <= 1:
                return jsonify({'error': '不能删除最后一个管理员账户'}), 400
        
        log_audit('delete', 'user', user.id,
                  f"删除用户: {user.username}",
                  details={'username': user.username, 'email': user.email, 'role': user.role})

        # 删除用户
        db.session.delete(user)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': '用户删除成功'
        }), 200

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"删除用户失败: {str(e)}")
        return jsonify({'error': '服务器内部错误', 'details': str(e)}), 500

@config_bp.route('/api/users/<int:user_id>/reset-password', methods=['POST'])
@login_required
@permission_required('system:admin')
def reset_user_password(user_id):
    """重置用户密码（管理员操作）"""
    try:
        # 检查是否为管理员
        if not current_user.is_admin:
            return jsonify({'error': '权限不足，只有管理员可以重置密码'}), 403
        
        # 不允许重置自己的密码
        if user_id == current_user.id:
            return jsonify({'error': '不能重置自己的密码，请使用个人设置页面'}), 400
        
        data = request.get_json()
        
        if 'new_password' not in data or not data['new_password']:
            return jsonify({'error': '新密码是必填项'}), 400
        
        # 验证密码强度
        if len(data['new_password']) < 6:
            return jsonify({'error': '密码长度至少为6个字符'}), 400
        
        user = User.query.get_or_404(user_id)
        
        # 设置新密码
        user.set_password(data['new_password'])
        user.updated_at = datetime.utcnow()
        
        # 保存到数据库
        db.session.commit()

        log_audit('update', 'user', user.id,
                  f"重置用户密码: {user.username}",
                  details={'username': user.username})

        return jsonify({
            'success': True,
            'message': '密码重置成功'
        }), 200

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"重置用户密码失败: {str(e)}")
        return jsonify({'error': '服务器内部错误', 'details': str(e)}), 500

@config_bp.route('/api/users/<int:user_id>/toggle-active', methods=['POST'])
@login_required
@permission_required('system:admin')
def toggle_user_active(user_id):
    """启用/禁用用户"""
    try:
        # 检查是否为管理员
        if not current_user.is_admin:
            return jsonify({'error': '权限不足'}), 403
        
        # 不允许操作自己
        if user_id == current_user.id:
            return jsonify({'error': '不能启用/禁用自己的账户'}), 400
        
        data = request.get_json()
        
        if 'is_active' not in data:
            return jsonify({'error': '缺少is_active参数'}), 400
        
        user = User.query.get_or_404(user_id)
        
        # 检查是否是最后一个管理员
        if user.role == 'admin' and data['is_active'] == False:
            admin_count = User.query.filter_by(role='admin', is_active=True).count()
            if admin_count <= 1:
                return jsonify({'error': '不能禁用最后一个管理员账户'}), 400
        
        user.is_active = data['is_active']
        user.updated_at = datetime.utcnow()
        
        # 保存到数据库
        db.session.commit()

        action = "启用" if data['is_active'] else "禁用"
        log_audit('update', 'user', user.id,
                  f"{action}用户: {user.username}",
                  details={'username': user.username, 'is_active': data['is_active']})

        return jsonify({
            'success': True,
            'message': f'用户{action}成功',
            'is_active': user.is_active
        }), 200
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"启用/禁用用户失败: {str(e)}")
        return jsonify({'error': '服务器内部错误', 'details': str(e)}), 500

@config_bp.route('/api/users/search', methods=['GET'])
@login_required
@permission_required('system:admin')
def search_users():
    """搜索用户"""
    try:
        # 检查是否为管理员
        if not current_user.is_admin:
            return jsonify({'error': '权限不足'}), 403
        
        search_term = request.args.get('q', '').strip()
        
        if not search_term:
            return jsonify([]), 200
        
        # 搜索用户名、邮箱、部门
        users = User.query.filter(
            db.or_(
                User.username.ilike(f'%{search_term}%'),
                User.email.ilike(f'%{search_term}%'),
                User.department.ilike(f'%{search_term}%')
            )
        ).order_by(User.username).limit(20).all()
        
        users_data = []
        for user in users:
            users_data.append({
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'role': user.role,
                'department': user.department,
                'is_active': user.is_active
            })
        
        return jsonify(users_data), 200
        
    except Exception as e:
        current_app.logger.error(f"搜索用户失败: {str(e)}")
        return jsonify({'error': '服务器内部错误'}), 500

@config_bp.route('/api/users/roles', methods=['GET'])
@login_required
@permission_required('system:admin')
def get_user_roles():
    """获取用户角色选项"""
    try:
        # 检查是否为管理员
        if not current_user.is_admin:
            return jsonify({'error': '权限不足'}), 403
        
        # 角色列表
        roles = [
            {'value': 'admin', 'label': '管理员', 'description': '具有所有权限'},
            {'value': 'operator', 'label': '操作员', 'description': '可以执行操作但不能修改系统配置'},
            {'value': 'user', 'label': '普通用户', 'description': '基本用户权限'},
            {'value': 'viewer', 'label': '查看者', 'description': '只能查看，不能执行任何操作'}
        ]
        
        return jsonify(roles), 200
        
    except Exception as e:
        current_app.logger.error(f"获取角色列表失败: {str(e)}")
        return jsonify({'error': '服务器内部错误'}), 500



@config_bp.route('/api/users/<int:user_id>/roles', methods=['PUT'])
@login_required
@permission_required('system:admin')
def update_user_roles(user_id):
    """更新用户角色"""
    from ..models import User, UserRole
    
    user = User.query.get_or_404(user_id)
    data = request.get_json()
    
    # 清除现有角色
    UserRole.query.filter_by(user_id=user_id).delete()
    
    # 添加新角色
    for role_id in data.get('role_ids', []):
        user_role = UserRole(user_id=user_id, role_id=role_id)
        db.session.add(user_role)
    
    db.session.commit()
    
    log_audit('update', 'user_roles', user_id, f"更新用户角色: {user.username}")
    
    return jsonify({'success': True, 'message': '用户角色已更新'})

@config_bp.route('/role-management')
@login_required
@permission_required('system:admin')
def role_management():
    """角色管理页面"""
    roles = Role.query.order_by(Role.name).all()
    for role in roles:
        if role.permissions is None:
            role.permissions = []
    permissions = Permission.query.order_by(Permission.category, Permission.module).all()

    # 按类别和模块分组权限
    permissions_by_category = {}
    for perm in permissions:
        if perm.category not in permissions_by_category:
            permissions_by_category[perm.category] = {}
        if perm.module not in permissions_by_category[perm.category]:
            permissions_by_category[perm.category][perm.module] = []
        permissions_by_category[perm.category][perm.module].append(perm.to_dict())
    
    return render_template('config/role_management.html', 
                         roles=roles, 
                         permissions_by_category=permissions_by_category)

@config_bp.route('/api/roles', methods=['POST'])
@login_required
@permission_required('system:admin')
def create_role():
    """创建角色"""
    data = request.get_json()
    
    role = Role(
        name=data.get('name'),
        description=data.get('description'),
        permissions=json.dumps(data.get('permissions', {})),
        is_system=data.get('is_system', False)
    )
    
    db.session.add(role)
    db.session.commit()
    
    log_audit('create', 'role', role.id, f"创建角色: {role.name}")
    
    return jsonify({'success': True, 'message': '角色已创建', 'id': role.id})


@config_bp.route('/permission-settings')
@login_required
@permission_required('system:admin')
def permission_settings():
    """权限设置页面"""
    permissions = Permission.query.order_by(Permission.category, Permission.module, Permission.name).all()
    return render_template('config/permission_settings.html', permissions=permissions)

@config_bp.route('/api/permissions', methods=['GET'])
@login_required
@permission_required('system:admin')
def get_permissions():
    """获取所有权限"""
    permissions = Permission.query.all()
    return jsonify([p.to_dict() for p in permissions])


@config_bp.route('/api/permissions', methods=['POST'])
@login_required
@permission_required('system:admin')
def add_permission():
    """添加新权限"""
    try:
        # 检查是否为管理员
        if not current_user.is_admin:
            return jsonify({'error': '权限不足，只有管理员可以管理权限'}), 403
        
        data = request.get_json()
        
        # 验证必填字段
        required_fields = ['code', 'name']
        for field in required_fields:
            if field not in data or not data[field]:
                return jsonify({'error': f'字段 "{field}" 是必填项'}), 400
        
        # 验证权限代码格式
        code = data['code']
        if not re.match(r'^[a-zA-Z0-9_:.]+$', code):
            return jsonify({'error': '权限代码只能包含字母、数字、下划线、冒号和点号'}), 400
        
        # 检查权限代码是否已存在
        existing_permission = Permission.query.filter_by(code=code).first()
        if existing_permission:
            return jsonify({'error': '权限代码已存在'}), 400
        
        # 创建新权限
        new_permission = Permission(
            code=code,
            name=data['name'],
            description=data.get('description'),
            category=data.get('category', 'general'),
            module=data.get('module'),
            is_system=data.get('is_system', False)
        )
        
        # 保存到数据库
        db.session.add(new_permission)
        db.session.commit()

        log_audit('create', 'permission', new_permission.id,
                  f"创建权限: {new_permission.name}",
                  details={'code': new_permission.code, 'name': new_permission.name, 'category': new_permission.category})

        return jsonify({
            'success': True,
            'message': '权限添加成功',
            'permission': new_permission.to_dict()
        }), 201

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"添加权限失败: {str(e)}")
        return jsonify({'error': '服务器内部错误', 'details': str(e)}), 500

@config_bp.route('/api/permissions/<int:permission_id>', methods=['PUT'])
@login_required
@permission_required('system:admin')
def update_permission(permission_id):
    """更新权限"""
    try:
        # 检查是否为管理员
        if not current_user.is_admin:
            return jsonify({'error': '权限不足，只有管理员可以管理权限'}), 403
        
        permission = Permission.query.get_or_404(permission_id)
        data = request.get_json()
        
        # 如果是系统权限，只能更新部分字段
        if permission.is_system:
            allowed_fields = ['name', 'description', 'category', 'module']
            for key in data:
                if key not in allowed_fields:
                    return jsonify({'error': f'系统权限的"{key}"字段不可修改'}), 400
        
        # 验证必填字段
        if 'code' in data and (not data['code'] or data['code'].strip() == ''):
            return jsonify({'error': '权限代码不能为空'}), 400
        
        if 'name' in data and (not data['name'] or data['name'].strip() == ''):
            return jsonify({'error': '权限名称不能为空'}), 400
        
        # 验证权限代码格式
        if 'code' in data and data['code'] != permission.code:
            if not re.match(r'^[a-zA-Z0-9_:.]+$', data['code']):
                return jsonify({'error': '权限代码只能包含字母、数字、下划线、冒号和点号'}), 400
            
            # 检查权限代码是否已被其他权限使用
            existing_permission = Permission.query.filter_by(code=data['code']).first()
            if existing_permission and existing_permission.id != permission_id:
                return jsonify({'error': '权限代码已存在'}), 400
            
            permission.code = data['code']
        
        # 更新其他字段
        if 'name' in data:
            permission.name = data['name']
        
        if 'description' in data:
            permission.description = data['description']
        
        if 'category' in data:
            permission.category = data['category']
        
        if 'module' in data:
            permission.module = data['module']
        
        # 系统权限字段不能修改
        if 'is_system' in data and not permission.is_system:
            permission.is_system = data['is_system']
        
        # 保存到数据库
        db.session.commit()

        log_audit('update', 'permission', permission.id,
                  f"更新权限: {permission.name}",
                  details={'code': permission.code, 'name': permission.name, 'category': permission.category})

        return jsonify({
            'success': True,
            'message': '权限更新成功',
            'permission': permission.to_dict()
        }), 200

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"更新权限失败: {str(e)}")
        return jsonify({'error': '服务器内部错误', 'details': str(e)}), 500

@config_bp.route('/api/permissions/<int:permission_id>', methods=['DELETE'])
@login_required
@permission_required('system:admin')
def delete_permission(permission_id):
    """删除权限"""
    try:
        # 检查是否为管理员
        if not current_user.is_admin:
            return jsonify({'error': '权限不足，只有管理员可以管理权限'}), 403
        
        permission = Permission.query.get_or_404(permission_id)
        
        # 检查是否是系统权限
        if permission.is_system:
            return jsonify({'error': '系统权限不能删除'}), 400
        
        # 检查权限是否正在被使用（这里需要根据您的业务逻辑实现）
        # 例如：if permission.in_use:
        #     return jsonify({'error': '权限正在被使用，无法删除'}), 400
        
        log_audit('delete', 'permission', permission.id,
                  f"删除权限: {permission.name}",
                  details={'code': permission.code, 'name': permission.name, 'category': permission.category})

        # 删除权限
        db.session.delete(permission)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': '权限删除成功'
        }), 200

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"删除权限失败: {str(e)}")
        return jsonify({'error': '服务器内部错误', 'details': str(e)}), 500

@config_bp.route('/api/permissions/<int:permission_id>', methods=['GET'])
@login_required
@permission_required('system:admin')
def get_permission_detail(permission_id):
    """获取权限详情"""
    try:
        # 检查是否为管理员
        if not current_user.is_admin:
            return jsonify({'error': '权限不足'}), 403
        
        permission = Permission.query.get_or_404(permission_id)
        return jsonify(permission.to_dict()), 200
        
    except Exception as e:
        current_app.logger.error(f"获取权限详情失败: {str(e)}")
        return jsonify({'error': '服务器内部错误'}), 500

@config_bp.route('/api/permissions/categories', methods=['GET'])
@login_required
@permission_required('system:admin')
def get_permission_categories():
    """获取权限分类列表"""
    try:
        # 检查是否为管理员
        if not current_user.is_admin:
            return jsonify({'error': '权限不足'}), 403
        
        # 从数据库获取所有分类
        categories = db.session.query(Permission.category).distinct().all()
        category_list = [cat[0] for cat in categories if cat[0]]
        
        return jsonify(category_list), 200
        
    except Exception as e:
        current_app.logger.error(f"获取权限分类失败: {str(e)}")
        return jsonify({'error': '服务器内部错误'}), 500

@config_bp.route('/api/permissions/modules', methods=['GET'])
@login_required
@permission_required('system:admin')
def get_permission_modules():
    """获取权限模块列表"""
    try:
        # 检查是否为管理员
        if not current_user.is_admin:
            return jsonify({'error': '权限不足'}), 403
        
        # 从数据库获取所有模块
        modules = db.session.query(Permission.module).distinct().all()
        module_list = [mod[0] for mod in modules if mod[0]]
        
        return jsonify(module_list), 200
        
    except Exception as e:
        current_app.logger.error(f"获取权限模块失败: {str(e)}")
        return jsonify({'error': '服务器内部错误'}), 500

@config_bp.route('/api/permissions/search', methods=['GET'])
@login_required
@permission_required('system:admin')
def search_permissions():
    """搜索权限"""
    try:
        # 检查是否为管理员
        if not current_user.is_admin:
            return jsonify({'error': '权限不足'}), 403
        
        search_term = request.args.get('q', '').strip()
        
        if not search_term:
            return jsonify([]), 200
        
        # 搜索权限代码、名称、描述
        permissions = Permission.query.filter(
            db.or_(
                Permission.code.ilike(f'%{search_term}%'),
                Permission.name.ilike(f'%{search_term}%'),
                Permission.description.ilike(f'%{search_term}%')
            )
        ).order_by(Permission.code).limit(50).all()
        
        permissions_data = [p.to_dict() for p in permissions]
        
        return jsonify(permissions_data), 200
        
    except Exception as e:
        current_app.logger.error(f"搜索权限失败: {str(e)}")
        return jsonify({'error': '服务器内部错误'}), 500

@config_bp.route('/api/permissions/import-default', methods=['POST'])
@login_required
@permission_required('system:admin')
def import_default_permissions():
    """导入默认权限和角色（开发人员使用）"""
    try:
        if not current_user.is_admin:
            return jsonify({'error': '权限不足'}), 403

        from utils.permission import create_default_roles_and_permissions
        create_default_roles_and_permissions()

        log_audit('create', 'permission', 0, '导入默认权限和角色')

        return jsonify({
            'success': True,
            'message': '默认权限和角色导入成功',
        })

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"导入默认权限失败: {str(e)}")
        return jsonify({'error': f'导入失败: {str(e)}'}), 500




# ========== 日志与审计 ==========


@config_bp.route('/system-logs')
@login_required
@permission_required('system:admin')
def system_logs():
    """系统日志页面"""
    page = request.args.get('page', 1, type=int)
    level = request.args.get('level', '')
    module = request.args.get('module', '')
    start_date_str = request.args.get('start_date', '')
    end_date_str = request.args.get('end_date', '')

    query = SystemLog.query

    # === 关键修改：将字符串日期解析为 datetime 对象 ===
    if start_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
            query = query.filter(SystemLog.timestamp >= start_date)
        except ValueError:
            pass

    if end_date_str:
        try:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').replace(
                hour=23, minute=59, second=59, microsecond=999999
            )
            query = query.filter(SystemLog.timestamp <= end_date)
        except ValueError:
            pass

    # 其他条件
    if level:
        query = query.filter(SystemLog.level == level)
    if module:
        query = query.filter(SystemLog.module == module)

    logs = query.order_by(SystemLog.timestamp.desc()).paginate(page=page, per_page=50, error_out=False)

    # ==================== 处理时间显示（UTC 转北京时间） ====================
    import pytz
    from datetime import timezone
    
    beijing_tz = pytz.timezone('Asia/Shanghai')
    
    for log in logs.items:
        if log.timestamp:
            # 如果 timestamp 是 naive datetime，添加 UTC 时区
            if log.timestamp.tzinfo is None:
                utc_time = log.timestamp.replace(tzinfo=timezone.utc)
            else:
                utc_time = log.timestamp.astimezone(timezone.utc)
            # 转换为北京时间
            beijing_time = utc_time.astimezone(beijing_tz)
            log.timestamp_display = beijing_time.strftime('%Y-%m-%d %H:%M:%S')
        else:
            log.timestamp_display = ''

    # 获取选项
    levels = db.session.query(SystemLog.level).distinct().all()
    modules = db.session.query(SystemLog.module).distinct().all()

    return render_template('config/system_logs.html',
                         logs=logs,
                         levels=[l[0] for l in levels],
                         modules=[m[0] for m in modules],
                         current_level=level,
                         current_module=module,
                         start_date=start_date_str,
                         end_date=end_date_str)
# API: 获取单个日志详情
@config_bp.route('/api/logs/<int:log_id>')
@login_required
@permission_required('system:admin')
def get_log_details(log_id):
    """获取单个日志的详细信息"""
    log = SystemLog.query.get_or_404(log_id)
    return jsonify(log.to_dict())

# API: 获取日志的详细数据
@config_bp.route('/api/logs/<int:log_id>/details')
@login_required
@permission_required('system:admin')
def get_log_details_data(log_id):
    """获取日志的详细数据（JSON格式）"""
    log = SystemLog.query.get_or_404(log_id)
    return jsonify({
        'details': json.loads(log.details) if log.details else {}
    })

# API: 删除日志
@config_bp.route('/api/logs/<int:log_id>', methods=['DELETE'])
@login_required
@permission_required('system:admin')
def delete_log(log_id):
    """删除日志记录"""
    log = SystemLog.query.get_or_404(log_id)
    
    # 记录删除操作
    admin_log = SystemLog(
        level='info',
        module='system_logs',
        source='API',
        message=f"用户 {current_user.username} 删除了日志记录 ID: {log_id}",
        details=json.dumps(log.to_dict()),
        user_id=current_user.id,
        ip_address=request.remote_addr,
        request_id=request.headers.get('X-Request-ID', '')
    )
    db.session.add(admin_log)
    
    db.session.delete(log)
    db.session.commit()
    
    return jsonify({'success': True, 'message': '日志已删除'})

# API: 导出日志
@config_bp.route('/api/logs/export')
@login_required
@permission_required('system:admin')
def export_logs():
    """导出日志数据"""
    # 获取筛选参数
    level = request.args.get('level', '')
    module = request.args.get('module', '')
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    export_format = request.args.get('format', 'csv')
    limit = request.args.get('limit', 1000, type=int)
    include_details = request.args.get('include_details', 'true') == 'true'
    
    # 构建查询
    query = SystemLog.query
    
    if level:
        query = query.filter(SystemLog.level == level)
    if module:
        query = query.filter(SystemLog.module == module)
    if start_date:
        query = query.filter(SystemLog.timestamp >= start_date)
    if end_date:
        query = query.filter(SystemLog.timestamp <= end_date)
    
    # 限制数量
    if limit > 0:
        logs = query.order_by(SystemLog.timestamp.desc()).limit(limit).all()
    else:
        logs = query.order_by(SystemLog.timestamp.desc()).all()
    
    # 根据格式导出
    if export_format == 'csv':
        return export_logs_csv(logs, include_details)
    elif export_format == 'json':
        return export_logs_json(logs, include_details)
    else:  # txt
        return export_logs_txt(logs, include_details)

def export_logs_csv(logs, include_details):
    """导出为CSV格式"""
    output = io.StringIO()
    writer = csv.writer(output)
    
    # 写入标题行
    headers = ['ID', '时间', '级别', '模块', '来源', '消息', '用户', 'IP地址', '请求ID']
    if include_details:
        headers.append('详细数据')
    writer.writerow(headers)
    
    # 写入数据行
    for log in logs:
        row = [
            log.id,
            (log.timestamp + timedelta(hours=8)).strftime('%Y-%m-%d %H:%M:%S') if log.timestamp else '',
            log.level,
            log.module or '',
            log.source or '',
            log.message,
            log.user.username if log.user else '系统',
            log.ip_address or '',
            log.request_id or ''
        ]
        
        if include_details:
            row.append(json.dumps(json.loads(log.details) if log.details else {}, ensure_ascii=False))
        
        writer.writerow(row)
    
    # 创建响应
    output.seek(0)
    response = make_response(output.getvalue())
    response.headers['Content-Disposition'] = f'attachment; filename=system_logs_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    response.headers['Content-Type'] = 'text/csv; charset=utf-8'
    
    return response

def export_logs_json(logs, include_details):
    """导出为JSON格式"""
    logs_data = []
    for log in logs:
        log_data = log.to_dict()
        if not include_details:
            log_data.pop('details', None)
        logs_data.append(log_data)
    
    response = make_response(json.dumps(logs_data, ensure_ascii=False, indent=2))
    response.headers['Content-Disposition'] = f'attachment; filename=system_logs_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
    response.headers['Content-Type'] = 'application/json; charset=utf-8'
    
    return response

def export_logs_txt(logs, include_details):
    """导出为文本格式"""
    output = io.StringIO()
    
    for log in logs:
        output.write(f"日志ID: {log.id}\n")
        output.write(f"时间: {(log.timestamp + timedelta(hours=8)).strftime('%Y-%m-%d %H:%M:%S') if log.timestamp else ''}\n")
        output.write(f"级别: {log.level}\n")
        output.write(f"模块: {log.module or 'N/A'}\n")
        output.write(f"来源: {log.source or 'N/A'}\n")
        output.write(f"消息: {log.message}\n")
        output.write(f"用户: {log.user.username if log.user else '系统'}\n")
        output.write(f"IP地址: {log.ip_address or 'N/A'}\n")
        output.write(f"请求ID: {log.request_id or 'N/A'}\n")
        
        if include_details and log.details:
            details = json.loads(log.details)
            output.write(f"详细数据: {json.dumps(details, ensure_ascii=False, indent=2)}\n")
        
        output.write("-" * 80 + "\n\n")
    
    output.seek(0)
    response = make_response(output.getvalue())
    response.headers['Content-Disposition'] = f'attachment; filename=system_logs_{datetime.now().strftime("%Y%m%d_%H%M%S")}.txt'
    response.headers['Content-Type'] = 'text/plain; charset=utf-8'
    
    return response

# API: 获取日志统计信息
@config_bp.route('/api/logs/stats')
@login_required
@permission_required('system:admin')
def get_log_stats():
    """获取日志统计信息"""
    # 获取时间范围参数
    days = request.args.get('days', 7, type=int)
    
    # 计算时间范围
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=days)
    
    # 按级别统计
    level_stats = db.session.query(
        SystemLog.level,
        func.count(SystemLog.id).label('count')
    ).filter(
        SystemLog.timestamp >= start_date,
        SystemLog.timestamp <= end_date
    ).group_by(SystemLog.level).all()
    
    # 按模块统计
    module_stats = db.session.query(
        SystemLog.module,
        func.count(SystemLog.id).label('count')
    ).filter(
        SystemLog.timestamp >= start_date,
        SystemLog.timestamp <= end_date
    ).group_by(SystemLog.module).order_by(func.count(SystemLog.id).desc()).limit(10).all()
    
    # 按日期统计
    date_stats = db.session.query(
        func.date(SystemLog.timestamp).label('date'),
        func.count(SystemLog.id).label('count')
    ).filter(
        SystemLog.timestamp >= start_date,
        SystemLog.timestamp <= end_date
    ).group_by(func.date(SystemLog.timestamp)).order_by(func.date(SystemLog.timestamp)).all()
    
    return jsonify({
        'level_stats': {level: count for level, count in level_stats},
        'module_stats': {module: count for module, count in module_stats if module},
        'date_stats': [{'date': str(date), 'count': count} for date, count in date_stats],
        'total_logs': sum(count for _, count in level_stats)
    })


#=============

@config_bp.route('/audit-logs')
@login_required
@permission_required('system:admin')
def audit_logs():
    """审计日志页面"""
    page = request.args.get('page', 1, type=int)
    action = request.args.get('action', '')
    resource_type = request.args.get('resource_type', '')
    user_id = request.args.get('user_id', type=int)
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    
    query = AuditLog.query
    
    if action:
        query = query.filter(AuditLog.action == action)
    if resource_type:
        query = query.filter(AuditLog.resource_type == resource_type)
    if user_id:
        query = query.filter(AuditLog.user_id == user_id)
    if start_date:
        query = query.filter(AuditLog.timestamp >= start_date)
    if end_date:
        query = query.filter(AuditLog.timestamp <= end_date)
    
    logs = query.order_by(AuditLog.timestamp.desc()).paginate(page=page, per_page=50, error_out=False)
    
    # 获取选项
    from models.models import User
    users = User.query.all()
    actions = db.session.query(AuditLog.action).distinct().all()
    resource_types = db.session.query(AuditLog.resource_type).distinct().all()
    
    return render_template('config/audit_logs.html',
                         logs=logs,
                         users=users,
                         actions=[a[0] for a in actions],
                         resource_types=[r[0] for r in resource_types],
                         current_action=action,
                         current_resource_type=resource_type,
                         current_user_id=user_id,
                         start_date=start_date,
                         end_date=end_date)
# API: 获取单个审计日志详情
@config_bp.route('/api/audit-logs/<int:log_id>')
@login_required
@permission_required('system:admin')
def get_audit_log_details(log_id):
    """获取单个审计日志的详细信息"""
    log = AuditLog.query.get_or_404(log_id)
    return jsonify(log.to_dict())

# API: 获取审计日志的详细数据
@config_bp.route('/api/audit-logs/<int:log_id>/details')
@login_required
@permission_required('system:admin')
def get_audit_log_details_data(log_id):
    """获取审计日志的详细数据（JSON格式）"""
    log = AuditLog.query.get_or_404(log_id)
    return jsonify({
        'details': json.loads(log.details) if log.details else {}
    })

# API: 获取审计日志的变更记录
@config_bp.route('/api/audit-logs/<int:log_id>/changes')
@login_required
@permission_required('system:admin')
def get_audit_log_changes(log_id):
    """获取审计日志的变更记录（JSON格式）"""
    log = AuditLog.query.get_or_404(log_id)
    return jsonify({
        'changes': json.loads(log.changes) if log.changes else {}
    })

# API: 删除审计日志
@config_bp.route('/api/audit-logs/<int:log_id>', methods=['DELETE'])
@login_required
@permission_required('system:admin')
#@admin_required  # 假设需要管理员权限
def delete_audit_log(log_id):
    """删除审计日志记录（需要管理员权限）"""
    log = AuditLog.query.get_or_404(log_id)
    
    # 记录删除操作到系统日志
    admin_log = SystemLog(
        level='warning',
        module='audit_logs',
        source='API',
        message=f"管理员 {current_user.username} 删除了审计记录 ID: {log_id}",
        details=json.dumps({
            'deleted_audit_log': log.to_dict(),
            'deleted_by': current_user.username,
            'deleted_at': datetime.utcnow().isoformat()
        }),
        user_id=current_user.id,
        ip_address=request.remote_addr,
        request_id=request.headers.get('X-Request-ID', '')
    )
    db.session.add(admin_log)
    
    log_audit('delete', 'audit_log', log_id,
              f"删除审计日志: ID {log_id}",
              details={'deleted_log_id': log_id, 'deleted_resource': log.resource_type})

    db.session.delete(log)
    db.session.commit()

    return jsonify({'success': True, 'message': '审计日志已删除'})

# API: 导出审计日志
@config_bp.route('/api/audit-logs/export')
@login_required
@permission_required('system:admin')
def export_audit_logs():
    """导出审计日志数据"""
    # 获取筛选参数
    action = request.args.get('action', '')
    resource_type = request.args.get('resource_type', '')
    user_id = request.args.get('user_id', type=int)
    resource_id = request.args.get('resource_id', '')
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    search = request.args.get('search', '')
    export_format = request.args.get('format', 'csv')
    limit = request.args.get('limit', 1000, type=int)
    include_details = request.args.get('include_details', 'true') == 'true'
    include_changes = request.args.get('include_changes', 'true') == 'true'
    
    # 构建查询
    query = AuditLog.query
    
    if action:
        query = query.filter(AuditLog.action == action)
    if resource_type:
        query = query.filter(AuditLog.resource_type == resource_type)
    if user_id:
        query = query.filter(AuditLog.user_id == user_id)
    if resource_id:
        query = query.filter(AuditLog.resource_id == resource_id)
    if start_date:
        query = query.filter(AuditLog.timestamp >= start_date)
    if end_date:
        query = query.filter(AuditLog.timestamp <= end_date)
    if search:
        search_filter = or_(
            AuditLog.message.ilike(f'%{search}%'),
            AuditLog.ip_address.ilike(f'%{search}%'),
            AuditLog.user_agent.ilike(f'%{search}%'),
            AuditLog.resource_id.ilike(f'%{search}%')
        )
        query = query.filter(search_filter)
    
    # 限制数量
    if limit > 0:
        logs = query.order_by(AuditLog.timestamp.desc()).limit(limit).all()
    else:
        logs = query.order_by(AuditLog.timestamp.desc()).all()
    
    # 根据格式导出
    if export_format == 'csv':
        return export_audit_logs_csv(logs, include_details, include_changes)
    elif export_format == 'json':
        return export_audit_logs_json(logs, include_details, include_changes)
    else:  # txt
        return export_audit_logs_txt(logs, include_details, include_changes)

def export_audit_logs_csv(logs, include_details, include_changes):
    """导出为CSV格式"""
    output = io.StringIO()
    writer = csv.writer(output)
    
    # 写入标题行
    headers = ['ID', '时间', '操作', '资源类型', '资源ID', '用户', 'IP地址', '消息', '状态', '请求方法', '请求路径']
    if include_details:
        headers.append('详细数据')
    if include_changes:
        headers.append('变更记录')
    writer.writerow(headers)
    
    # 写入数据行
    for log in logs:
        row = [
            log.id,
            log.local_timestamp.strftime('%Y-%m-%d %H:%M:%S') if log.local_timestamp else '',
            log.action,
            log.resource_type or '',
            log.resource_id or '',
            log.user.username if log.user else '系统',
            log.ip_address or '',
            log.message,
            log.status or '',
            log.request_method or '',
            log.request_path or ''
        ]
        
        if include_details:
            row.append(json.dumps(json.loads(log.details) if log.details else {}, ensure_ascii=False))
        if include_changes:
            row.append(json.dumps(json.loads(log.changes) if log.changes else {}, ensure_ascii=False))
        
        writer.writerow(row)
    
    # 创建响应
    output.seek(0)
    response = make_response(output.getvalue())
    response.headers['Content-Disposition'] = f'attachment; filename=audit_logs_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    response.headers['Content-Type'] = 'text/csv; charset=utf-8'
    
    return response

def export_audit_logs_json(logs, include_details, include_changes):
    """导出为JSON格式"""
    logs_data = []
    for log in logs:
        log_data = log.to_dict()
        if not include_details:
            log_data.pop('details', None)
        if not include_changes:
            log_data.pop('changes', None)
        logs_data.append(log_data)
    
    response = make_response(json.dumps(logs_data, ensure_ascii=False, indent=2))
    response.headers['Content-Disposition'] = f'attachment; filename=audit_logs_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
    response.headers['Content-Type'] = 'application/json; charset=utf-8'
    
    return response

def export_audit_logs_txt(logs, include_details, include_changes):
    """导出为文本格式"""
    output = io.StringIO()
    
    for log in logs:
        output.write(f"审计记录ID: {log.id}\n")
        output.write(f"时间: {log.local_timestamp.strftime('%Y-%m-%d %H:%M:%S') if log.local_timestamp else ''}\n")
        output.write(f"操作: {log.action}\n")
        output.write(f"资源类型: {log.resource_type or 'N/A'}\n")
        output.write(f"资源ID: {log.resource_id or 'N/A'}\n")
        output.write(f"用户: {log.user.username if log.user else '系统'}\n")
        output.write(f"IP地址: {log.ip_address or 'N/A'}\n")
        output.write(f"消息: {log.message}\n")
        output.write(f"状态: {log.status or 'N/A'}\n")
        output.write(f"请求方法: {log.request_method or 'N/A'}\n")
        output.write(f"请求路径: {log.request_path or 'N/A'}\n")
        
        if include_details and log.details:
            details = json.loads(log.details)
            output.write(f"详细数据: {json.dumps(details, ensure_ascii=False, indent=2)}\n")
        
        if include_changes and log.changes:
            changes = json.loads(log.changes)
            output.write(f"变更记录: {json.dumps(changes, ensure_ascii=False, indent=2)}\n")
        
        output.write("-" * 80 + "\n\n")
    
    output.seek(0)
    response = make_response(output.getvalue())
    response.headers['Content-Disposition'] = f'attachment; filename=audit_logs_{datetime.now().strftime("%Y%m%d_%H%M%S")}.txt'
    response.headers['Content-Type'] = 'text/plain; charset=utf-8'
    
    return response

# API: 获取审计日志统计信息
@config_bp.route('/api/audit-logs/stats')
@login_required
@permission_required('system:admin')
def get_audit_log_stats():
    """获取审计日志统计信息"""
    # 获取时间范围参数
    days = request.args.get('days', 7, type=int)
    
    # 计算时间范围
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=days)
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    
    # 按操作类型统计
    action_stats = db.session.query(
        AuditLog.action,
        func.count(AuditLog.id).label('count')
    ).filter(
        AuditLog.timestamp >= start_date,
        AuditLog.timestamp <= end_date
    ).group_by(AuditLog.action).all()
    
    # 按资源类型统计
    resource_stats = db.session.query(
        AuditLog.resource_type,
        func.count(AuditLog.id).label('count')
    ).filter(
        AuditLog.timestamp >= start_date,
        AuditLog.timestamp <= end_date
    ).group_by(AuditLog.resource_type).order_by(func.count(AuditLog.id).desc()).limit(10).all()
    
    # 按日期统计
    date_stats = db.session.query(
        func.date(AuditLog.timestamp).label('date'),
        func.count(AuditLog.id).label('count')
    ).filter(
        AuditLog.timestamp >= start_date,
        AuditLog.timestamp <= end_date
    ).group_by(func.date(AuditLog.timestamp)).order_by(func.date(AuditLog.timestamp)).all()
    
    # 今日统计
    today_count = db.session.query(func.count(AuditLog.id)).filter(
        AuditLog.timestamp >= today_start
    ).scalar()
    
    # 删除操作统计
    delete_count = db.session.query(func.count(AuditLog.id)).filter(
        AuditLog.timestamp >= start_date,
        AuditLog.timestamp <= end_date,
        AuditLog.action == 'delete'
    ).scalar()
    
    # 唯一用户统计
    unique_users_count = db.session.query(
        func.count(func.distinct(AuditLog.user_id))
    ).filter(
        AuditLog.timestamp >= start_date,
        AuditLog.timestamp <= end_date
    ).scalar()
    
    # 按用户统计
    user_stats = db.session.query(
        AuditLog.user_id,
        User.username,
        func.count(AuditLog.id).label('count')
    ).join(
        User, AuditLog.user_id == User.id
    ).filter(
        AuditLog.timestamp >= start_date,
        AuditLog.timestamp <= end_date
    ).group_by(AuditLog.user_id, User.username).order_by(func.count(AuditLog.id).desc()).limit(10).all()
    
    return jsonify({
        'action_stats': {action: count for action, count in action_stats},
        'resource_stats': {resource_type: count for resource_type, count in resource_stats if resource_type},
        'date_stats': [{'date': str(date), 'count': count} for date, count in date_stats],
        'user_stats': [{'user_id': user_id, 'username': username, 'count': count} for user_id, username, count in user_stats],
        'today_count': today_count,
        'delete_count': delete_count,
        'unique_users_count': unique_users_count or 0,
        'total_logs': sum(count for _, count in action_stats)
    })

# API: 获取资源的时间线
@config_bp.route('/api/audit-logs/timeline')
@login_required
@permission_required('system:admin')
def get_resource_timeline():
    """获取特定资源的时间线审计记录"""
    resource_type = request.args.get('resource_type', '')
    resource_id = request.args.get('resource_id', '')
    
    if not resource_type or not resource_id:
        return jsonify({'error': '资源类型和资源ID不能为空'}), 400
    
    logs = AuditLog.query.filter(
        AuditLog.resource_type == resource_type,
        AuditLog.resource_id == resource_id
    ).order_by(AuditLog.timestamp.asc()).limit(100).all()
    
    return jsonify({
        'resource_type': resource_type,
        'resource_id': resource_id,
        'logs': [log.to_dict() for log in logs]
    })

# API: 批量删除审计日志
@config_bp.route('/api/audit-logs/batch-delete', methods=['POST'])
@login_required
@permission_required('system:admin')
#@admin_required
def batch_delete_audit_logs():
    """批量删除审计日志（需要管理员权限）"""
    data = request.get_json()
    log_ids = data.get('log_ids', [])
    
    if not log_ids:
        return jsonify({'error': '请选择要删除的日志'}), 400
    
    # 记录批量删除操作
    admin_log = SystemLog(
        level='warning',
        module='audit_logs',
        source='API',
        message=f"管理员 {current_user.username} 批量删除了 {len(log_ids)} 条审计记录",
        details=json.dumps({
            'deleted_log_ids': log_ids,
            'deleted_by': current_user.username,
            'deleted_at': datetime.utcnow().isoformat()
        }),
        user_id=current_user.id,
        ip_address=request.remote_addr,
        request_id=request.headers.get('X-Request-ID', '')
    )
    db.session.add(admin_log)
    
    # 批量删除
    deleted_count = AuditLog.query.filter(AuditLog.id.in_(log_ids)).delete(synchronize_session=False)
    db.session.commit()

    log_audit('delete', 'audit_log', 0,
              f"批量删除 {deleted_count} 条审计日志",
              details={'deleted_ids': log_ids, 'deleted_count': deleted_count})

    return jsonify({
        'success': True,
        'message': f'成功删除 {deleted_count} 条审计记录',
        'deleted_count': deleted_count
    })


@config_bp.route('/log-settings')
@login_required
@permission_required('config:view')
def log_settings():
    """日志设置页面"""
    settings = LogSetting.query.order_by(LogSetting.log_type).all()
    return render_template('config/log_settings.html', settings=settings)

@config_bp.route('/api/log-settings', methods=['GET'])
@login_required
@permission_required('config:view')
def get_log_settings():
    """获取日志设置"""
    settings = LogSetting.query.all()
    return jsonify([s.to_dict() for s in settings])

@config_bp.route('/api/log-settings/<int:setting_id>', methods=['PUT'])
@login_required
@permission_required('config:edit')
def update_log_setting(setting_id):
    """更新日志设置"""
    setting = LogSetting.query.get_or_404(setting_id)
    data = request.get_json()
    
    for key in ['enabled', 'level', 'retention_days', 'max_file_size', 
                'max_files', 'output_format']:
        if key in data:
            setattr(setting, key, data[key])
    
    if 'destinations' in data:
        setting.destinations = json.dumps(data['destinations'])
    
    if 'filters' in data:
        setting.filters = json.dumps(data['filters'])
    
    setting.updated_at = datetime.utcnow()
    db.session.commit()
    
    log_audit('update', 'log_setting', setting.id, f"更新日志设置: {setting.log_type}")
    
    return jsonify({'success': True, 'message': '日志设置已更新'})

# ========== API与集成 ==========

@config_bp.route('/api-settings')
@login_required
@permission_required('config:view')
def api_settings():
    """API设置页面"""
    settings = APISetting.query.order_by(APISetting.name).all()
    return render_template('config/api_settings.html', settings=settings)

@config_bp.route('/api/api-settings/<int:setting_id>', methods=['GET'])
@login_required
@permission_required('config:view')
def get_api_setting(setting_id):
    """获取单个API设置"""
    setting = APISetting.query.get_or_404(setting_id)
    return jsonify(setting.to_dict())

@config_bp.route('/api/api-settings', methods=['POST'])
@login_required
@permission_required('config:edit')
def create_api_setting():
    """创建API设置"""
    import secrets
    import string
    
    data = request.get_json()
    
    # 生成API Key
    alphabet = string.ascii_letters + string.digits
    api_key = ''.join(secrets.choice(alphabet) for _ in range(32))
    
    setting = APISetting(
        name=data.get('name'),
        api_key=api_key,
        secret_key=data.get('secret_key', ''),
        enabled=data.get('enabled', True),
        rate_limit=data.get('rate_limit', 100),
        rate_limit_period=data.get('rate_limit_period', 60),
        allowed_ips=json.dumps(data.get('allowed_ips', [])),
        allowed_methods=json.dumps(data.get('allowed_methods', ['GET', 'POST'])),
        allowed_endpoints=json.dumps(data.get('allowed_endpoints', [])),
        permissions=json.dumps(data.get('permissions', {})),
        expires_at=data.get('expires_at'),
        description=data.get('description')
    )
    
    db.session.add(setting)
    db.session.commit()
    
    log_audit('create', 'api_setting', setting.id, f"创建API设置: {setting.name}")
    
    return jsonify({
        'success': True, 
        'message': 'API设置已创建', 
        'id': setting.id,
        'api_key': api_key  # 只在这里返回一次
    })

@config_bp.route('/api/api-settings/<int:setting_id>', methods=['PUT'])
@login_required
@permission_required('config:edit')
def update_api_setting(setting_id):
    """更新API设置"""
    setting = APISetting.query.get_or_404(setting_id)
    data = request.get_json()
    
    for key in ['name', 'enabled', 'rate_limit', 'rate_limit_period', 'description']:
        if key in data:
            setattr(setting, key, data[key])
    
    # 处理可选字段
    if 'secret_key' in data and data['secret_key']:
        setting.secret_key = data['secret_key']
    
    if 'expires_at' in data:
        if data['expires_at']:
            setting.expires_at = datetime.fromisoformat(data['expires_at'].replace('Z', '+00:00'))
        else:
            setting.expires_at = None
    
    # 处理JSON字段
    for key in ['allowed_ips', 'allowed_methods', 'allowed_endpoints', 'permissions']:
        if key in data:
            setattr(setting, key, json.dumps(data[key]))
    
    setting.updated_at = datetime.utcnow()
    db.session.commit()
    
    log_audit('update', 'api_setting', setting.id, f"更新API设置: {setting.name}")
    
    return jsonify({'success': True, 'message': 'API设置已更新'})

@config_bp.route('/api/api-settings/<int:setting_id>/status', methods=['PUT'])
@login_required
@permission_required('config:edit')
def update_api_setting_status(setting_id):
    """更新API设置状态"""
    setting = APISetting.query.get_or_404(setting_id)
    data = request.get_json()
    
    if 'enabled' in data:
        setting.enabled = data['enabled']
        setting.updated_at = datetime.utcnow()
        db.session.commit()
        
        action = '启用' if setting.enabled else '禁用'
        log_audit('update', 'api_setting', setting.id, f"{action}API设置: {setting.name}")
        
        return jsonify({'success': True, 'message': f'API设置已{action}'})
    
    return jsonify({'success': False, 'message': '无效的请求'}), 400

@config_bp.route('/integration-settings')
@login_required
@permission_required('config:view')
def integration_settings():
    """集成配置页面"""
    integrations = IntegrationSetting.query.order_by(IntegrationSetting.name).all()
    return render_template('config/integration_settings.html', integrations=integrations)

@config_bp.route('/api/integration-settings', methods=['GET'])
@login_required
@permission_required('config:view')
def get_integration_settings():
    """获取集成配置"""
    settings = IntegrationSetting.query.all()
    return jsonify([s.to_dict() for s in settings])

@config_bp.route('/api/integration-settings', methods=['POST'])
@login_required
@permission_required('config:edit')
def create_integration_setting():
    """创建集成配置"""
    data = request.get_json()
    
    # 验证必填字段
    if not data.get('name') or not data.get('integration_type') or not data.get('provider'):
        return jsonify({'success': False, 'message': '缺少必填字段'}), 400
    
    # 创建集成配置
    integration = IntegrationSetting(
        name=data.get('name'),
        integration_type=data.get('integration_type'),
        provider=data.get('provider'),
        config=json.dumps(data.get('config', {})),
        enabled=data.get('enabled', True),
        sync_enabled=data.get('sync_enabled', False),
        sync_direction=data.get('sync_direction', 'bidirectional'),
        sync_interval=data.get('sync_interval', 300),
        description=data.get('description')
    )
    
    db.session.add(integration)
    db.session.commit()
    
    log_audit('create', 'integration_setting', integration.id, f"创建集成配置: {integration.name}")
    
    return jsonify({
        'success': True, 
        'message': '集成配置已创建', 
        'id': integration.id
    })

@config_bp.route('/api/integration-settings/<int:setting_id>', methods=['GET'])
@login_required
@permission_required('config:view')
def get_integration_setting(setting_id):
    """获取单个集成配置"""
    setting = IntegrationSetting.query.get_or_404(setting_id)
    return jsonify(setting.to_dict())

@config_bp.route('/api/integration-settings/<int:setting_id>', methods=['PUT'])
@login_required
@permission_required('config:edit')
def update_integration_setting(setting_id):
    """更新集成配置"""
    setting = IntegrationSetting.query.get_or_404(setting_id)
    data = request.get_json()
    
    for key in ['name', 'enabled', 'sync_enabled', 'sync_direction', 
                'sync_interval', 'description']:
        if key in data:
            setattr(setting, key, data[key])
    
    # 处理配置
    if 'config' in data:
        setting.config = json.dumps(data['config'])
    
    setting.updated_at = datetime.utcnow()
    db.session.commit()
    
    log_audit('update', 'integration_setting', setting.id, f"更新集成配置: {setting.name}")
    
    return jsonify({'success': True, 'message': '集成配置已更新'})

@config_bp.route('/api/integration-settings/<int:setting_id>/status', methods=['PUT'])
@login_required
@permission_required('config:edit')
def update_integration_setting_status(setting_id):
    """更新集成配置状态"""
    setting = IntegrationSetting.query.get_or_404(setting_id)
    data = request.get_json()
    
    if 'enabled' in data:
        setting.enabled = data['enabled']
        setting.updated_at = datetime.utcnow()
        db.session.commit()
        
        action = '启用' if setting.enabled else '禁用'
        log_audit('update', 'integration_setting', setting.id, f"{action}集成配置: {setting.name}")
        
        return jsonify({'success': True, 'message': f'集成配置已{action}'})
    
    return jsonify({'success': False, 'message': '无效的请求'}), 400

@config_bp.route('/api/integration-settings/<int:setting_id>/test', methods=['POST'])
@login_required
@permission_required('config:edit')
def test_integration_setting(setting_id):
    """测试集成连接"""
    setting = IntegrationSetting.query.get_or_404(setting_id)
    
    # 这里应该实现实际的集成连接测试逻辑
    # 根据集成类型和提供商调用相应的API进行测试
    
    # 示例：模拟测试结果
    import random
    success = random.choice([True, False])
    
    if success:
        return jsonify({
            'success': True,
            'message': f'成功连接到 {setting.provider} {setting.integration_type}'
        })
    else:
        return jsonify({
            'success': False,
            'message': f'连接到 {setting.provider} {setting.integration_type} 失败',
            'details': {'error': '连接超时', 'code': 408}
        })

@config_bp.route('/api/integration-settings/<int:setting_id>/sync', methods=['POST'])
@login_required
@permission_required('config:edit')
def trigger_integration_sync(setting_id):
    """触发集成同步"""
    setting = IntegrationSetting.query.get_or_404(setting_id)
    
    if not setting.enabled or not setting.sync_enabled:
        return jsonify({'success': False, 'message': '集成未启用或同步未启用'}), 400
    
    # 这里应该实现实际的同步逻辑
    # 根据集成类型和提供商调用相应的API进行同步
    
    # 更新同步状态
    setting.last_sync_at = datetime.utcnow()
    setting.last_sync_status = 'success'
    db.session.commit()
    
    log_audit('sync', 'integration_setting', setting.id, f"手动触发集成同步: {setting.name}")
    
    return jsonify({
        'success': True,
        'message': '集成同步已触发'
    })

# ========== 辅助函数 ==========


def log_system(level, module, message, details=None, user_id=None):
    """记录系统日志"""
    system_log = SystemLog(
        level=level,
        module=module,
        message=message,
        details=json.dumps(details) if details else None,
        user_id=user_id or (current_user.id if current_user.is_authenticated else None),
        ip_address=request.remote_addr,
        request_id=request.headers.get('X-Request-ID')
    )
    
    db.session.add(system_log)
    db.session.commit()


@config_bp.route('/update-system-setting', methods=['POST'])
def update_system_setting():
    """处理单个系统设置的更新（AJAX 调用）"""
    data = request.get_json()
    if not data:
        return jsonify(success=False, message='无效的请求数据'), 400

    key = data.get('key')
    value = data.get('value')

    if not key:
        return jsonify(success=False, message='缺少参数 key'), 400

    setting = SystemSetting.query.filter_by(key=key).first()
    if not setting:
        return jsonify(success=False, message='设置项不存在'), 404

    # 可选：检查是否可编辑（is_public 字段）
    if hasattr(setting, 'is_public') and not setting.is_public:
        return jsonify(success=False, message='该项不允许编辑'), 403

    setting.value = value
    db.session.commit()

    log_audit('update', 'system_setting', key,
              f"更新系统设置: {key}={value}",
              details={'key': key, 'value': value})

    # 可以记录日志等
    current_app.logger.info(f'系统设置 [{key}] 已更新为: {value}')

    return jsonify(success=True)

@config_bp.route('/api/backup-configs', methods=['POST'])
@login_required
@permission_required('system:admin')
def create_backup_config():
    data = request.get_json()
    # 验证和创建配置...

    log_audit('create', 'backup_config', 0,
              "创建备份配置",
              details={'name': data.get('name', '') if data else ''})

    return jsonify(new_config.to_dict()), 201

@config_bp.route('/api/backup-configs/<int:config_id>', methods=['PUT'])
@login_required
@permission_required('system:admin')
def update_backup_config(config_id):
    config = BackupConfig.query.get_or_404(config_id)
    data = request.get_json()
    # 更新配置...
    db.session.commit()

    log_audit('update', 'backup_config', config.id,
              f"更新备份配置: {config.name}",
              details={'name': config.name})

    return jsonify(config.to_dict())

#from your_app.tasks import run_backup_task, restore_backup_task  # 假设异步任务存在（可选）

@config_bp.route('/api/backup-configs/<int:config_id>/run', methods=['POST'])
@login_required
@permission_required('system:admin')
def run_backup(config_id):
    """
    立即执行指定备份配置的备份任务
    ---
    参数:
        config_id: 备份配置ID (路径参数)
    返回:
        202 Accepted: 任务已触发
        404 Not Found: 配置不存在
    """
    config = BackupConfig.query.get_or_404(config_id)
    # 此处可触发异步任务（例如 Celery），避免阻塞请求
    # run_backup_task.delay(config.id)
    current_app.logger.info(f"立即备份任务已触发，配置ID: {config.id}, 名称: {config.name}")
    # 更新最后备份时间和状态（可根据实际任务进度另行处理）
    # config.last_backup_at = datetime.utcnow()
    # config.last_backup_status = 'running'
    # db.session.commit()

    log_audit('execute', 'backup', config.id,
              f"执行备份: {config.name}",
              details={'config_id': config.id, 'config_name': config.name})

    return jsonify({
        "message": "备份任务已触发",
        "config_id": config.id,
        "config_name": config.name
    }), 202


@config_bp.route('/api/backup-configs/<int:config_id>/restore', methods=['POST'])
@login_required
@permission_required('system:admin')
def restore_backup(config_id):
    """
    从指定备份配置的最近一次备份中恢复数据
    ---
    参数:
        config_id: 备份配置ID (路径参数)
    返回:
        202 Accepted: 恢复任务已触发
        404 Not Found: 配置不存在
    """
    config = BackupConfig.query.get_or_404(config_id)
    # 触发恢复任务（通常需要指定备份文件，此处简化为使用最近备份）
    # restore_backup_task.delay(config.id)
    current_app.logger.info(f"恢复任务已触发，配置ID: {config.id}, 名称: {config.name}")

    log_audit('execute', 'backup', config.id,
              f"执行恢复: {config.name}",
              details={'config_id': config.id, 'config_name': config.name})

    return jsonify({
        "message": "恢复任务已触发",
        "config_id": config.id,
        "config_name": config.name
    }), 202


@config_bp.route('/api/backup-configs/<int:config_id>', methods=['DELETE'])
@login_required
@permission_required('system:admin')
def delete_backup_config(config_id):
    """
    删除指定的备份配置（不删除已生成的备份文件）
    ---
    参数:
        config_id: 备份配置ID (路径参数)
    返回:
        200 OK: 删除成功
        404 Not Found: 配置不存在
    """
    config = BackupConfig.query.get_or_404(config_id)

    log_audit('delete', 'backup_config', config.id,
              f"删除备份配置: {config.name}",
              details={'config_id': config.id, 'config_name': config.name})

    db.session.delete(config)
    db.session.commit()
    current_app.logger.info(f"备份配置已删除，ID: {config.id}, 名称: {config.name}")
    return jsonify({
        "message": "备份配置已删除",
        "config_id": config.id
    }), 200


@config_bp.route('/api/alert-config-templates', methods=['GET'])
def get_alert_templates():
    """获取所有告警模板（JSON）"""
    templates = AlertConfigTemplate.query.all()
    return jsonify([t.to_dict() for t in templates])

@config_bp.route('/api/alert-config-templates/<int:template_id>', methods=['GET'])
def get_alert_template(template_id):
    """获取单个告警模板（JSON）"""
    template = AlertConfigTemplate.query.get_or_404(template_id)
    return jsonify(template.to_dict())

@config_bp.route('/api/alert-config-templates', methods=['POST'])
def create_alert_template():
    """创建告警模板"""
    data = request.get_json()
    # 此处应有数据验证和创建逻辑
    template = AlertConfigTemplate(
        name=data['name'],
        description=data.get('description'),
        severity=data['severity'],
        alert_type=data['alert_type'],
        match_conditions=json.dumps(data.get('match_conditions', [])),
        notification_channels=json.dumps(data.get('notification_channels', [])),
        actions=json.dumps(data.get('actions', [])),
        auto_acknowledge=data.get('auto_acknowledge', False),
        auto_resolve=data.get('auto_resolve', False),
        enabled=data.get('enabled', True),
        is_default=data.get('is_default', False)
    )
    db.session.add(template)
    db.session.commit()

    log_audit('create', 'alert_template', template.id,
              f"创建告警模板: {template.name}",
              details={'name': template.name, 'severity': template.severity, 'alert_type': template.alert_type})

    return jsonify(template.to_dict()), 201

@config_bp.route('/api/alert-config-templates/<int:template_id>', methods=['PUT'])
def update_alert_template(template_id):
    """更新告警模板"""
    template = AlertConfigTemplate.query.get_or_404(template_id)
    data = request.get_json()
    # 更新字段
    template.name = data.get('name', template.name)
    template.description = data.get('description', template.description)
    template.severity = data.get('severity', template.severity)
    template.alert_type = data.get('alert_type', template.alert_type)
    template.match_conditions = json.dumps(data.get('match_conditions', json.loads(template.match_conditions or '[]')))
    template.notification_channels = json.dumps(data.get('notification_channels', json.loads(template.notification_channels or '[]')))
    template.actions = json.dumps(data.get('actions', json.loads(template.actions or '[]')))
    template.auto_acknowledge = data.get('auto_acknowledge', template.auto_acknowledge)
    template.auto_resolve = data.get('auto_resolve', template.auto_resolve)
    template.enabled = data.get('enabled', template.enabled)
    template.is_default = data.get('is_default', template.is_default)
    db.session.commit()

    log_audit('update', 'alert_template', template.id,
              f"更新告警模板: {template.name}",
              details={'name': template.name, 'severity': template.severity})

    return jsonify(template.to_dict())

@config_bp.route('/api/alert-config-templates/<int:template_id>', methods=['DELETE'])
def delete_alert_template(template_id):
    """删除告警模板"""
    template = AlertConfigTemplate.query.get_or_404(template_id)

    log_audit('delete', 'alert_template', template.id,
              f"删除告警模板: {template.name}",
              details={'name': template.name})

    db.session.delete(template)
    db.session.commit()
    return '', 204


@config_bp.route('/notification-templates', methods=['POST'])
@login_required
@permission_required('config:edit')
def create_notification_template():
    data = request.get_json()
    # 创建模板逻辑
    template = NotificationTemplate(
        name=data['name'],
        description=data.get('description'),
        notification_type=data['notification_type'],
        template_content=data['template_content'],
        variables=json.dumps(data.get('variables', [])),
        enabled=data.get('enabled', True),
        is_default=data.get('is_default', False)
    )
    db.session.add(template)
    db.session.commit()

    log_audit('create', 'notification_template', template.id,
              f"创建通知模板: {template.name}",
              details={'name': template.name, 'notification_type': template.notification_type})

    return jsonify({'success': True, 'id': template.id})

@config_bp.route('/notification-templates/<int:id>', methods=['PUT'])
@login_required
@permission_required('config:edit')
def update_notification_template(id):
    template = NotificationTemplate.query.get_or_404(id)
    data = request.get_json()
    template.name = data['name']
    template.description = data.get('description')
    template.notification_type = data['notification_type']
    template.template_content = data['template_content']
    template.variables = json.dumps(data.get('variables', []))
    template.enabled = data.get('enabled', True)
    template.is_default = data.get('is_default', False)
    db.session.commit()

    log_audit('update', 'notification_template', template.id,
              f"更新通知模板: {template.name}",
              details={'name': template.name, 'notification_type': template.notification_type})

    return jsonify({'success': True})

@config_bp.route('/notification-templates/<int:id>', methods=['DELETE'])
@login_required
@permission_required('config:edit')
def delete_notification_template(id):
    template = NotificationTemplate.query.get_or_404(id)

    log_audit('delete', 'notification_template', template.id,
              f"删除通知模板: {template.name}",
              details={'name': template.name})

    db.session.delete(template)
    db.session.commit()
    return jsonify({'success': True})


@config_bp.route('/role/add', methods=['POST'])
@login_required
@permission_required('system:admin')
def add_role():
    """新增角色"""
    # CSRF验证（如果前端在header中传递了X-CSRFToken）
    try:
        validate_csrf(request.headers.get('X-CSRFToken'))
    except ValidationError:
        return jsonify({'success': False, 'message': 'CSRF验证失败'}), 400

    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': '无效的请求数据'}), 400

    name = data.get('name', '').strip()
    description = data.get('description', '').strip() or None
    permission_ids = data.get('permission_ids', [])

    # 验证角色名称
    if not name:
        return jsonify({'success': False, 'message': '角色名称不能为空'}), 400

    # 检查名称是否已存在
    existing = Role.query.filter_by(name=name).first()
    if existing:
        return jsonify({'success': False, 'message': '角色名称已存在'}), 400

    # 创建新角色
    role = Role(name=name, description=description)
    
    # 分配权限
    if permission_ids:
        permissions = Permission.query.filter(Permission.id.in_(permission_ids)).all()
        role.permissions = permissions

    try:
        db.session.add(role)
        db.session.commit()

        log_audit('create', 'role', role.id,
                  f"创建角色: {role.name}",
                  details={'name': role.name, 'description': role.description})

        return jsonify({
            'success': True,
            'message': '角色创建成功',
            'role': role.to_dict()  # 返回角色数据以便前端更新
        })
    except IntegrityError:
        db.session.rollback()
        return jsonify({'success': False, 'message': '数据库错误，可能名称重复'}), 500
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'添加角色失败: {str(e)}')
        return jsonify({'success': False, 'message': '服务器内部错误'}), 500


@config_bp.route('/role/update/<int:role_id>', methods=['PUT'])
@login_required
@permission_required('system:admin')
def update_role(role_id):
    """更新角色"""
    # CSRF验证
    try:
        validate_csrf(request.headers.get('X-CSRFToken'))
    except ValidationError:
        return jsonify({'success': False, 'message': 'CSRF验证失败'}), 400

    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': '无效的请求数据'}), 400

    role = Role.query.get(role_id)
    if not role:
        return jsonify({'success': False, 'message': '角色不存在'}), 404

    # 检查是否为系统角色（禁止修改系统角色）
    if role.is_system:
        return jsonify({'success': False, 'message': '系统角色不可修改'}), 403

    name = data.get('name', '').strip()
    description = data.get('description', '').strip() or None
    permission_ids = data.get('permission_ids', [])

    if not name:
        return jsonify({'success': False, 'message': '角色名称不能为空'}), 400

    # 检查名称是否与其他角色冲突
    existing = Role.query.filter(Role.name == name, Role.id != role_id).first()
    if existing:
        return jsonify({'success': False, 'message': '角色名称已存在'}), 400

    # 更新字段
    role.name = name
    role.description = description

    # 更新权限
    if permission_ids is not None:  # 允许传空数组清空权限
        permissions = Permission.query.filter(Permission.id.in_(permission_ids)).all()
        role.permissions = permissions

    try:
        db.session.commit()

        log_audit('update', 'role', role.id,
                  f"更新角色: {role.name}",
                  details={'name': role.name, 'description': role.description})

        return jsonify({
            'success': True,
            'message': '角色更新成功',
            'role': role.to_dict()
        })
    except IntegrityError:
        db.session.rollback()
        return jsonify({'success': False, 'message': '数据库错误'}), 500
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'更新角色失败: {str(e)}')
        return jsonify({'success': False, 'message': '服务器内部错误'}), 500


@config_bp.route('/role/delete/<int:role_id>', methods=['DELETE'])
@login_required
@permission_required('system:admin')
def delete_role(role_id):
    """删除角色"""
    # CSRF验证
    try:
        validate_csrf(request.headers.get('X-CSRFToken'))
    except ValidationError:
        return jsonify({'success': False, 'message': 'CSRF验证失败'}), 400

    role = Role.query.get(role_id)
    if not role:
        return jsonify({'success': False, 'message': '角色不存在'}), 404

    # 禁止删除系统角色
    if role.is_system:
        return jsonify({'success': False, 'message': '系统角色不可删除'}), 403

    # 可选：检查是否有用户关联此角色，如果有则禁止删除或给出提示
    # if role.users and len(role.users) > 0:
    #     return jsonify({'success': False, 'message': '该角色下存在用户，无法删除'}), 400

    try:
        log_audit('delete', 'role', role.id,
                  f"删除角色: {role.name}",
                  details={'name': role.name})

        db.session.delete(role)
        db.session.commit()
        return jsonify({'success': True, 'message': '角色删除成功'})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'删除角色失败: {str(e)}')
        return jsonify({'success': False, 'message': '服务器内部错误'}), 500






@config_bp.route('/api/global-parameters/initialize-defaults', methods=['GET', 'POST'])
#@login_required
def initialize_default_params():
    """
    初始化默认全局参数
    清空当前所有参数，并插入预定义的默认参数列表
    返回 JSON 格式的响应
    """
    try:
        # 预定义的默认参数列表（请根据实际需求修改或扩展）
        default_params = [
            {
                'name': 'site_name',
                'value': '网络资产管理系统',
                'data_type': 'string',
                'category': 'general',
                'description': '站点名称',
                'default_value': '网络资产管理系统',
                'min_value': None,
                'max_value': None,
                'unit': None,
                'enabled': True
            },
            {
                'name': 'items_per_page',
                'value': '20',
                'data_type': 'integer',
                'category': 'ui',
                'description': '每页显示条目数',
                'default_value': '20',
                'min_value': '5',
                'max_value': '100',
                'unit': '条',
                'enabled': True
            },
            {
                'name': 'enable_logging',
                'value': 'true',
                'data_type': 'boolean',
                'category': 'system',
                'description': '是否开启操作日志',
                'default_value': 'true',
                'min_value': None,
                'max_value': None,
                'unit': None,
                'enabled': True
            },
            {
                'name': 'session_timeout',
                'value': '30',
                'data_type': 'integer',
                'category': 'security',
                'description': '会话超时时间（分钟）',
                'default_value': '30',
                'min_value': '5',
                'max_value': '1440',
                'unit': '分钟',
                'enabled': True
            },
            {
                'name': 'enable_2fa',
                'value': 'false',
                'data_type': 'boolean',
                'category': 'security',
                'description': '是否开启双因素认证',
                'default_value': 'false',
                'min_value': None,
                'max_value': None,
                'unit': None,
                'enabled': True
            },
            # 继续添加更多默认参数...
        ]

        # 清空现有所有参数（注意：这会永久删除所有记录，请根据业务需求决定是否清空）
        GlobalParameter.query.delete()
        
        # 插入默认参数
        for param_data in default_params:
            # 创建模型实例（id 自动生成，created_at/updated_at 有默认值）
            param = GlobalParameter(**param_data)
            db.session.add(param)
        
        db.session.commit()

        log_audit('create', 'global_parameter', 0,
                  f"初始化默认全局参数",
                  details={'total': len(default_params), 'enabled_count': len([p for p in default_params if p['enabled']])})

        # 记录操作日志（可选）
        current_app.logger.info(f"用户 {current_user.username} 初始化了全局默认参数")

        return jsonify({
            'success': True,
            'message': '默认参数初始化成功',
            'stats': {
                'total': len(default_params),
                'enabled_count': len([p for p in default_params if p['enabled']])
            }
        })
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"初始化默认参数失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'初始化失败: {str(e)}'
        }), 500