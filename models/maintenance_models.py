from extensions import db

from datetime import datetime, timedelta

import json

import uuid

from sqlalchemy import DateTime, ForeignKey, Integer, String, Float, Text,or_



from sqlalchemy.orm import relationship

from models._base import utcnow as _utcnow



class MaintenanceTask(db.Model):

    """维护任务"""

    __tablename__ = 'maintenance_tasks'

    

    id = db.Column(db.Integer, primary_key=True)

    name = db.Column(db.String(100), nullable=False)

    description = db.Column(db.Text)

    maintenance_type = db.Column(db.String(50))  # preventive, corrective, emergency, upgrade

    device_ids = db.Column(db.Text)  # JSON格式的设备ID列表

    scheduled_date = db.Column(db.DateTime, nullable=False)

    estimated_duration = db.Column(db.Integer)  # 预计持续时间（分钟）

    actual_duration = db.Column(db.Integer)  # 实际持续时间（分钟）

    status = db.Column(db.String(20), default='scheduled')  # scheduled, in_progress, completed, cancelled

    priority = db.Column(db.String(20), default='medium')

    assigned_to = db.Column(db.Integer, db.ForeignKey('users.id'))

    approval_required = db.Column(db.Boolean, default=False)

    approved_by = db.Column(db.Integer, db.ForeignKey('users.id'))

    approved_at = db.Column(db.DateTime)

    completed_by = db.Column(db.Integer, db.ForeignKey('users.id'))

    completed_at = db.Column(db.DateTime)

    notes = db.Column(db.Text)

    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    

    def to_dict(self):

        return {

            'id': self.id,

            'name': self.name,

            'description': self.description,

            'maintenance_type': self.maintenance_type,

            'scheduled_date': self.scheduled_date.isoformat() if self.scheduled_date else None,

            'estimated_duration': self.estimated_duration,



            'status': self.status,

            'priority': self.priority,

            'created_at': self.created_at.isoformat() if self.created_at else None

        }





class SparePart(db.Model):

    """备件"""

    __tablename__ = 'spare_parts'

    

    id = db.Column(db.Integer, primary_key=True)

    asset_number = db.Column(db.String(64), unique=True, index=True)

    part_name = db.Column(db.String(128))  # 注意：这里是 part_name

    part_type = db.Column(db.String(50))

    manufacturer = db.Column(db.String(64))

    is_active = db.Column(db.Boolean, default=True)

    model = db.Column(db.String(64))

    serial_number = db.Column(db.String(64))

    status = db.Column(db.String(20), default='in_stock')  # in_stock, in_use, reserved, discarded

    warehouse_location = db.Column(db.String(128))

    purchase_date = db.Column(db.Date)

    unit_price = db.Column(db.Numeric(10, 2))  # 或者用 Float，但 Numeric 更适合金额

    current_stock = db.Column(db.Integer, default=0, nullable=False, comment='current stock quantity')

    min_stock_level = db.Column(db.Integer, default=0, nullable=False, comment='minimum stock threshold')

    max_stock_level = db.Column(db.Integer, default=0, nullable=False, comment='maximum stock threshold')

    supplier_id = db.Column(db.Integer, db.ForeignKey('suppliers.id'), nullable=True, comment='primary supplier id')

    installed_device_id = db.Column(db.Integer, db.ForeignKey('devices.id'))

    installed_device = db.relationship('Device', back_populates='spare_parts')

    supplier = db.relationship('Supplier', backref='spare_parts')

    installed_date = db.Column(db.Date)

    installed_by = db.Column(db.String(64))

    notes = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=_utcnow)

    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)

    

    def to_dict(self):

        """修正后的 to_dict，只包含模型中存在的字段"""

        return {

            'id': self.id,

            'asset_number': self.asset_number,

            'part_name': self.part_name,      # 使用 part_name

            'part_type': self.part_type,

            'manufacturer': self.manufacturer,

            'is_active':self.is_active,

            'model': self.model,

            'serial_number': self.serial_number,

            'status': self.status,

            'unit_price':self.unit_price,

            'warehouse_location': self.warehouse_location,

            'purchase_date': self.purchase_date.isoformat() if self.purchase_date else None,

            'current_stock': self.current_stock,

            'min_stock_level': self.min_stock_level,

            'max_stock_level': self.max_stock_level,

            'supplier_id': self.supplier_id,

            'installed_device_id': self.installed_device_id,

            'installed_date': self.installed_date.isoformat() if self.installed_date else None,

            'installed_by': self.installed_by,

            'notes': self.notes,

            'created_at': self.created_at.isoformat() if self.created_at else None,

            'updated_at': self.updated_at.isoformat() if self.updated_at else None,

        }



