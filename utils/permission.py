"""权限检查工具 - 装饰器 + 辅助函数"""
from functools import wraps
from flask import abort, jsonify, request
from flask_login import current_user
from extensions import db


def has_permission(user, permission_code):
    """检查用户是否拥有指定权限"""
    if not getattr(user, 'is_authenticated', False):
        return False
    if user.role == 'admin':
        return True
    # 延迟导入避免循环引用
    from models.config_models import UserRole, Role, Permission, role_permissions
    # 先通过 UserRole 桥接表查询
    role_ids = db.session.query(UserRole.role_id).filter_by(user_id=user.id).subquery()
    result = db.session.query(
        db.session.query(role_permissions).join(
            Permission, Permission.id == role_permissions.c.permission_id
        ).filter(
            role_permissions.c.role_id.in_(db.session.query(role_ids)),
            Permission.code == permission_code
        ).exists()
    ).scalar()
    if result:
        return True
    # 回退：通过 user.role 字符串字段查找对应的角色权限
    role = Role.query.filter_by(name=user.role).first()
    if role:
        return db.session.query(
            db.session.query(role_permissions).filter(
                role_permissions.c.role_id == role.id,
                role_permissions.c.permission_id == Permission.id,
                Permission.code == permission_code
            ).exists()
        ).scalar()
    return False


