# blueprints/auth.py
import time
from collections import defaultdict
from flask import Blueprint, request, jsonify, render_template, redirect, url_for, flash,current_app
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from datetime import datetime,timezone
from extensions import db
from models.models import User
import traceback
from auth import admin_required, log_operation
from utils.audit import log_audit

auth_bp = Blueprint('auth', __name__)

# 简单的登录失败限流（内存级，单进程有效；多进程/生产环境请改用 Redis + Flask-Limiter）
_login_failures = defaultdict(list)
LOGIN_MAX_ATTEMPTS = 5
LOGIN_LOCKOUT_SECONDS = 300


def _login_rate_limited(identifier):
    now = time.time()
    attempts = _login_failures[identifier]
    attempts[:] = [t for t in attempts if now - t < LOGIN_LOCKOUT_SECONDS]
    return len(attempts) >= LOGIN_MAX_ATTEMPTS


def _register_login_failure(identifier):
    _login_failures[identifier].append(time.time())


def _clear_login_failures(identifier):
    _login_failures[identifier].clear()

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    
    if request.method == 'POST':
        client_ip = request.remote_addr
        if _login_rate_limited(client_ip):
            flash('登录尝试过于频繁，请稍后再试', 'danger')
            return render_template('login.html')

        username = request.form.get('username')
        password = request.form.get('password')
        remember = request.form.get('remember', False)
        
        user = User.query.filter_by(username=username).first()
        
        if user and user.check_password(password):
            if user.is_active:
                login_user(user, remember=remember)
                user.last_login = datetime.now(timezone.utc)
                db.session.commit()
                
                _clear_login_failures(client_ip)
                # 直接调用 log_operation 函数
                log_operation('login', 'user', user.id, user.username, '用户登录')
                log_audit('login', 'auth', user.id, '用户登录', details={'username': username, 'ip': request.remote_addr})

                flash('登录成功', 'success')
                return redirect(url_for('main.index'))
            else:
                flash('账户已被禁用', 'danger')
        else:
            _register_login_failure(client_ip)
            flash('用户名或密码错误', 'danger')
    
    return render_template('login.html')

@auth_bp.route('/logout')
@login_required
def logout():
    log_operation('logout', 'user', current_user.id, current_user.username, '用户退出')
    logout_user()
    flash('您已退出登录', 'info')
    return redirect(url_for('auth.login'))

@auth_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        try:
            current_user.email = request.form.get('email')
            new_password = request.form.get('new_password')
            if new_password:
                current_user.set_password(new_password)
                flash('密码已更新', 'success')
            db.session.commit()
            current_app.log_operation('update', 'user', current_user.id, current_user.username, '更新个人资料')
            log_audit('update', 'profile', current_user.id, '更新个人资料', details={'username': current_user.username, 'email': current_user.email}, user_id=current_user.id)
            flash('个人资料已更新', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'更新失败: {str(e)}', 'danger')
    return render_template('profile.html')


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    # 内部资产系统默认关闭公开自助注册；需通过 ALLOW_PUBLIC_REGISTRATION=true 显式开启
    if not current_app.config.get('ALLOW_PUBLIC_REGISTRATION', True):
        flash('当前系统未开放自助注册，请联系管理员开通账户', 'warning')
        return redirect(url_for('auth.login'))
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))

    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')

        if password != confirm_password:
            flash('两次输入的密码不一致', 'error')
            return render_template('register.html')

        if db.session.query(User).filter_by(username=username).first():
            flash('用户名已存在', 'error')
            return render_template('register.html')

        if db.session.query(User).filter_by(email=email).first():
            flash('邮箱已被注册', 'error')
            return render_template('register.html')

        new_user = User(username=username, email=email, role='user')
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()
        # 创建 UserRole 关联
        from models.config_models import Role, UserRole
        user_role = Role.query.filter_by(name='user').first()
        if user_role:
            db.session.add(UserRole(user_id=new_user.id, role_id=user_role.id))
            db.session.commit()
        log_audit('create', 'user', new_user.id, '注册新用户', details={'username': username, 'email': email})

        flash('注册成功，请登录', 'success')
        return redirect(url_for('auth.login'))

    return render_template('register.html')


@auth_bp.route('/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        current_password = request.form.get('current_password')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')

        if not current_user.check_password(current_password):
            flash('当前密码不正确', 'danger')
        elif new_password != confirm_password:
            flash('两次输入的新密码不一致', 'danger')
        elif len(new_password) < 6:
            flash('新密码长度不能少于6位', 'danger')
        else:
            current_user.set_password(new_password)
            db.session.commit()
            log_audit('update', 'auth', current_user.id, '修改密码', user_id=current_user.id)
            flash('密码修改成功', 'success')
            return redirect(url_for('auth.profile'))

    return render_template('change_password.html')