class Supplier(db.Model):

    """供应商"""

    __tablename__ = 'suppliers'

    

    id = db.Column(db.Integer, primary_key=True)

    name = db.Column(db.String(100), nullable=False)

    contact_person = db.Column(db.String(50))

    email = db.Column(db.String(100))

    phone = db.Column(db.String(20))

    address = db.Column(db.Text)

    website = db.Column(db.String(200))

    rating = db.Column(db.Integer)  # 1-5星评分

    lead_time = db.Column(db.Integer)  # 交货周期（天）

    payment_terms = db.Column(db.String(100))

    notes = db.Column(db.Text)

    is_active = db.Column(db.Boolean, default=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


    

    def to_dict(self):

        return {

            'id': self.id,

            'name': self.name,

            'contact_person': self.contact_person,

            'email': self.email,

            'phone': self.phone,

            'rating': self.rating,

            'lead_time': self.lead_time,

            'is_active': self.is_active

        }









class WorkOrderTemplate(db.Model):

    """工单模板"""

    __tablename__ = 'work_order_templates'

    

    id = db.Column(db.Integer, primary_key=True)

    name = db.Column(db.String(100), nullable=False)

    description = db.Column(db.Text)

    category = db.Column(db.String(50))

    subcategory = db.Column(db.String(50))

    content = db.Column(db.Text)  # 模板内容

    default_priority = db.Column(db.String(20), default='medium')

    default_assignee = db.Column(db.Integer, db.ForeignKey('users.id'))

    sla_id = db.Column(db.Integer, db.ForeignKey('sla_policies.id'))

    is_active = db.Column(db.Boolean, default=True)

    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    

    def to_dict(self):

        return {

            'id': self.id,

            'name': self.name,

            'description': self.description,

            'category': self.category,

            'default_priority': self.default_priority,

            'is_active': self.is_active

        }









class KnowledgeArticle(db.Model):

    """知识库文章"""

    __tablename__ = 'knowledge_articles'

    

    id = db.Column(db.Integer, primary_key=True)

    title = db.Column(db.String(200), nullable=False)

    content = db.Column(db.Text)

    category = db.Column(db.String(50))

    tags = db.Column(db.String(200))  # 逗号分隔的标签

    device_type = db.Column(db.String(50))

    vendor = db.Column(db.String(50))

    model = db.Column(db.String(50))

    author_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    status = db.Column(db.String(20), default='draft')  # draft, published, archived

    view_count = db.Column(db.Integer, default=0)

    helpful_count = db.Column(db.Integer, default=0)

    not_helpful_count = db.Column(db.Integer, default=0)

    is_featured = db.Column(db.Boolean, default=False)

    published_at = db.Column(db.DateTime)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    author = db.relationship('User', foreign_keys=[author_id], backref='knowledge_articles')

    

    def to_dict(self):

        return {

            'id': self.id,

            'title': self.title,

            'category': self.category,

            'tags': self.tags,

            'device_type': self.device_type,

            'status': self.status,

            'view_count': self.view_count,

            'is_featured': self.is_featured,

            'created_at': self.created_at.isoformat() if self.created_at else None

        }





class OnCallSchedule(db.Model):

    """值班安排"""

    __tablename__ = 'on_call_schedules'

    

    id = db.Column(db.Integer, primary_key=True)

    schedule_name = db.Column(db.String(100), nullable=False)

    schedule_type = db.Column(db.String(20), default='weekly')  # weekly, monthly, custom

    schedule_data = db.Column(db.Text)  # JSON格式的排班数据

    start_date = db.Column(db.DateTime, nullable=False)

    end_date = db.Column(db.DateTime)

    is_active = db.Column(db.Boolean, default=True)

    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    

    def to_dict(self):

        return {

            'id': self.id,

            'schedule_name': self.schedule_name,

            'schedule_type': self.schedule_type,

            'start_date': self.start_date.isoformat() if self.start_date else None,

            'end_date': self.end_date.isoformat() if self.end_date else None,

            'is_active': self.is_active

        }





class SLAPolicy(db.Model):

    """SLA策略"""

    __tablename__ = 'sla_policies'

    

    id = db.Column(db.Integer, primary_key=True)

    name = db.Column(db.String(100), nullable=False)

    description = db.Column(db.Text)

    category = db.Column(db.String(50))  # incident, request, problem

    priority = db.Column(db.String(20))

    response_time = db.Column(db.Integer)  # 响应时间（分钟）

    resolution_time = db.Column(db.Integer)  # 解决时间（分钟）

    business_hours = db.Column(db.Text)  # JSON格式的工作时间配置

    is_active = db.Column(db.Boolean, default=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    

    def to_dict(self):

        return {

            'id': self.id,

            'name': self.name,

            'description': self.description,

            'category': self.category,

            'priority': self.priority,

            'response_time': self.response_time,

            'resolution_time': self.resolution_time,

            'is_active': self.is_active

        }







class Asset(db.Model):

    __tablename__ = 'assets'

    

    id = db.Column(db.Integer, primary_key=True)

    

    # 资产基本信息

    asset_number = db.Column(db.String(64), unique=True, nullable=False, index=True)

    asset_name = db.Column(db.String(128), nullable=False)

    asset_type = db.Column(db.String(50), nullable=False, index=True)  # 服务器、网络设备、软件、办公设备等

    asset_subtype = db.Column(db.String(50))  # 子类型

    

    # 设备关联（如果有）

    device_id = db.Column(db.Integer, db.ForeignKey('devices.id'), nullable=True)

    

    # 位置信息

    location_id = db.Column(db.Integer, db.ForeignKey('locations.id'), nullable=True)

    cabinet_id = db.Column(db.Integer, db.ForeignKey('cabinets.id'), nullable=True)

    position = db.Column(db.String(128))  # 具体位置描述

    

    # 规格信息

    brand = db.Column(db.String(64))

    model = db.Column(db.String(64))

    serial_number = db.Column(db.String(100), unique=True, nullable=True, default=None)

    specification = db.Column(db.Text)  # 规格描述

    

    # 资产状态

    status = db.Column(db.String(20), default='active', index=True)  # active, inactive, retired, lost, maintenance

    condition = db.Column(db.String(20), default='good')  # good, fair, poor

    

    # 财务信息

    purchase_date = db.Column(db.Date)

    purchase_price = db.Column(db.Float)

    warranty_expiry = db.Column(db.Date)

    depreciation_rate = db.Column(db.Float)  # 年折旧率

    current_value = db.Column(db.Float)  # 当前价值

    

    # 责任人信息

    owner_department = db.Column(db.String(100))

    owner_person = db.Column(db.String(64))

    owner_contact = db.Column(db.String(50))

    

    # 供应商信息

    supplier_name = db.Column(db.String(128))

    supplier_contact = db.Column(db.String(128))

    

    # 使用信息

    in_use = db.Column(db.Boolean, default=True)

    usage_description = db.Column(db.Text)

    

    # 维护信息

    maintenance_schedule = db.Column(db.String(50))  # 维护周期

    last_maintenance = db.Column(db.Date)

    next_maintenance = db.Column(db.Date)

    

    # 其他信息

    tags = db.Column(db.String(255))  # 标签，用逗号分隔

    notes = db.Column(db.Text)

    is_active = db.Column(db.Boolean, default=True)

    

    # 时间戳

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    

    # 关系

    device = db.relationship('Device', backref='asset_record', foreign_keys=[device_id])

    location = db.relationship('Location', backref='assets')

    cabinet = db.relationship('Cabinet', backref='assets')





    ledger_entries = db.relationship('AssetLedger', 

                                     back_populates='asset',   # ✅ 正确

                                     lazy='dynamic', 

                                     cascade='all, delete-orphan')



    supplier_id = db.Column(db.Integer, db.ForeignKey('suppliers.id'), nullable=True)

    supplier = db.relationship('Supplier')

    





    def __repr__(self):

        return f'<Asset {self.asset_number}: {self.asset_name}>'

    

    def calculate_current_value(self):

        """计算当前资产价值"""

        if not self.purchase_price or not self.purchase_date:

            return self.purchase_price or 0

        

        today = datetime.utcnow().date()

        purchase_date = self.purchase_date

        

        # 计算已使用年数

        years_diff = today.year - purchase_date.year

        if (today.month, today.day) < (purchase_date.month, purchase_date.day):

            years_diff -= 1

        

        if years_diff <= 0:

            return self.purchase_price

        

        # 应用折旧率

        depreciation_rate = self.depreciation_rate or 10  # 默认10%年折旧

        current_value = self.purchase_price

        for _ in range(years_diff):

            current_value *= (1 - depreciation_rate / 100)

        

        return max(current_value, 0)  # 价值不能为负

    

    def get_age(self):

        """获取资产年龄（年）"""

        if not self.purchase_date:

            return None

        

        today = datetime.utcnow().date()

        purchase_date = self.purchase_date

        

        years_diff = today.year - purchase_date.year

        if (today.month, today.day) < (purchase_date.month, purchase_date.day):

            years_diff -= 1

        

        return max(years_diff, 0)

    

    def is_under_warranty(self):

        """检查是否在保修期内"""

        if not self.warranty_expiry:

            return False

        

        today = datetime.utcnow().date()

        return today <= self.warranty_expiry

    

    def get_status_badge_class(self):

        """获取状态对应的CSS类"""

        status_classes = {

            'active': 'success',

            'inactive': 'secondary',

            'retired': 'dark',

            'lost': 'danger',

            'maintenance': 'warning',

            'reserved': 'info'

        }

        return status_classes.get(self.status, 'secondary')

    

    def get_condition_badge_class(self):

        """获取状况对应的CSS类"""

        condition_classes = {

            'excellent': 'success',

            'good': 'info',

            'fair': 'warning',

            'poor': 'danger'

        }

        return condition_classes.get(self.condition, 'secondary')

    

    def to_dict(self):

        """转换为字典格式"""

        return {

            'id': self.id,

            'asset_number': self.asset_number,

            'asset_name': self.asset_name,

            'asset_type': self.asset_type,

            'brand': self.brand,

            'model': self.model,

            'status': self.status,

            'purchase_date': self.purchase_date.isoformat() if self.purchase_date else None,

            'purchase_price': self.purchase_price,

            'current_value': self.calculate_current_value(),

            'location_id': self.location_id,

            'location_name': self.location.name if self.location else None,

            'owner_department': self.owner_department,

            'owner_person': self.owner_person,

            'warranty_expiry': self.warranty_expiry.isoformat() if self.warranty_expiry else None,

            'is_under_warranty': self.is_under_warranty(),

            'age_years': self.get_age(),

            'condition': self.condition

        }





class AssetDepreciation(db.Model):

    """资产折旧记录模型"""

    __tablename__ = 'asset_depreciations'

    

    id = db.Column(db.Integer, primary_key=True)

    asset_id = db.Column(db.Integer, db.ForeignKey('assets.id'), nullable=False)

    

    # 折旧信息

    year = db.Column(db.Integer, nullable=False)  # 折旧年份

    month = db.Column(db.Integer, nullable=False)  # 折旧月份（1-12）

    

    # 折旧金额

    original_value = db.Column(db.Float, nullable=False)  # 原值

    depreciation_amount = db.Column(db.Float, nullable=False)  # 当期折旧额

    accumulated_depreciation = db.Column(db.Float, nullable=False)  # 累计折旧

    current_value = db.Column(db.Float, nullable=False)  # 当期净值

    

    # 折旧方法

    method = db.Column(db.String(20), nullable=False)  # 折旧方法: straight_line(直线法), double_declining(双倍余额递减法), sum_of_years(年数总和法)

    depreciation_rate = db.Column(db.Float)  # 折旧率（%）

    

    # 计算参数

    useful_life = db.Column(db.Integer)  # 使用年限

    residual_value = db.Column(db.Float)  # 残值

    

    # 状态

    is_calculated = db.Column(db.Boolean, default=False)  # 是否已计算

    is_posted = db.Column(db.Boolean, default=False)  # 是否已过账到总账

    

    # 时间戳

    calculated_at = db.Column(db.DateTime)  # 计算时间

    posted_at = db.Column(db.DateTime)  # 过账时间

    

    # 关系

    asset = db.relationship('Asset', backref=db.backref('depreciations', lazy='dynamic'))

    

    # 索引

    __table_args__ = (

        db.Index('idx_asset_depreciation_asset_year_month', 'asset_id', 'year', 'month', unique=True),

        db.Index('idx_asset_depreciation_year_month', 'year', 'month'),

        db.Index('idx_asset_depreciation_is_posted', 'is_posted'),

    )

    

    def __repr__(self):

        return f'<AssetDepreciation 资产ID:{self.asset_id} {self.year}年{self.month}月>'

    

    def to_dict(self):

        """转换为字典格式"""

        return {

            'id': self.id,

            'asset_id': self.asset_id,

            'asset_code': self.asset.asset_code if self.asset else None,

            'asset_name': self.asset.name if self.asset else None,

            'year': self.year,

            'month': self.month,

            'original_value': self.original_value,

            'depreciation_amount': self.depreciation_amount,

            'accumulated_depreciation': self.accumulated_depreciation,

            'current_value': self.current_value,

            'method': self.method,

            'depreciation_rate': self.depreciation_rate,

            'useful_life': self.useful_life,

            'residual_value': self.residual_value,

            'is_calculated': self.is_calculated,

            'is_posted': self.is_posted,

            'calculated_at': self.calculated_at.strftime('%Y-%m-%d %H:%M:%S') if self.calculated_at else None,

            'posted_at': self.posted_at.strftime('%Y-%m-%d %H:%M:%S') if self.posted_at else None

        }

    

    def calculate_monthly_depreciation(self):

        """计算月度折旧额"""

        if self.method == 'straight_line':

            # 直线法：每月折旧额 = (原值 - 残值) / (使用年限 * 12)

            if self.useful_life and self.useful_life > 0:

                total_months = self.useful_life * 12

                if total_months > 0:

                    return (self.original_value - self.residual_value) / total_months

        elif self.method == 'double_declining':

            # 双倍余额递减法：每月折旧额 = 当期净值 * (2 / (使用年限 * 12))

            if self.useful_life and self.useful_life > 0:

                monthly_rate = 2 / (self.useful_life * 12)

                return self.current_value * monthly_rate

        elif self.method == 'sum_of_years':

            # 年数总和法：每年折旧额 = (原值 - 残值) * (剩余年限 / 年数总和)

            # 这里简化为平均到每个月

            if self.useful_life and self.useful_life > 0:

                years_sum = self.useful_life * (self.useful_life + 1) / 2

                remaining_years = self.useful_life - ((self.year - 1) + (self.month - 1) / 12)

                annual_depreciation = (self.original_value - self.residual_value) * (remaining_years / years_sum)

                return annual_depreciation / 12

        

        return 0.0







class AssetLedger(db.Model):

    """资产台账模型（记录资产的所有变动）"""

    __tablename__ = 'asset_ledger'

    

    id = db.Column(db.Integer, primary_key=True)

    

    # 资产信息

    asset_id = db.Column(db.Integer, db.ForeignKey('assets.id'), nullable=False)

    asset_code = db.Column(db.String(50), nullable=False)  # 资产编号（冗余存储，便于查询）

    asset_name = db.Column(db.String(100), nullable=False)  # 资产名称（冗余存储）

    

    # 交易信息

    transaction_type = db.Column(db.String(20), nullable=False)  # 交易类型: purchase(采购), depreciation(折旧), transfer(转移), maintenance(维修), disposal(处置), revaluation(重估), other(其他)

    transaction_date = db.Column(db.Date, nullable=False)  # 交易日期

    transaction_time = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)  # 交易时间

    

    # 金额相关

    debit_amount = db.Column(db.Float, default=0.0)  # 借方金额

    credit_amount = db.Column(db.Float, default=0.0)  # 贷方金额

    balance_amount = db.Column(db.Float, nullable=False)  # 余额

    

    # 数量相关

    quantity_change = db.Column(db.Float, default=0.0)  # 数量变化

    quantity_balance = db.Column(db.Float, nullable=False)  # 数量余额

    

    # 状态相关

    status_before = db.Column(db.String(20))  # 变动前状态

    status_after = db.Column(db.String(20), nullable=False)  # 变动后状态

    

    # 位置相关

    location_id_before = db.Column(db.Integer, db.ForeignKey('locations.id'))  # 变动前位置

    location_id_after = db.Column(db.Integer, db.ForeignKey('locations.id'))  # 变动后位置

    location_before = db.Column(db.String(100))  # 变动前位置名称（冗余）

    location_after = db.Column(db.String(100))  # 变动后位置名称（冗余）

    

    # 责任人相关

    responsible_person_before = db.Column(db.String(50))  # 变动前责任人

    responsible_person_after = db.Column(db.String(50))  # 变动后责任人

    

    # 部门相关

    department_before = db.Column(db.String(100))  # 变动前部门

    department_after = db.Column(db.String(100))  # 变动后部门

    

    # 折旧相关（如果是折旧交易）

    depreciation_year = db.Column(db.Integer)  # 折旧年份

    depreciation_month = db.Column(db.Integer)  # 折旧月份

    depreciation_method = db.Column(db.String(20))  # 折旧方法

    

    # 详细说明

    description = db.Column(db.Text)  # 交易描述

    reference_number = db.Column(db.String(50))  # 参考单号（如采购单号、折旧计算单号等）

    document_number = db.Column(db.String(50))  # 凭证号

    

    # 操作信息

    operator_id = db.Column(db.Integer, db.ForeignKey('users.id'))  # 操作人ID

    operator_name = db.Column(db.String(50))  # 操作人姓名（冗余存储）

    

    # 审批信息

    approval_status = db.Column(db.String(20), default='pending')  # 审批状态: pending, approved, rejected

    approval_notes = db.Column(db.Text)  # 审批意见

    approved_by = db.Column(db.String(50))  # 审批人

    approved_at = db.Column(db.DateTime)  # 审批时间

    

    # 系统字段

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    

    # 关系

    asset = db.relationship('Asset', backref=db.backref('ledger_entries', lazy='dynamic'))

    operator = db.relationship('User', foreign_keys=[operator_id])

    before_location = db.relationship('Location', foreign_keys=[location_id_before])

    after_location = db.relationship('Location', foreign_keys=[location_id_after])

    asset = db.relationship('Asset', 

                            back_populates='ledger_entries')   # ✅ 正确

    

    # 索引

    __table_args__ = (

        db.Index('idx_asset_ledger_asset_id', 'asset_id'),

        db.Index('idx_asset_ledger_transaction_date', 'transaction_date'),

        db.Index('idx_asset_ledger_transaction_type', 'transaction_type'),

        db.Index('idx_asset_ledger_asset_code', 'asset_code'),

        db.Index('idx_asset_ledger_reference_number', 'reference_number'),

        db.Index('idx_asset_ledger_operator_id', 'operator_id'),

        db.Index('idx_asset_ledger_approval_status', 'approval_status'),

        db.Index('idx_asset_ledger_date_type', 'transaction_date', 'transaction_type'),

        db.Index('idx_asset_ledger_asset_date', 'asset_id', 'transaction_date'),

    )

    

    # 交易类型常量

    TRANSACTION_TYPES = {

        'purchase': '采购',

        'depreciation': '折旧',

        'transfer': '转移',

        'maintenance': '维修',

        'disposal': '处置',

        'revaluation': '重估',

        'inventory_adjustment': '盘点调整',

        'scrap': '报废',

        'loan': '借用',

        'return': '归还',

        'other': '其他'

    }

    

    def __repr__(self):

        return f'<AssetLedger 资产:{self.asset_code} 类型:{self.transaction_type} 日期:{self.transaction_date}>'

    

    def to_dict(self):

        """转换为字典格式"""

        return {

            'id': self.id,

            'asset_id': self.asset_id,

            'asset_code': self.asset_code,

            'asset_name': self.asset_name,

            'transaction_type': self.transaction_type,

            'transaction_type_display': self.TRANSACTION_TYPES.get(self.transaction_type, self.transaction_type),

            'transaction_date': self.transaction_date.strftime('%Y-%m-%d') if self.transaction_date else None,

            'transaction_time': self.transaction_time.strftime('%Y-%m-%d %H:%M:%S') if self.transaction_time else None,

            'debit_amount': self.debit_amount,

            'credit_amount': self.credit_amount,

            'balance_amount': self.balance_amount,

            'quantity_change': self.quantity_change,

            'quantity_balance': self.quantity_balance,

            'status_before': self.status_before,

            'status_after': self.status_after,

            'location_before': self.location_before,

            'location_after': self.location_after,

            'responsible_person_before': self.responsible_person_before,

            'responsible_person_after': self.responsible_person_after,

            'department_before': self.department_before,

            'department_after': self.department_after,

            'depreciation_year': self.depreciation_year,

            'depreciation_month': self.depreciation_month,

            'depreciation_method': self.depreciation_method,

            'description': self.description,

            'reference_number': self.reference_number,

            'document_number': self.document_number,

            'operator_id': self.operator_id,

            'operator_name': self.operator_name,

            'approval_status': self.approval_status,

            'approval_notes': self.approval_notes,

            'approved_by': self.approved_by,

            'approved_at': self.approved_at.strftime('%Y-%m-%d %H:%M:%S') if self.approved_at else None,

            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None

        }

    

    @classmethod

    def create_purchase_entry(cls, asset, purchase_data):

        """创建采购台账记录"""

        ledger = cls(

            asset_id=asset.id,

            asset_code=asset.asset_code,

            asset_name=asset.name,

            transaction_type='purchase',

            transaction_date=purchase_data.get('purchase_date', datetime.now().date()),

            transaction_time=datetime.now(),

            debit_amount=purchase_data.get('purchase_price', 0),

            credit_amount=0,

            balance_amount=purchase_data.get('purchase_price', 0),

            quantity_change=1,

            quantity_balance=1,

            status_before='new',

            status_after='in_use',

            location_id_after=purchase_data.get('location_id'),

            location_after=purchase_data.get('location'),

            responsible_person_after=purchase_data.get('responsible_person'),

            department_after=purchase_data.get('department'),

            description=f"采购资产: {asset.name}",

            reference_number=purchase_data.get('purchase_order_number'),

            document_number=purchase_data.get('document_number'),

            operator_id=current_user.id if current_user and current_user.is_authenticated else None,

            operator_name=current_user.username if current_user and current_user.is_authenticated else None,

            approval_status='approved'  # 采购默认已审批

        )

        return ledger

    

    @classmethod

    def create_depreciation_entry(cls, asset, depreciation_data):

        """创建折旧台账记录"""

        ledger = cls(

            asset_id=asset.id,

            asset_code=asset.asset_code,

            asset_name=asset.name,

            transaction_type='depreciation',

            transaction_date=depreciation_data.get('depreciation_date', datetime.now().date()),

            transaction_time=datetime.now(),

            debit_amount=0,

            credit_amount=depreciation_data.get('depreciation_amount', 0),

            balance_amount=depreciation_data.get('current_value', asset.current_value),

            quantity_change=0,

            quantity_balance=1,

            status_before=asset.status,

            status_after=asset.status,

            location_id_before=asset.location_id,

            location_id_after=asset.location_id,

            location_before=asset.location.name if asset.location else None,

            location_after=asset.location.name if asset.location else None,

            responsible_person_before=asset.responsible_person,

            responsible_person_after=asset.responsible_person,

            department_before=asset.department,

            department_after=asset.department,

            depreciation_year=depreciation_data.get('year'),

            depreciation_month=depreciation_data.get('month'),

            depreciation_method=depreciation_data.get('method'),

            description=f"折旧计提: {depreciation_data.get('description', '')}",

            reference_number=depreciation_data.get('reference_number'),

            document_number=depreciation_data.get('document_number'),

            operator_id=current_user.id if current_user and current_user.is_authenticated else None,

            operator_name=current_user.username if current_user and current_user.is_authenticated else None,

            approval_status='approved'  # 折旧计提默认已审批

        )

        return ledger

    

    @classmethod

    def create_transfer_entry(cls, asset, transfer_data):

        """创建转移台账记录"""

        ledger = cls(

            asset_id=asset.id,

            asset_code=asset.asset_code,

            asset_name=asset.name,

            transaction_type='transfer',

            transaction_date=transfer_data.get('transfer_date', datetime.now().date()),

            transaction_time=datetime.now(),

            debit_amount=0,

            credit_amount=0,

            balance_amount=asset.current_value,

            quantity_change=0,

            quantity_balance=1,

            status_before=asset.status,

            status_after=asset.status,

            location_id_before=asset.location_id,

            location_id_after=transfer_data.get('new_location_id'),

            location_before=transfer_data.get('old_location'),

            location_after=transfer_data.get('new_location'),

            responsible_person_before=asset.responsible_person,

            responsible_person_after=transfer_data.get('new_responsible_person', asset.responsible_person),

            department_before=asset.department,

            department_after=transfer_data.get('new_department', asset.department),

            description=transfer_data.get('description', f"资产转移: {transfer_data.get('old_location')} -> {transfer_data.get('new_location')}"),

            reference_number=transfer_data.get('transfer_order_number'),

            document_number=transfer_data.get('document_number'),

            operator_id=current_user.id if current_user and current_user.is_authenticated else None,

            operator_name=current_user.username if current_user and current_user.is_authenticated else None,

            approval_status=transfer_data.get('approval_status', 'pending')

        )

        return ledger

    

    @classmethod

    def create_disposal_entry(cls, asset, disposal_data):

        """创建处置台账记录"""

        ledger = cls(

            asset_id=asset.id,

            asset_code=asset.asset_code,

            asset_name=asset.name,

            transaction_type='disposal',

            transaction_date=disposal_data.get('disposal_date', datetime.now().date()),

            transaction_time=datetime.now(),

            debit_amount=0,

            credit_amount=disposal_data.get('disposal_value', asset.current_value),

            balance_amount=0,

            quantity_change=-1,

            quantity_balance=0,

            status_before=asset.status,

            status_after='disposed',

            location_id_before=asset.location_id,

            location_before=asset.location.name if asset.location else None,

            responsible_person_before=asset.responsible_person,

            department_before=asset.department,

            description=disposal_data.get('description', f"资产处置: {disposal_data.get('disposal_reason', '')}"),

            reference_number=disposal_data.get('disposal_order_number'),

            document_number=disposal_data.get('document_number'),

            operator_id=current_user.id if current_user and current_user.is_authenticated else None,

            operator_name=current_user.username if current_user and current_user.is_authenticated else None,

            approval_status=disposal_data.get('approval_status', 'pending')

        )

        return ledger



class SparePartRequest(db.Model):

    """备件申请模型"""

    __tablename__ = 'spare_part_requests'

    

    id = db.Column(db.Integer, primary_key=True)

    

    # 申请信息

    request_number = db.Column(db.String(50), unique=True, nullable=False)  # 申请单号

    spare_part_id = db.Column(db.Integer, db.ForeignKey('spare_parts.id'), nullable=False)

    quantity = db.Column(db.Integer, nullable=False)  # 申请数量

    reason = db.Column(db.Text, nullable=False)  # 申请原因

    urgency = db.Column(db.String(20), default='medium')  # 紧急程度: low, medium, high, critical

    usage_description = db.Column(db.Text)  # 用途描述

    

    # 申请人信息

    requester_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    requester_name = db.Column(db.String(50), nullable=False)

    department = db.Column(db.String(100))

    

    # 审批信息

    approval_status = db.Column(db.String(20), default='pending')  # pending, approved, rejected, partially_approved

    approval_notes = db.Column(db.Text)

    approved_by = db.Column(db.String(50))

    approved_at = db.Column(db.DateTime)

    

    # 发放信息

    issued_quantity = db.Column(db.Integer, default=0)  # 已发放数量

    issued_by = db.Column(db.String(50))

    issued_at = db.Column(db.DateTime)

    

    # 状态

    status = db.Column(db.String(20), default='pending')  # pending, approved, issued, completed, cancelled

    

    # 时间戳

    requested_at = db.Column(db.DateTime, default=datetime.utcnow)

    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    

    # SparePartRequest 关系

    spare_part = db.relationship('SparePart', backref=db.backref('requests', lazy='dynamic'))

    requester = db.relationship('User', foreign_keys=[requester_id])

    

    def __repr__(self):

        return f'<SparePartRequest {self.request_number}>'

    

    def generate_request_number(self):

        """生成申请单号"""

        date_str = datetime.now().strftime('%Y%m%d')

        count = SparePartRequest.query.filter(

            db.func.date(SparePartRequest.requested_at) == datetime.now().date()

        ).count() + 1

        return f'SPR{date_str}{count:04d}'





class SparePartUsage(db.Model):

    """备件使用记录模型"""

    __tablename__ = 'spare_part_usage'

    

    id = db.Column(db.Integer, primary_key=True)

    

    # 备件信息

    spare_part_id = db.Column(db.Integer, ForeignKey('spare_parts.id'), nullable=False)

    spare_part_code = db.Column(String(50), nullable=False)

    spare_part_name = db.Column(String(100), nullable=False)

    

    # 使用信息

    usage_date = db.Column(db.DateTime, nullable=False)

    quantity = db.Column(db.Integer, nullable=False)

    unit_price = db.Column(Float)  # 单价（使用时的价格）

    total_cost = db.Column(Float)  # 总成本

    

    # 使用场景

    usage_type = db.Column(String(20))  # maintenance, replacement, emergency, project, other

    work_order_id = db.Column(db.Integer, ForeignKey('work_orders.id'))  # 关联工单

    maintenance_id = db.Column(db.Integer, ForeignKey('maintenance_records.id'))  # 关联维护记录

    # 外键定义正确，指向 projects 表的 id

    project_id = db.Column(db.Integer, ForeignKey('projects.id'))  # 关联项目



    # 关系定义 - 同样使用字符串形式

    project = relationship(

        'Project', 

        back_populates='spare_part_usages'

    )

    

    # 使用描述

    description = db.Column(Text)

    used_on_device = db.Column(String(100))  # 用在哪个设备上

    used_on_location = db.Column(String(100))  # 使用位置

    

    # 操作信息

    operator_id = db.Column(db.Integer, ForeignKey('users.id'))

    operator_name = db.Column(String(50))

    

    # 时间戳

    created_at = db.Column(DateTime, default=datetime.utcnow)

    

    # 其他关系

    spare_part = relationship('SparePart', backref=db.backref('usage_records', lazy='dynamic'))

    work_order = relationship('WorkOrder', backref=db.backref('spare_part_usage', lazy='dynamic'))

    operator = relationship('User', foreign_keys=[operator_id])

    

    def __repr__(self):

        return f'<SparePartUsage {self.spare_part_code} {self.usage_date}>'

    

    def calculate_cost(self):

        """计算使用成本"""

        if self.quantity and self.unit_price:

            self.total_cost = self.quantity * self.unit_price

        return self.total_cost







#===========================

# models.py - 添加缺失的维护记录模型



class MaintenanceRecord(db.Model):

    """维护记录模型"""

    __tablename__ = 'maintenance_records'

    

    id = db.Column(db.Integer, primary_key=True)

    

    # 维护基本信息

    record_number = db.Column(db.String(50), unique=True, nullable=False)  # 维护记录编号

    title = db.Column(db.String(200), nullable=False)  # 维护标题

    description = db.Column(db.Text)  # 维护描述

    

    # 关联信息

    device_id = db.Column(db.Integer, db.ForeignKey('devices.id'))  # 关联设备

    asset_id = db.Column(db.Integer, db.ForeignKey('assets.id'))  # 关联资产

    location_id = db.Column(db.Integer, db.ForeignKey('locations.id'))  # 关联位置

    

    # 维护类型

    maintenance_type = db.Column(db.String(50), nullable=False)  # 维护类型: preventive(预防性), corrective(修复性), emergency(紧急), routine(例行)

    category = db.Column(db.String(50))  # 维护类别: hardware, software, network, power, cooling, other

    

    # 时间信息

    scheduled_date = db.Column(db.Date)  # 计划日期

    actual_date = db.Column(db.Date)  # 实际执行日期

    start_time = db.Column(db.DateTime)  # 开始时间

    end_time = db.Column(db.DateTime)  # 结束时间

    duration_hours = db.Column(db.Float)  # 持续时间（小时）

    

    # 维护人员

    technician_id = db.Column(db.Integer, db.ForeignKey('users.id'))  # 技术人员ID

    technician_name = db.Column(db.String(50))  # 技术人员姓名

    team_members = db.Column(db.Text)  # 团队成员（JSON或逗号分隔）

    

    # 成本信息

    labor_cost = db.Column(db.Float, default=0.0)  # 人工成本

    material_cost = db.Column(db.Float, default=0.0)  # 材料成本

    total_cost = db.Column(db.Float, default=0.0)  # 总成本

    

    # 维护结果

    status = db.Column(db.String(20), default='pending')  # 状态: pending, in_progress, completed, cancelled, on_hold

    result = db.Column(db.String(20))  # 结果: success, partial_success, failed, cancelled

    resolution = db.Column(db.Text)  # 解决方案描述

    

    # 检查项

    check_items = db.Column(db.Text)  # 检查项目（JSON格式）

    checklist_results = db.Column(db.Text)  # 检查结果（JSON格式）

    

    # 问题发现

    issues_found = db.Column(db.Text)  # 发现的问题

    recommendations = db.Column(db.Text)  # 建议

    

    # 文档

    attachments = db.Column(db.Text)  # 附件列表（JSON格式）

    notes = db.Column(db.Text)  # 备注

    

    # 审批信息

    approval_status = db.Column(db.String(20), default='pending')  # 审批状态

    approved_by = db.Column(db.String(50))

    approved_at = db.Column(db.DateTime)

    

    # 关联工单

    work_order_id = db.Column(db.Integer, db.ForeignKey('work_orders.id'))

    

    # 系统字段

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    created_by = db.Column(db.String(50))

    updated_by = db.Column(db.String(50))

    

    # 关系

    device = db.relationship('Device', backref='maintenance_records')

    asset = db.relationship('Asset', backref='maintenance_records')

    location = db.relationship('Location', backref='maintenance_records')

    technician = db.relationship('User', foreign_keys=[technician_id])

    work_order = db.relationship('WorkOrder', backref='maintenance_records')

    

    def __repr__(self):

        return f'<MaintenanceRecord {self.record_number}: {self.title}>'

    

    def generate_record_number(self):

        """生成维护记录编号"""

        if not self.record_number:

            date_str = datetime.now().strftime('%Y%m%d')

            count = MaintenanceRecord.query.filter(

                db.func.date(MaintenanceRecord.created_at) == datetime.now().date()

            ).count() + 1

            self.record_number = f'MR{date_str}{count:04d}'

        return self.record_number

    

    def calculate_duration(self):

        """计算维护持续时间"""

        if self.start_time and self.end_time:

            duration = (self.end_time - self.start_time).total_seconds() / 3600

            self.duration_hours = round(duration, 2)

        return self.duration_hours

    

    def calculate_total_cost(self):

        """计算总成本"""

        self.total_cost = (self.labor_cost or 0) + (self.material_cost or 0)

        return self.total_cost





class WorkOrder(db.Model):

    """工单模型"""

    __tablename__ = 'work_orders'

    

    id = db.Column(db.Integer, primary_key=True)

    

    # 工单基本信息

    work_order_number = db.Column(db.String(50), unique=True, nullable=False)  # 工单编号

    title = db.Column(db.String(200), nullable=False)  # 工单标题

    description = db.Column(db.Text)  # 工单描述

    

    # 工单分类

    work_order_type = db.Column(db.String(50), nullable=False)  # 工单类型: incident, request, problem, change, task

    category = db.Column(db.String(50))  # 工单类别

    

    # 优先级和紧急程度

    priority = db.Column(db.String(20), default='medium')  # 优先级: low, medium, high, critical

    impact = db.Column(db.String(20), default='medium')  # 影响程度: low, medium, high

    urgency = db.Column(db.String(20), default='medium')  # 紧急程度: low, medium, high

    

    # 关联信息

    requester_id = db.Column(db.Integer, db.ForeignKey('users.id'))  # 请求人ID

    requester_name = db.Column(db.String(50))  # 请求人姓名

    requester_department = db.Column(db.String(100))  # 请求人部门

    requester_contact = db.Column(db.String(50))  # 请求人联系方式

    

    # 分配信息

    assigned_to_id = db.Column(db.Integer, db.ForeignKey('users.id'))  # 分配给的工程师ID

    assigned_to_name = db.Column(db.String(50))  # 分配给的工程师姓名

    assigned_department = db.Column(db.String(100))  # 分配部门

    

    # 时间信息

    requested_at = db.Column(db.DateTime, default=datetime.utcnow)  # 请求时间

    scheduled_date = db.Column(db.Date)  # 计划完成日期

    due_date = db.Column(db.Date)  # 到期日期

    actual_start_date = db.Column(db.DateTime)  # 实际开始时间

    actual_end_date = db.Column(db.DateTime)  # 实际结束时间

    resolution_time = db.Column(db.Float)  # 解决时间（小时）

    

    # 状态信息

    status = db.Column(db.String(20), default='open')  # 状态: open, assigned, in_progress, on_hold, resolved, closed, cancelled

    resolution = db.Column(db.Text)  # 解决方案

    resolution_notes = db.Column(db.Text)  # 解决备注

    

    # SLA相关信息

    sla_level = db.Column(db.String(20))  # SLA级别

    sla_response_time = db.Column(db.Integer)  # 响应时间（小时）

    sla_resolution_time = db.Column(db.Integer)  # 解决时间（小时）

    actual_response_time = db.Column(db.Float)  # 实际响应时间（小时）

    sla_policy_id = db.Column(db.Integer, db.ForeignKey('sla_policies.id'), nullable=True)  # 关联SLA策略

    sla_response_met = db.Column(db.Boolean, nullable=True)  # 响应是否达标

    sla_resolution_met = db.Column(db.Boolean, nullable=True)  # 解决是否达标

    sla_status = db.Column(db.String(20), default='pending')  # pending/monitoring/met/breached

    breached_at = db.Column(db.DateTime, nullable=True)  # 首次违约时间

    

    # 关联设备/资产

    device_id = db.Column(db.Integer, db.ForeignKey('devices.id'))

    device_name = db.Column(db.String(100))

    asset_id = db.Column(db.Integer, db.ForeignKey('assets.id'))

    asset_name = db.Column(db.String(100))

    service_catalog_id = db.Column(db.Integer, db.ForeignKey('service_catalogs.id'), nullable=True)

    correlation_group = db.Column(db.String(100), nullable=True, comment='事件关联分组键(同组仅生成一张工单)')

    auto_created = db.Column(db.Boolean, default=False, comment='由事件关联引擎自动生成')

    is_major = db.Column(db.Boolean, default=False, comment='重大事件标记（重大事件管理实践）')

    

    # 成本信息

    estimated_hours = db.Column(db.Float)  # 预估工时

    actual_hours = db.Column(db.Float)  # 实际工时

    labor_cost = db.Column(db.Float)  # 人工成本

    material_cost = db.Column(db.Float)  # 材料成本

    total_cost = db.Column(db.Float)  # 总成本

    

    # 审批信息

    approval_required = db.Column(db.Boolean, default=False)

    approval_status = db.Column(db.String(20), default='pending')  # 审批状态

    approved_by = db.Column(db.String(50))

    approved_at = db.Column(db.DateTime)

    

    # 关闭信息

    closed_by = db.Column(db.String(50))

    closed_at = db.Column(db.DateTime)

    closure_notes = db.Column(db.Text)

    

    # 客户反馈

    customer_feedback = db.Column(db.Text)

    customer_rating = db.Column(db.Integer)  # 客户评分 1-5

    

    # 系统字段

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    created_by = db.Column(db.String(50))

    updated_by = db.Column(db.String(50))

    

    # 关系

    requester = db.relationship('User', foreign_keys=[requester_id], backref='requested_work_orders')

    assigned_to = db.relationship('User', foreign_keys=[assigned_to_id], backref='assigned_work_orders')

    device = db.relationship('Device', backref='work_orders')

    asset = db.relationship('Asset', backref='work_orders')

    sla_policy = db.relationship('SLAPolicy', backref='work_orders')

    service_catalog = db.relationship('ServiceCatalog', backref='work_orders')

    

    def __repr__(self):

        return f'<WorkOrder {self.work_order_number}: {self.title}>'

    

    def generate_work_order_number(self):

        """生成工单编号（基于日期+时间+随机串，避免并发计数冲突）"""

        if not self.work_order_number:

            date_str = datetime.now().strftime('%Y%m%d%H%M%S')

            suffix = uuid.uuid4().hex[:6].upper()

            self.work_order_number = f'WO{date_str}{suffix}'

        return self.work_order_number

    

    def calculate_resolution_time(self):

        """计算解决时间"""

        if self.actual_start_date and self.actual_end_date:

            duration = (self.actual_end_date - self.actual_start_date).total_seconds() / 3600

            self.resolution_time = round(duration, 2)

        return self.resolution_time

    

    def update_sla_compliance(self):

        """基于实际耗时更新SLA达标情况并持久化"""

        if self.actual_response_time is not None and self.sla_response_time:

            self.sla_response_met = self.actual_response_time <= self.sla_response_time

        if self.resolution_time is not None and self.sla_resolution_time:

            self.sla_resolution_met = self.resolution_time <= self.sla_resolution_time

        return self



    def apply_sla_policy(self):

        """根据工单类型与优先级匹配SLA策略，写入响应/解决时限（小时）"""

        pol = None

        if self.sla_policy_id:

            pol = SLAPolicy.query.get(self.sla_policy_id)

        if pol is None:

            pol = SLAPolicy.query.filter_by(

                category=self.work_order_type, priority=self.priority, is_active=True

            ).first()

        if pol is None:

            pol = SLAPolicy.query.filter_by(

                category=self.work_order_type, is_active=True

            ).first()

        if pol:

            self.sla_policy_id = pol.id

            if pol.response_time and self.sla_response_time is None:

                self.sla_response_time = pol.response_time

            if pol.resolution_time and self.sla_resolution_time is None:

                self.sla_resolution_time = pol.resolution_time

            self.sla_level = pol.name

        return self



    def compute_sla_status(self, now=None):

        """实时计算并持久化工单SLA状态（违约检测与升级依据）"""

        now = now or datetime.utcnow()

        if self.status in ('resolved', 'closed', 'cancelled'):

            if self.resolution_time is not None and self.sla_resolution_time:

                self.sla_resolution_met = self.resolution_time <= self.sla_resolution_time

            if self.actual_response_time is not None and self.sla_response_time:

                self.sla_response_met = self.actual_response_time <= self.sla_response_time

            self.sla_status = 'met' if (

                self.sla_response_met is not False and self.sla_resolution_met is not False

            ) else 'breached'

            return self.sla_status

        # 进行中：依据SLA时限实时判定违约

        breached = False

        if self.sla_response_time and self.actual_response_time is None:

            limit = self.requested_at + timedelta(hours=self.sla_response_time)

            if now > limit:

                breached = True

        if self.sla_resolution_time:

            base = self.actual_start_date or self.requested_at

            limit = base + timedelta(hours=self.sla_resolution_time)

            if now > limit:

                breached = True

        if breached:

            if self.sla_status != 'breached':

                self.breached_at = now

            self.sla_status = 'breached'

        else:

            self.sla_status = 'monitoring'

        return self.sla_status





class InspectionTask(db.Model):

    """巡检任务模型"""

    __tablename__ = 'inspection_tasks'

    

    id = db.Column(db.Integer, primary_key=True)

    

    # 任务基本信息

    task_number = db.Column(db.String(50), unique=True, nullable=False)  # 任务编号

    title = db.Column(db.String(200), nullable=False)  # 任务标题

    

    # 巡检类型

    inspection_type = db.Column(db.String(50), nullable=False)  # 巡检类型: daily, weekly, monthly, quarterly, annual, special

    template_id = db.Column(db.Integer, db.ForeignKey('inspection_templates.id'))  # 巡检模板ID

    

    # 巡检对象

    device_id = db.Column(db.Integer, db.ForeignKey('devices.id'))  # 关联设备

    location_id = db.Column(db.Integer, db.ForeignKey('locations.id'))  # 关联位置

    cabinet_id = db.Column(db.Integer, db.ForeignKey('cabinets.id'))  # 关联机柜

    

    # 时间信息

    scheduled_date = db.Column(db.Date, nullable=False)  # 计划日期

    scheduled_time = db.Column(db.String(20))  # 计划时间

    due_date = db.Column(db.Date)  # 到期日期

    actual_date = db.Column(db.Date)  # 实际执行日期

    actual_time = db.Column(db.String(20))  # 实际执行时间

    

    # 分配信息

    assigned_to_id = db.Column(db.Integer, db.ForeignKey('users.id'))  # 分配给的巡检员

    assigned_to_name = db.Column(db.String(50))

    team_members = db.Column(db.Text)  # 团队成员

    

    # 状态信息

    status = db.Column(db.String(20), default='pending')  # 状态: pending, in_progress, completed, cancelled, overdue

    completion_percentage = db.Column(db.Float, default=0.0)  # 完成百分比

    

    # 巡检结果

    result_id = db.Column(db.Integer, db.ForeignKey('inspection_results.id'), nullable=True)  # 改为可为空

    overall_result = db.Column(db.String(20))  # 总体结果: passed, failed, warning



    # 详细检查

    checklist_items = db.Column(db.Text)  # 检查项目（JSON格式）

    checklist_results = db.Column(db.Text)  # 检查结果（JSON格式）

    

    # 问题发现

    issues_found = db.Column(db.Text)  # 发现的问题

    recommendations = db.Column(db.Text)  # 建议

    

    # 附件和备注

    attachments = db.Column(db.Text)  # 附件

    notes = db.Column(db.Text)  # 备注

    

    # 提醒设置

    reminder_days = db.Column(db.Integer, default=0)  # 提前提醒天数

    reminder_sent = db.Column(db.Boolean, default=False)  # 提醒是否已发送

    

    # 系统字段

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    created_by = db.Column(db.String(50))

    updated_by = db.Column(db.String(50))

    

    # 关系

    template = db.relationship('InspectionTemplate', backref='tasks')

    device = db.relationship('Device', backref='inspection_tasks')

    location = db.relationship('Location', backref='inspection_tasks')

    cabinet = db.relationship('Cabinet', backref='inspection_tasks')

    assigned_to = db.relationship('User', foreign_keys=[assigned_to_id], backref='assigned_inspection_tasks')

    







    def __repr__(self):

        return f'<InspectionTask {self.task_number}: {self.title}>'

    

    def generate_task_number(self):

        """生成任务编号（基于日期+时间+随机串，避免并发计数冲突）"""

        if not self.task_number:

            date_str = datetime.now().strftime('%Y%m%d%H%M%S')

            suffix = uuid.uuid4().hex[:6].upper()

            self.task_number = f'IT{date_str}{suffix}'

        return self.task_number

    

    def update_status(self):

        """更新任务状态"""

        today = datetime.now().date()

        

        if self.status == 'completed':

            return

        

        if self.scheduled_date < today and self.status != 'completed':

            self.status = 'overdue'

        elif self.scheduled_date == today and self.status == 'pending':

            self.status = 'today'





class InspectionTemplate(db.Model):

    """巡检模板模型"""

    __tablename__ = 'inspection_templates'

    

    id = db.Column(db.Integer, primary_key=True)

    

    # 模板基本信息

    name = db.Column(db.String(100), nullable=False, unique=True)  # 模板名称

    description = db.Column(db.Text)  # 模板描述

    

    # 模板类型

    template_type = db.Column(db.String(50), nullable=False)  # 模板类型: daily, weekly, monthly, quarterly, annual, special

    category = db.Column(db.String(50))  # 模板类别

    

    # 适用对象

    applicable_to = db.Column(db.String(50))  # 适用对象: all, device, location, cabinet

    device_type = db.Column(db.String(50))  # 设备类型（如适用）

    

    # 检查项目

    items = db.Column(db.Text, nullable=False)  # 检查项目（JSON格式或文本）

    item_count = db.Column(db.Integer, default=0)  # 项目数量

    

    # 检查标准

    standards = db.Column(db.Text)  # 检查标准

    pass_criteria = db.Column(db.Text)  # 通过标准

    

    # 预计时间

    estimated_time_minutes = db.Column(db.Integer, default=30)  # 预计时间（分钟）

    

    # 频率设置

    frequency_days = db.Column(db.Integer)  # 频率（天）

    reminder_days = db.Column(db.Integer, default=1)  # 提醒天数

    

    # 状态

    is_active = db.Column(db.Boolean, default=True)

    is_default = db.Column(db.Boolean, default=False)

    

    # 系统字段

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    created_by = db.Column(db.String(50))

    updated_by = db.Column(db.String(50))

    

    def __repr__(self):

        return f'<InspectionTemplate {self.name}>'

    

    def update_item_count(self):

        """更新项目数量"""

        if self.items:

            # 假设items是JSON数组或每行一个项目的文本

            if self.items.startswith('['):

                # JSON格式

                import json

                items_list = json.loads(self.items)

                self.item_count = len(items_list)

            else:

                # 文本格式，每行一个项目

                items_list = [item.strip() for item in self.items.split('\n') if item.strip()]

                self.item_count = len(items_list)

        return self.item_count





class InspectionResult(db.Model):

    """巡检结果模型"""

    __tablename__ = 'inspection_results'

    

    id = db.Column(db.Integer, primary_key=True)

    

    # 结果基本信息

    result_number = db.Column(db.String(50), unique=True, nullable=False)  # 结果编号

    task_id = db.Column(db.Integer, db.ForeignKey('inspection_tasks.id'), nullable=False)  # 关联任务

    

    # 巡检信息

    inspection_date = db.Column(db.Date, nullable=False)  # 巡检日期

    inspection_time = db.Column(db.String(20))  # 巡检时间

    inspector_id = db.Column(db.Integer, db.ForeignKey('users.id'))  # 巡检员ID

    inspector_name = db.Column(db.String(50))  # 巡检员姓名

    

    # 总体结果

    overall_result = db.Column(db.String(20), nullable=False)  # 总体结果: passed, failed, warning

    score = db.Column(db.Float)  # 得分（百分比）

    

    # 详细结果

    checklist_items = db.Column(db.Text)  # 检查项目（JSON格式）

    checklist_results = db.Column(db.Text)  # 检查结果（JSON格式）

    

    # 统计信息

    total_items = db.Column(db.Integer, default=0)  # 总项目数

    passed_items = db.Column(db.Integer, default=0)  # 通过项目数

    failed_items = db.Column(db.Integer, default=0)  # 失败项目数

    warning_items = db.Column(db.Integer, default=0)  # 警告项目数

    skipped_items = db.Column(db.Integer, default=0)  # 跳过项目数

    

    # 问题发现

    issues_found = db.Column(db.Text)  # 发现的问题

    critical_issues = db.Column(db.Integer, default=0)  # 严重问题数

    major_issues = db.Column(db.Integer, default=0)  # 主要问题数

    minor_issues = db.Column(db.Integer, default=0)  # 次要问题数

    

    # 建议和措施

    recommendations = db.Column(db.Text)  # 建议

    actions_taken = db.Column(db.Text)  # 已采取措施

    follow_up_actions = db.Column(db.Text)  # 后续措施

    

    # 附件

    attachments = db.Column(db.Text)  # 附件列表

    photos = db.Column(db.Text)  # 照片列表

    

    # 审批信息

    approval_status = db.Column(db.String(20), default='pending')  # 审批状态

    approved_by = db.Column(db.String(50))

    approved_at = db.Column(db.DateTime)

    

    # 系统字段

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    

    # 关系

    task = db.relationship('InspectionTask', foreign_keys=[task_id], backref='inspection_result', uselist=False)

    inspector = db.relationship('User', foreign_keys=[inspector_id], backref='inspection_results')

    

    def __repr__(self):

        return f'<InspectionResult {self.result_number}>'

    

    def generate_result_number(self):

        """生成结果编号（基于日期+时间+随机串，避免并发计数冲突）"""

        if not self.result_number:

            date_str = datetime.now().strftime('%Y%m%d%H%M%S')

            suffix = uuid.uuid4().hex[:6].upper()

            self.result_number = f'IR{date_str}{suffix}'

        return self.result_number

    

    def calculate_score(self):

        """计算巡检得分"""

        if self.total_items > 0:

            self.score = round((self.passed_items / self.total_items) * 100, 2)

        return self.score

    

    def update_statistics(self):

        """更新统计信息"""

        if self.checklist_results:

            try:

                import json

                results = json.loads(self.checklist_results)

                self.total_items = len(results)

                self.passed_items = sum(1 for r in results if r.get('result') == 'passed')

                self.failed_items = sum(1 for r in results if r.get('result') == 'failed')

                self.warning_items = sum(1 for r in results if r.get('result') == 'warning')

                self.skipped_items = sum(1 for r in results if r.get('result') == 'skipped')

                self.calculate_score()

            except:

                pass





class ChangeAffectedDevice(db.Model):

    """变更影响的设备关联表（支持影响分析）"""

    __tablename__ = 'change_affected_devices'



    id = db.Column(db.Integer, primary_key=True)

    change_id = db.Column(db.Integer, db.ForeignKey('change_requests.id'), nullable=False)

    device_id = db.Column(db.Integer, db.ForeignKey('devices.id'), nullable=False)

    note = db.Column(db.Text)



    device = db.relationship('Device', backref='change_affected_links')





class ChangeRequest(db.Model):

    """变更请求模型"""

    __tablename__ = 'change_requests'

    

    id = db.Column(db.Integer, primary_key=True)

    

    # 变更基本信息

    change_number = db.Column(db.String(50), unique=True, nullable=False)  # 变更编号

    title = db.Column(db.String(200), nullable=False)  # 变更标题

    description = db.Column(db.Text)  # 变更描述

    

    # 变更类型

    change_type = db.Column(db.String(50), nullable=False)  # 变更类型: emergency, standard, normal

    category = db.Column(db.String(50))  # 变更类别

    

    # 影响和风险

    impact_level = db.Column(db.String(20))  # 影响级别: low, medium, high

    risk_level = db.Column(db.String(20))  # 风险级别: low, medium, high

    impact_description = db.Column(db.Text)  # 影响描述

    risk_description = db.Column(db.Text)  # 风险描述

    

    # 计划信息

    scheduled_date = db.Column(db.Date)  # 计划日期

    scheduled_start_time = db.Column(db.String(20))  # 计划开始时间

    scheduled_end_time = db.Column(db.String(20))  # 计划结束时间

    estimated_duration_hours = db.Column(db.Float)  # 预估持续时间

    

    # 关联信息

    requester_id = db.Column(db.Integer, db.ForeignKey('users.id'))  # 请求人ID

    requester_name = db.Column(db.String(50))

    implementer_id = db.Column(db.Integer, db.ForeignKey('users.id'))  # 实施人ID

    implementer_name = db.Column(db.String(50))

    

    # 变更对象

    affected_devices = db.Column(db.Text)  # 受影响的设备（JSON格式）

    affected_services = db.Column(db.Text)  # 受影响的服务

    affected_users = db.Column(db.Text)  # 受影响的用户

    

    # 详细计划

    implementation_plan = db.Column(db.Text)  # 实施计划

    rollback_plan = db.Column(db.Text)  # 回滚计划

    test_plan = db.Column(db.Text)  # 测试计划

    

    # 状态信息

    status = db.Column(db.String(20), default='draft')  # 状态: draft, submitted, review, approved, rejected, scheduled, in_progress, completed, cancelled

    current_stage = db.Column(db.String(50))  # 当前阶段

    

    # 审批信息

    approval_status = db.Column(db.String(20), default='pending')  # 审批状态

    approver_id = db.Column(db.Integer, db.ForeignKey('users.id'))  # 审批人ID

    approver_name = db.Column(db.String(50))

    approval_date = db.Column(db.DateTime)

    approval_notes = db.Column(db.Text)  # 审批意见

    

    # CAB评审

    cab_review_required = db.Column(db.Boolean, default=False)

    cab_review_date = db.Column(db.DateTime)

    cab_members = db.Column(db.Text)  # CAB成员

    cab_review_notes = db.Column(db.Text)  # CAB评审意见

    

    # 实施结果

    actual_start_date = db.Column(db.DateTime)  # 实际开始时间

    actual_end_date = db.Column(db.DateTime)  # 实际结束时间

    actual_duration_hours = db.Column(db.Float)  # 实际持续时间

    implementation_result = db.Column(db.Text)  # 实施结果

    issues_encountered = db.Column(db.Text)  # 遇到的问题

    

    # 关闭信息

    closed_by = db.Column(db.String(50))

    closed_date = db.Column(db.DateTime)

    closure_notes = db.Column(db.Text)

    

    # 评估

    post_implementation_review = db.Column(db.Text)  # 实施后评审

    success_criteria_met = db.Column(db.Boolean)  # 成功标准是否达成

    lessons_learned = db.Column(db.Text)  # 经验教训

    

    # 系统字段

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    created_by = db.Column(db.String(50))

    updated_by = db.Column(db.String(50))

    

    # 关系

    requester = db.relationship('User', foreign_keys=[requester_id], backref='requested_change_requests')

    implementer = db.relationship('User', foreign_keys=[implementer_id], backref='implemented_change_requests')

    approver = db.relationship('User', foreign_keys=[approver_id], backref='approved_change_requests')

    affected_device_links = db.relationship('ChangeAffectedDevice', backref='change', cascade='all, delete-orphan', lazy='dynamic')

    impact_analyses = db.relationship('ChangeImpactAnalysis', backref='change', cascade='all, delete-orphan', lazy='dynamic')

    

    def __repr__(self):

        return f'<ChangeRequest {self.change_number}: {self.title}>'

    

    def generate_change_number(self):

        """Generate final change number (date+time+uuid suffix)."""

        if not self.change_number or str(self.change_number or '').startswith('TEMP-'):

            date_str = datetime.now().strftime('%Y%m%d%H%M%S')

            suffix = uuid.uuid4().hex[:6].upper()

            self.change_number = f'CR{date_str}{suffix}'

        return self.change_number



class CIDependency(db.Model):

    """CMDB 配置项(CI)之间的依赖关系（有向图）



    语义：source 依赖(depends_on / runs_on / hosts / connects_to / contains / uses) target。

    影响分析：若 target 故障，则所有 source（及其下游依赖）受影响。

    """

    __tablename__ = 'ci_dependencies'



    id = db.Column(db.Integer, primary_key=True)

    source_id = db.Column(db.Integer, db.ForeignKey('devices.id'), nullable=False, index=True)  # 依赖方（上游）

    target_id = db.Column(db.Integer, db.ForeignKey('devices.id'), nullable=False, index=True)  # 被依赖方（下游）

    dependency_type = db.Column(db.String(30), default='depends_on', nullable=False)  # depends_on/runs_on/hosts/connects_to/contains/uses

    criticality = db.Column(db.String(20), default='medium')  # low/medium/high

    description = db.Column(db.Text)

    created_by = db.Column(db.String(50))

    created_at = db.Column(db.DateTime, default=datetime.utcnow)



    source = db.relationship('Device', foreign_keys=[source_id], backref='dependencies_as_source')

    target = db.relationship('Device', foreign_keys=[target_id], backref='dependencies_as_target')



    __table_args__ = (

        db.UniqueConstraint('source_id', 'target_id', 'dependency_type', name='uq_ci_dependency'),

    )



    DEPENDENCY_TYPES = {

        'depends_on': '依赖',

        'runs_on': '运行于',

        'hosts': '承载',

        'connects_to': '连接至',

        'contains': '包含',

        'uses': '使用',

    }

    CRITICALITY_RANK = {'low': 1, 'medium': 2, 'high': 3}



    def to_dict(self):

        return {

            'id': self.id,

            'source_id': self.source_id,

            'target_id': self.target_id,

            'source_name': self.source.name if self.source else None,

            'target_name': self.target.name if self.target else None,

            'dependency_type': self.dependency_type,

            'dependency_type_label': self.DEPENDENCY_TYPES.get(self.dependency_type, self.dependency_type),

            'criticality': self.criticality,

            'description': self.description or '',

            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M') if self.created_at else None,

        }



    def __repr__(self):

        return f'<CIDependency {self.source_id}->{self.target_id} {self.dependency_type}>'





class ChangeApproval(db.Model):

    """变更审批链中的一条审批记录（按阶段 stage 顺序）"""

    __tablename__ = 'change_approvals'



    id = db.Column(db.Integer, primary_key=True)

    change_id = db.Column(db.Integer, db.ForeignKey('change_requests.id'), nullable=False, index=True)

    stage = db.Column(db.Integer, default=1)            # 审批阶段顺序（1,2,3...）

    stage_name = db.Column(db.String(50))               # 技术审核 / 经理审批 / CAB评审

    approver_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)  # 指定审批人；为空表示任意具备权限者

    approver_name = db.Column(db.String(50))

    status = db.Column(db.String(20), default='pending')  # pending/approved/rejected/skipped

    comment = db.Column(db.Text)

    decided_at = db.Column(db.DateTime)

    decided_by = db.Column(db.String(50))



    change = db.relationship('ChangeRequest', backref=db.backref('approval_chain', cascade='all, delete-orphan', lazy='dynamic'))

    approver = db.relationship('User', backref='change_approvals')



    def to_dict(self):

        return {

            'id': self.id,

            'change_id': self.change_id,

            'stage': self.stage,

            'stage_name': self.stage_name,

            'approver_id': self.approver_id,

            'approver_name': self.approver_name,

            'status': self.status,

            'comment': self.comment or '',

            'decided_at': self.decided_at.strftime('%Y-%m-%d %H:%M') if self.decided_at else None,

            'decided_by': self.decided_by,

        }



    def __repr__(self):

        return f'<ChangeApproval change={self.change_id} stage={self.stage} {self.status}>'