def permission_required(permission_code):
    """路由装饰器：要求用户拥有指定权限"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                if request.is_json or request.path.startswith('/api/'):
                    return jsonify({'error': 'Authentication required'}), 401
                return abort(401)
            if not has_permission(current_user, permission_code):
                if request.is_json or request.path.startswith('/api/'):
                    return jsonify({'error': '权限不足', 'required_permission': permission_code}), 403
                return abort(403)
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def permission_required_self_or_admin(permission_code, user_id_field='user_id'):
    """路由装饰器：当前用户是自己的资源，或者是拥有指定权限的管理员"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                if request.is_json or request.path.startswith('/api/'):
                    return jsonify({'error': 'Authentication required'}), 401
                return abort(401)
            # 如果是自己的资源，允许
            target_user_id = kwargs.get(user_id_field)
            if target_user_id is not None and int(target_user_id) == current_user.id:
                return f(*args, **kwargs)
            # 否则需要指定权限
            if not has_permission(current_user, permission_code):
                if request.is_json or request.path.startswith('/api/'):
                    return jsonify({'error': '权限不足', 'required_permission': permission_code}), 403
                return abort(403)
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def create_default_roles_and_permissions():
    """创建默认权限和角色（幂等）"""
    from models.config_models import Role, Permission, UserRole, role_permissions

    # ====== 定义所有权限 ======
    all_permissions = [
        # (code, name, category, module, is_system)
        ('system:admin', '系统管理员', 'system', 'system', True),

        ('config:view', '查看配置', 'config', 'config', False),
        ('config:edit', '编辑配置', 'config', 'config', False),

        ('user:view', '查看用户', 'user', 'user', False),
        ('user:edit', '编辑用户', 'user', 'user', False),

        ('permission:view', '查看权限', 'permission', 'permission', False),
        ('permission:edit', '编辑权限', 'permission', 'permission', False),

        ('device:view', '查看设备', 'device', 'device', False),
        ('device:edit', '编辑设备', 'device', 'device', False),

        ('report:view', '查看报表', 'report', 'report', False),
        ('report:edit', '管理报表', 'report', 'report', False),

        ('topology:view', '查看拓扑', 'topology', 'topology', False),
        ('topology:edit', '编辑拓扑', 'topology', 'topology', False),

        ('asset:view', '查看资产', 'asset', 'asset', False),
        ('asset:edit', '编辑资产', 'asset', 'asset', False),

        ('monitor:view', '查看监控', 'monitor', 'monitor', False),
        ('monitor:edit', '编辑监控', 'monitor', 'monitor', False),

        ('maintenance:view', '查看运维', 'maintenance', 'maintenance', False),
        ('maintenance:edit', '编辑运维', 'maintenance', 'maintenance', False),

        ('alert:view', '查看告警', 'alert', 'alert', False),
        ('alert:edit', '编辑告警', 'alert', 'alert', False),

        ('cmdb:view', '查看CMDB依赖', 'cmdb', 'cmdb', False),
        ('cmdb:edit', '编辑CMDB依赖', 'cmdb', 'cmdb', False),

        ('change:cab:view', '查看CAB审批', 'change', 'change', False),
        ('change:cab:approve', 'CAB审批', 'change', 'change', False),

        ('csi:view', '查看持续改进', 'csi', 'csi', False),
        ('csi:edit', '管理持续改进', 'csi', 'csi', False),

        ('event:rules', '事件关联规则', 'event', 'event', False),

        ('availability:collect', '采集真实可用率', 'availability', 'availability', False),
        ('csat:view', '查看服务满意度', 'csat', 'csat', False),
        ('csat:submit', '提交满意度评价', 'csat', 'csat', False),
        ('change:impact', '变更影响模拟', 'change', 'change', False),

        ('report:sla', 'SLA与服务报表', 'report', 'report', False),
        ('itsm:sla:manage', '管理SLA策略', 'itsm', 'itsm', False),

        ('audit:view', '查看审计', 'audit', 'audit', False),
        ('audit:delete', '删除审计', 'audit', 'audit', False),

        ('log:view', '查看日志', 'log', 'log', False),
        ('log:delete', '删除日志', 'log', 'log', False),

        ('cabinet:view', '查看机柜', 'cabinet', 'cabinet', False),
        ('cabinet:edit', '编辑机柜', 'cabinet', 'cabinet', False),

        ('location:view', '查看位置', 'location', 'location', False),
        ('location:edit', '编辑位置', 'location', 'location', False),

        ('network:view', '查看网络管理', 'network', 'network', False),
        ('network:edit', '编辑网络管理', 'network', 'network', False),

        ('netflow:view', '查看流量分析', 'netflow', 'netflow', False),
        ('netflow:edit', '管理流量采集', 'netflow', 'netflow', False),

        ('exec:view', '查看自动化执行', 'exec', 'exec', False),
        ('exec:run', '创建/执行任务', 'exec', 'exec', False),
        ('exec:approve', '审批执行任务', 'exec', 'exec', False),

        ('device_group:view', '查看设备分组', 'device_group', 'device_group', False),
        ('device_group:edit', '管理设备分组', 'device_group', 'device_group', False),

        ('system:jobs', '查看系统定时任务', 'system', 'system', False),
        ('system:jobs:run', '手动执行系统定时任务', 'system', 'system', False),
    ]

    # 创建权限（如果不存在）
    permission_map = {}
    for code, name, category, module, is_system in all_permissions:
        perm = Permission.query.filter_by(code=code).first()
        if not perm:
            perm = Permission(
                code=code, name=name, category=category,
                module=module, is_system=is_system
            )
            db.session.add(perm)
        permission_map[code] = perm
    db.session.flush()

    # ====== 定义四个角色的权限 ======
    role_definitions = [
        {
            'name': 'admin',
            'description': '系统管理员 — 拥有全部权限',
            'is_system': True,
            'permissions': [code for code, _, _, _, _ in all_permissions],
        },
        {
            'name': 'operator',
            'description': '操作员 — 可管理设备、监控、运维等日常操作',
            'is_system': True,
            'permissions': [
                'config:view',
                'device:view', 'device:edit',
                'report:view', 'report:edit',
                'topology:view', 'topology:edit',
                'asset:view', 'asset:edit',
                'monitor:view', 'monitor:edit',
                'maintenance:view', 'maintenance:edit',
                'alert:view', 'alert:edit',
                'cmdb:view', 'cmdb:edit',
                'change:cab:view', 'change:cab:approve',
                'csi:view', 'csi:edit',
                'event:rules',
                'availability:collect',
                'csat:view', 'csat:submit',
                'change:impact',
                'report:sla',
                'itsm:sla:manage',
                'audit:view',
                'log:view',
                'cabinet:view', 'cabinet:edit',
                'location:view', 'location:edit',
                'network:view', 'network:edit',
                'netflow:view', 'netflow:edit',
                'exec:view', 'exec:run', 'exec:approve',
                'device_group:view', 'device_group:edit',
                'system:jobs', 'system:jobs:run',
            ],
        },
        {
            'name': 'user',
            'description': '普通用户 — 可查看大部分内容，可编辑分配的模块',
            'is_system': True,
            'permissions': [
                'config:view',
                'device:view', 'device:edit',
                'report:view',
                'topology:view',
                'asset:view',
                'monitor:view',
                'maintenance:view', 'maintenance:edit',
                'alert:view',
                'cmdb:view', 'change:cab:view',
                'csi:view', 'event:rules', 'report:sla',
                'csat:view', 'csat:submit',
                'change:impact',
                'audit:view',
                'log:view',
                'cabinet:view',
                'location:view',
                'network:view', 'netflow:view',
                'exec:view',
                'device_group:view',
            ],
        },
        {
            'name': 'viewer',
            'description': '查看者 — 只读访问',
            'is_system': True,
            'permissions': [
                'config:view',
                'device:view',
                'report:view',
                'topology:view',
                'asset:view',
                'monitor:view',
                'maintenance:view',
                'alert:view',
                'cmdb:view', 'change:cab:view',
                'csi:view', 'event:rules', 'report:sla',
                'csat:view',
                'change:impact',
                'audit:view',
                'log:view',
                'cabinet:view',
                'location:view',
                'network:view', 'netflow:view',
                'exec:view',
                'device_group:view',
            ],
        },
    ]

    for rd in role_definitions:
        role = Role.query.filter_by(name=rd['name']).first()
        if not role:
            role = Role(name=rd['name'], description=rd['description'], is_system=rd['is_system'])
            db.session.add(role)
        # 更新角色权限
        role.permissions = [permission_map[code] for code in rd['permissions'] if code in permission_map]

    # 确保 admin 用户有关联的 UserRole 记录
    from models.models import User
    admin_user = User.query.filter_by(role='admin').first()
    if admin_user:
        admin_role = Role.query.filter_by(name='admin').first()
        if admin_role:
            existing = UserRole.query.filter_by(user_id=admin_user.id, role_id=admin_role.id).first()
            if not existing:
                ur = UserRole(user_id=admin_user.id, role_id=admin_role.id)
                db.session.add(ur)

    db.session.commit()
