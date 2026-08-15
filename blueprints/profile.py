# app/routes/profile.py

from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import login_required, current_user
#from app import db
from models.models import User, OperationLog
from utils.audit import log_audit

profile_bp = Blueprint('profile', __name__, url_prefix='/profile')

@profile_bp.route('/', methods=['GET', 'POST'])
@login_required
def profile():
    """个人资料页面"""
    if request.method == 'POST':
        # 更新个人资料
        email = request.form.get('email')
        phone = request.form.get('phone')
        department = request.form.get('department')
        
        if email and email != current_user.email:
            # 检查邮箱是否已被使用
            existing_user = User.query.filter(User.email == email, User.id != current_user.id).first()
            if existing_user:
                flash('邮箱已被其他用户使用', 'danger')
                return redirect(url_for('profile.profile'))
            current_user.email = email
        
        if phone:
            current_user.phone = phone
        
        if department:
            current_user.department = department
        
        try:
            db.session.commit()
            log_audit('update', 'profile', current_user.id, '更新个人资料', details={'username': current_user.username, 'email': email}, user_id=current_user.id)

            # 记录操作日志
            log = OperationLog(
                user_id=current_user.id,
                username=current_user.username,
                action='update_profile',
                target_type='user',
                target_id=current_user.id,
                details='更新个人资料',
                ip_address=request.remote_addr,
                user_agent=request.user_agent.string if hasattr(request, 'user_agent') else ''
            )
            db.session.add(log)
            db.session.commit()
            
            flash('个人资料更新成功', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'更新失败: {str(e)}', 'danger')
        
        return redirect(url_for('profile.profile'))
    
    # GET 请求显示个人资料页面
    return render_template('profile/index.html', user=current_user)