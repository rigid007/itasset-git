# blueprints/user.py
from flask import Blueprint, request, render_template, flash, redirect, url_for, jsonify
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash
from extensions import db
from datetime import datetime
import traceback
from models.models import db, User, Location, Cabinet, Device, OperationLog, TopologyLog,Config
from models.settings_models import SystemConfig
from utils.audit import log_audit
from utils.permission import permission_required
from models.config_models import Role, UserRole

# 初始化蓝图
user_bp = Blueprint('user', __name__, url_prefix='/users')

# 导入模型
# from models import User, Role, OperationLog


@user_bp.route('/user-list')
@login_required
@permission_required('user:view')
def user_list():
    # 查询所有用户，确保数据正常返回
    users = User.query.order_by(User.created_at.desc()).all() or []
    return render_template('user_list.html', users=users)

# 2. 新增用户接口（核心：接收表单参数，创建用户）
@user_bp.route('/user/add', methods=['POST'])
@login_required
@permission_required('user:edit')
def user_add():

    # 接收表单参数（与前端 name 属性完全一致）
    username = request.form.get('username')
    email = request.form.get('email')
    password = request.form.get('password')
    is_admin = bool(int(request.form.get('is_admin', 0)))
    is_active = bool(int(request.form.get('is_active', 1)))

    # 基础校验（避免无效数据）
    if not username or not email or not password:
        flash('用户名、邮箱、密码不能为空', 'danger')
        return redirect(url_for('user_list'))
    if len(password) < 6:
        flash('密码长度不少于6位', 'danger')
        return redirect(url_for('user_list'))
    # 校验用户名/邮箱是否重复
    if User.query.filter_by(username=username).first():
        flash('用户名已存在', 'danger')
        return redirect(url_for('user_list'))
    if User.query.filter_by(email=email).first():
        flash('邮箱已存在', 'danger')
        return redirect(url_for('user_list'))

    # 创建用户（密码加密存储）
    try:
        new_user = User(
            username=username,
            email=email,
            password_hash=generate_password_hash(password),
            role='admin' if is_admin else 'user',
            is_active=is_active
        )
        db.session.add(new_user)
        db.session.commit()  # 提交事务，确保数据写入数据库
        # 创建用户角色关联
        role_name = 'admin' if is_admin else 'user'
        role = Role.query.filter_by(name=role_name).first()
        if role and not UserRole.query.filter_by(user_id=new_user.id, role_id=role.id).first():
            db.session.add(UserRole(user_id=new_user.id, role_id=role.id))
            db.session.commit()
        log_audit('create', 'user', new_user.id, f'创建用户 {username}', details={'username': username, 'email': email, 'is_admin': is_admin}, user_id=current_user.id)
        flash(f'用户 {username} 创建成功', 'success')
    except Exception as e:
        db.session.rollback()  # 异常回滚
        flash(f'创建失败：{str(e)}', 'danger')

    return redirect(url_for('user_list'))  # 跳转回用户列表，刷新数据

# 3. 编辑用户接口（核心：接收用户ID，更新信息）
@user_bp.route('/user/edit', methods=['POST'])
@login_required
@permission_required('user:edit')
def user_edit():

    # 接收参数（先获取用户ID）
    user_id_str = request.form.get('user_id')
    username = request.form.get('username')
    email = request.form.get('email')
    password = request.form.get('password')
    is_admin = bool(int(request.form.get('is_admin', 0)))
    is_active = bool(int(request.form.get('is_active', 1)))

    # 校验用户ID有效性
    if not user_id_str:
        flash('用户ID不能为空', 'danger')
        return redirect(url_for('user_list'))
    try:
        user_id = int(user_id_str)
    except ValueError:
        flash('无效的用户ID', 'danger')
        return redirect(url_for('user_list'))

    # 查找用户
    user = User.query.get(user_id)
    if not user:
        flash('用户不存在', 'danger')
        return redirect(url_for('user_list'))

    # 校验用户名/邮箱是否重复（排除当前用户）
    if User.query.filter(User.username == username, User.id != user_id).first():
        flash('用户名已存在', 'danger')
        return redirect(url_for('user_list'))
    if User.query.filter(User.email == email, User.id != user_id).first():
        flash('邮箱已存在', 'danger')
        return redirect(url_for('user_list'))

    # 更新用户信息
    try:
        user.username = username
        user.email = email
        new_role = 'admin' if is_admin else 'user'
        user.role = new_role
        user.is_active = is_active
        # 密码不为空时才更新
        if password and len(password) >= 6:
            user.password_hash = generate_password_hash(password)
        # 同步 UserRole 关联
        role = Role.query.filter_by(name=new_role).first()
        if role:
            existing_ur = UserRole.query.filter_by(user_id=user.id).first()
            if existing_ur:
                existing_ur.role_id = role.id
            else:
                db.session.add(UserRole(user_id=user.id, role_id=role.id))
        db.session.commit()
        log_audit('update', 'user', user.id, f'编辑用户 {username}', details={'username': username, 'email': email, 'is_admin': is_admin, 'password_changed': bool(password and len(password) >= 6)}, user_id=current_user.id)
        flash(f'用户 {username} 修改成功', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'修改失败：{str(e)}', 'danger')

    return redirect(url_for('user_list'))

# 4. 删除用户接口（核心：接收用户ID，删除用户）
@user_bp.route('/user/delete', methods=['POST'])
@login_required
@permission_required('user:edit')
def user_delete():

    # 接收用户ID
    user_id_str = request.form.get('user_id')
    if not user_id_str:
        flash('用户ID不能为空', 'danger')
        return redirect(url_for('user_list'))
    try:
        user_id = int(user_id_str)
    except ValueError:
        flash('无效的用户ID', 'danger')
        return redirect(url_for('user_list'))

    # 禁止删除自己
    if current_user.id == user_id:
        flash('禁止删除当前登录账号', 'danger')
        return redirect(url_for('user_list'))

    # 查找并删除用户
    user = User.query.get(user_id)
    if not user:
        flash('用户不存在', 'danger')
        return redirect(url_for('user_list'))

    try:
        db.session.delete(user)
        db.session.commit()
        log_audit('delete', 'user', user.id, f'删除用户 {user.username}', details={'deleted_username': user.username}, user_id=current_user.id)
        flash(f'用户 {user.username} 删除成功', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'删除失败：{str(e)}', 'danger')

    return redirect(url_for('user_list'))