class CABConfig(db.Model):

    """变更顾问委员会(CAB)配置：审批阶段定义



    stages_json 结构：[{"name":"技术审核","approver_ids":[2,3],"mode":"any"},

                       {"name":"经理审批","approver_ids":[5],"mode":"all"},

                       {"name":"CAB评审","approver_ids":[],"mode":"any"}]

    mode=any 表示任一审批人通过即阶段通过；mode=all 表示需全部通过。

    approver_ids 为空表示“任意具备 change:cab:approve 权限者”均可审批该阶段。

    """

    __tablename__ = 'cab_config'



    id = db.Column(db.Integer, primary_key=True)

    name = db.Column(db.String(100), default='默认CAB')

    description = db.Column(db.Text)

    is_active = db.Column(db.Boolean, default=True)

    stages_json = db.Column(db.Text)

    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    updated_by = db.Column(db.String(50))



    def get_stages(self):

        try:

            return json.loads(self.stages_json or '[]') if self.stages_json else []

        except Exception:

            return []



    def set_stages(self, stages):

        self.stages_json = json.dumps(stages, ensure_ascii=False)



    def __repr__(self):

        return f'<CABConfig {self.name} active={self.is_active}>'





class Project(db.Model):

    """项目模型"""

    __tablename__ = 'projects'

    

    id = db.Column(db.Integer, primary_key=True)

    project_code = db.Column(String(50), unique=True, nullable=False)

    project_name = db.Column(String(100), nullable=False)

    

    # 项目信息

    description = db.Column(Text)

    start_date = db.Column(db.DateTime)

    end_date = db.Column(db.DateTime)

    budget = db.Column(Float)

    actual_cost = db.Column(Float, default=0.0)

    

    # 状态信息

    status = db.Column(String(20), default='planning')  # planning, in_progress, completed, cancelled, on_hold

    priority = db.Column(String(20), default='medium')  # low, medium, high, critical

    

    # 负责人信息

    manager_id = db.Column(db.Integer, ForeignKey('users.id'))

    manager_name = db.Column(String(50))

    

    # 部门信息

    department = db.Column(String(100))

    

    # 系统字段

    created_at = db.Column(DateTime, default=_utcnow)

    updated_at = db.Column(DateTime, default=_utcnow, onupdate=_utcnow)

    

    # 关系定义 - 使用字符串形式延迟解析，避免循环引用

    manager = relationship('User', foreign_keys=[manager_id])

    # 关键修改：使用字符串 'SparePartUsage' 而不是直接引用类

    spare_part_usages = relationship(

        'SparePartUsage', 

        back_populates='project',

        lazy='dynamic'  # 保持懒加载，提升性能

    )

    

    def __repr__(self):

        return f'<Project {self.project_code}: {self.project_name}>'









