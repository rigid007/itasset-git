
# models.py - 最终修复版
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
#from werkzeug.security import generate_password_hash, check_password_hash
from extensions import db  # 关键：从extensions.py导入唯一的db实例
#from models.maintenance_models  import  SparePart

#models.py 只依赖 extensions.db,以下引入注释掉。
#from extensions import db
#db = SQLAlchemy()
# models/models.py - 添加监控相关模型
from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text, ForeignKey
#from sqlalchemy.orm import relationship


class SystemConfig(db.Model):
    __tablename__ = 'system_configs'
    __table_args__ = {'extend_existing': True}
    
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.String(500), nullable=False)
    description = db.Column(db.String(200))
    category = db.Column(db.String(50), default='general')  # 新增分类字段
    is_public = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)