class ProblemRecord(db.Model):

    """问题管理"""

    __tablename__ = 'problem_records'



    id = db.Column(db.Integer, primary_key=True)

    problem_number = db.Column(db.String(64), unique=True, nullable=False, comment='问题编号')

    title = db.Column(db.String(200), nullable=False, comment='问题标题')

    description = db.Column(db.Text, comment='问题描述')

    category = db.Column(db.String(50), comment='分类: network/server/security/application')

    severity = db.Column(db.String(20), default='medium', comment='严重度')

    priority = db.Column(db.String(20), default='medium', comment='优先级')

    status = db.Column(db.String(20), default='identified', comment='状态: identified/investigating/resolved/closed')

    root_cause = db.Column(db.Text, comment='根因')

    resolution = db.Column(db.Text, comment='解决方案')

    workaround = db.Column(db.Text, comment='临时方案')

    known_error = db.Column(db.Boolean, default=False, comment='是否已知错误')

    known_error_ref = db.Column(db.String(100), comment='已知错误引用')

    related_work_order_ids = db.Column(db.Text, comment='关联工单ID列表JSON')

    related_change_ids = db.Column(db.Text, comment='关联变更ID列表JSON')

    identified_date = db.Column(db.DateTime, comment='发现日期')

    resolved_date = db.Column(db.DateTime, comment='解决日期')

    assigned_to = db.Column(db.Integer, db.ForeignKey('users.id'))

    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)



    # ITSM 关联：绑定受影响配置项(CI)

    device_id = db.Column(db.Integer, db.ForeignKey('devices.id'), nullable=True)

    asset_id = db.Column(db.Integer, db.ForeignKey('assets.id'), nullable=True)



    assignee = db.relationship('User', foreign_keys=[assigned_to], backref='assigned_problems')

    creator = db.relationship('User', foreign_keys=[created_by], backref='created_problem_records')

    device = db.relationship('Device', backref='problem_records')

    asset = db.relationship('Asset', backref='problem_records')



    def to_dict(self):

        return {

            'id': self.id,

            'problem_number': self.problem_number,

            'title': self.title,

            'category': self.category,

            'severity': self.severity,

            'status': self.status,

            'identified_date': self.identified_date.isoformat() if self.identified_date else None,

        }





class KnownError(db.Model):

    """已知错误"""

    __tablename__ = 'known_errors'



    id = db.Column(db.Integer, primary_key=True)

    ke_number = db.Column(db.String(64), unique=True, nullable=False, comment='错误编号')

    title = db.Column(db.String(200), nullable=False, comment='标题')

    description = db.Column(db.Text, comment='描述')

    symptom = db.Column(db.Text, comment='症状')

    root_cause = db.Column(db.Text, comment='根因')

    workaround = db.Column(db.Text, comment='临时方案')

    resolution = db.Column(db.Text, comment='最终方案')

    affected_components = db.Column(db.Text, comment='影响组件JSON')

    severity = db.Column(db.String(20), default='medium', comment='严重度')

    status = db.Column(db.String(20), default='active', comment='状态: active/resolved')

    linked_problem_id = db.Column(db.Integer, db.ForeignKey('problem_records.id'))

    knowledge_article_id = db.Column(db.Integer, db.ForeignKey('knowledge_articles.id'), nullable=True, comment='关联知识库文章')

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)



    linked_problem = db.relationship('ProblemRecord', backref='known_errors')

    knowledge_article = db.relationship('KnowledgeArticle', backref='known_errors')





class ServiceCatalog(db.Model):

    """服务目录"""

    __tablename__ = 'service_catalogs'



    id = db.Column(db.Integer, primary_key=True)

    name = db.Column(db.String(200), nullable=False, comment='服务名称')

    description = db.Column(db.Text, comment='服务描述')

    category = db.Column(db.String(50), comment='分类: incident/request/change')

    service_type = db.Column(db.String(30), default='request', comment='类型: request/incident/change')

    delivery_process = db.Column(db.Text, comment='交付流程JSON')

    estimated_fulfillment_time = db.Column(db.Integer, comment='预计履行时间(分钟)')

    cost = db.Column(db.Numeric(10, 2), default=0, comment='成本')

    chargeable = db.Column(db.Boolean, default=False, comment='是否收费')

    enabled = db.Column(db.Boolean, default=True, comment='是否启用')

    display_order = db.Column(db.Integer, default=0, comment='排序')

    form_template = db.Column(db.Text, comment='表单模板JSON')

    sla_policy_id = db.Column(db.Integer, db.ForeignKey('sla_policies.id'), nullable=True, comment='关联SLA策略')

    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)



    sla_policy = db.relationship('SLAPolicy', backref='service_catalogs')

    # 设备映射(用于真实可用率/影响分析按服务聚合)与服务满意度调查

    mapped_devices = db.relationship(

        'Device', secondary='service_catalog_devices',

        backref=db.backref('mapped_services', lazy='dynamic'), lazy='dynamic'

    )

    csat_surveys = db.relationship('CSATSurvey', backref='service_catalog', lazy='dynamic',

                                   cascade='all, delete-orphan')



    def to_dict(self):

        return {

            'id': self.id,

            'name': self.name,

            'category': self.category,

            'service_type': self.service_type,

            'estimated_fulfillment_time': self.estimated_fulfillment_time,

            'enabled': self.enabled,

        }





class CSIImprovement(db.Model):

    """持续改进(CSI)登记册 —— ITIL 持续改进实践"""

    __tablename__ = 'csi_improvements'



    id = db.Column(db.Integer, primary_key=True)

    code = db.Column(db.String(64), unique=True, nullable=False, comment='改进编号')

    title = db.Column(db.String(200), nullable=False, comment='改进标题')

    description = db.Column(db.Text, comment='改进说明')

    source_type = db.Column(db.String(30), default='audit', comment='来源: problem/change/incident/audit/survey')

    source_id = db.Column(db.Integer, comment='来源记录ID')

    status = db.Column(db.String(20), default='proposed', comment='状态: proposed/approved/in_progress/completed/rejected')

    priority = db.Column(db.String(20), default='medium')

    owner_id = db.Column(db.Integer, db.ForeignKey('users.id'))

    target_metric = db.Column(db.String(100), comment='目标指标(MTTR/可用率/满意度等)')

    baseline_value = db.Column(db.Float, comment='基线值')

    target_value = db.Column(db.Float, comment='目标值')

    actual_value = db.Column(db.Float, comment='实际达成值')

    expected_benefit = db.Column(db.Text, comment='预期收益')

    review_notes = db.Column(db.Text, comment='复盘记录')

    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    completed_at = db.Column(db.DateTime)



    owner = db.relationship('User', foreign_keys=[owner_id], backref='owned_csi')

    creator = db.relationship('User', foreign_keys=[created_by], backref='created_csi')



    def to_dict(self):

        return {

            'id': self.id,

            'code': self.code,

            'title': self.title,

            'source_type': self.source_type,

            'status': self.status,

            'priority': self.priority,

            'target_metric': self.target_metric,

            'baseline_value': self.baseline_value,

            'target_value': self.target_value,

            'actual_value': self.actual_value,

            'created_at': self.created_at.isoformat() if self.created_at else None,

        }





class EventCorrelationRule(db.Model):

    """事件归一化/关联规则 —— 告警去重、抑制、归一化与升级"""

    __tablename__ = 'event_correlation_rules'



    id = db.Column(db.Integer, primary_key=True)

    name = db.Column(db.String(200), nullable=False, comment='规则名称')

    description = db.Column(db.Text, comment='规则说明')

    enabled = db.Column(db.Boolean, default=True)

    priority_order = db.Column(db.Integer, default=100, comment='执行顺序(小优先)')

    match_scope = db.Column(db.String(30), default='message', comment='匹配字段: title/message/severity/source')

    match_operator = db.Column(db.String(20), default='contains', comment='equals/contains/not_contains/regex')

    match_value = db.Column(db.String(200), comment='匹配值(正则时为正则表达式)')

    action = db.Column(db.String(30), default='suppress', comment='suppress/group/raise_severity/set_priority')

    group_by = db.Column(db.String(20), default='none', comment='none/device_id')

    suppression_window_min = db.Column(db.Integer, default=60, comment='抑制窗口(分钟)')

    new_severity = db.Column(db.String(20), comment='action=raise_severity 时使用')

    new_priority = db.Column(db.String(20), comment='action=set_priority 时使用')

    normalize_template = db.Column(db.String(200), comment='归一化标题模板，支持 {host}{ip} 占位符')

    auto_ticket = db.Column(db.Boolean, default=False, comment='分组动作时按组自动生成单一事件工单')

    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)



    def to_dict(self):

        return {

            'id': self.id,

            'name': self.name,

            'enabled': self.enabled,

            'match_scope': self.match_scope,

            'match_operator': self.match_operator,

            'match_value': self.match_value,

            'action': self.action,

            'group_by': self.group_by,

            'auto_ticket': self.auto_ticket,

        }





# ===========================================================================

# K-N. ITIL 增强：真实可用率 / CSAT / 变更影响分析 关联模型

# ===========================================================================



# 服务目录 <-> 设备 映射(多对多)，用于按服务聚合真实可用率与影响分析

service_catalog_devices = db.Table(

    'service_catalog_devices',

    db.Column('service_catalog_id', db.Integer, db.ForeignKey('service_catalogs.id'), primary_key=True),

    db.Column('device_id', db.Integer, db.ForeignKey('devices.id'), primary_key=True),

)





class AvailabilityRecord(db.Model):

    """真实可用率记录 —— 由监控/设备在线状态(DeviceMonitorLog)计算得出



    替代以往基于工单解决时长的代理算法。scope='device' 时按单设备计算；

    scope='service' 时按服务目录映射设备做「任一设备宕机即服务不可用」并集计算。

    """

    __tablename__ = 'availability_records'



    id = db.Column(db.Integer, primary_key=True)

    scope = db.Column(db.String(20), nullable=False, comment='device/service')

    device_id = db.Column(db.Integer, db.ForeignKey('devices.id'), nullable=True, index=True)

    service_catalog_id = db.Column(db.Integer, db.ForeignKey('service_catalogs.id'), nullable=True, index=True)

    period_start = db.Column(db.DateTime, nullable=False)

    period_end = db.Column(db.DateTime, nullable=False)

    total_minutes = db.Column(db.Float, nullable=False)

    down_minutes = db.Column(db.Float, default=0.0)

    availability_pct = db.Column(db.Float, nullable=False)

    incident_count = db.Column(db.Integer, default=0, comment='窗口内相关告警数')

    source = db.Column(db.String(30), default='device_monitor_log', comment='数据来源')

    created_at = db.Column(db.DateTime, default=datetime.utcnow)



    device = db.relationship('Device', backref='availability_records')

    service_catalog = db.relationship('ServiceCatalog', backref='availability_records')



    def to_dict(self):

        return {

            'id': self.id, 'scope': self.scope, 'device_id': self.device_id,

            'service_catalog_id': self.service_catalog_id,

            'period_start': self.period_start.isoformat() if self.period_start else None,

            'period_end': self.period_end.isoformat() if self.period_end else None,

            'total_minutes': self.total_minutes, 'down_minutes': self.down_minutes,

            'availability_pct': self.availability_pct, 'incident_count': self.incident_count,

            'source': self.source,

        }





class CSATSurvey(db.Model):

    """客户满意度(CSAT)调查 —— 服务目录级度量"""

    __tablename__ = 'csat_surveys'



    id = db.Column(db.Integer, primary_key=True)

    service_catalog_id = db.Column(db.Integer, db.ForeignKey('service_catalogs.id'), nullable=True, index=True)

    work_order_id = db.Column(db.Integer, db.ForeignKey('work_orders.id'), nullable=True, index=True)

    rating = db.Column(db.Integer, nullable=False, comment='评分 1-5')

    comment = db.Column(db.Text)

    channel = db.Column(db.String(20), default='portal', comment='portal/email/manual')

    respondent = db.Column(db.String(100))

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    responded_at = db.Column(db.DateTime, default=datetime.utcnow)



    work_order = db.relationship('WorkOrder', backref='csat_surveys')



    def to_dict(self):

        return {

            'id': self.id, 'service_catalog_id': self.service_catalog_id,

            'work_order_id': self.work_order_id, 'rating': self.rating,

            'comment': self.comment or '', 'channel': self.channel,

            'created_at': self.created_at.isoformat() if self.created_at else None,

        }





class ChangeImpactAnalysis(db.Model):

    """变更影响模拟结果(先算影响再实施) —— 持久化快照"""

    __tablename__ = 'change_impact_analyses'



    id = db.Column(db.Integer, primary_key=True)

    change_id = db.Column(db.Integer, db.ForeignKey('change_requests.id'), nullable=False, index=True)

    simulated_at = db.Column(db.DateTime, default=datetime.utcnow)

    direct_device_ids = db.Column(db.Text, comment='直接受影响设备ID(JSON)')

    impacted_device_ids = db.Column(db.Text, comment='级联受影响设备ID(JSON，含直接)')

    impacted_service_ids = db.Column(db.Text, comment='受影响服务目录ID(JSON)')

    affected_user_count = db.Column(db.Integer, default=0, comment='估算受影响用户数')

    downtime_estimate_min = db.Column(db.Float, default=0.0, comment='预估停机(分钟)')

    risk_score = db.Column(db.Float, default=0.0)

    risk_level = db.Column(db.String(20), default='low')

    summary = db.Column(db.Text)



    def to_dict(self):

        return {

            'id': self.id, 'change_id': self.change_id,

            'simulated_at': self.simulated_at.isoformat() if self.simulated_at else None,

            'direct_device_ids': self.direct_device_ids,

            'impacted_device_ids': self.impacted_device_ids,

            'impacted_service_ids': self.impacted_service_ids,

            'affected_user_count': self.affected_user_count,

            'downtime_estimate_min': self.downtime_estimate_min,

            'risk_score': self.risk_score, 'risk_level': self.risk_level,

            'summary': self.summary or '',

        }

