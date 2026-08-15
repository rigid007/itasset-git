from extensions import db
from datetime import datetime

class DevicePerformance(db.Model):
    """设备性能数据"""
    __tablename__ = 'device_performances'
    
    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.Integer, db.ForeignKey('devices.id'), nullable=False, index=True)
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    
    # CPU相关指标
    cpu_usage = db.Column(db.Float)  # CPU使用率百分比
    cpu_load_1 = db.Column(db.Float)  # 1分钟负载
    cpu_load_5 = db.Column(db.Float)  # 5分钟负载
    cpu_load_15 = db.Column(db.Float)  # 15分钟负载
    cpu_core_count = db.Column(db.Integer)  # CPU核心数
    
    # 内存相关指标
    memory_usage = db.Column(db.Float)  # 内存使用率百分比
    memory_total = db.Column(db.BigInteger)  # 总内存（字节）
    memory_used = db.Column(db.BigInteger)  # 已用内存（字节）
    memory_free = db.Column(db.BigInteger)  # 空闲内存（字节）
    memory_cached = db.Column(db.BigInteger)  # 缓存内存（字节）
    memory_buffer = db.Column(db.BigInteger)  # 缓冲内存（字节）
    
    # 磁盘相关指标
    disk_usage = db.Column(db.Float)  # 磁盘使用率百分比
    disk_total = db.Column(db.BigInteger)  # 总磁盘空间（字节）
    disk_used = db.Column(db.BigInteger)  # 已用磁盘空间（字节）
    disk_free = db.Column(db.BigInteger)  # 空闲磁盘空间（字节）
    disk_read_bytes = db.Column(db.BigInteger)  # 读取字节数
    disk_write_bytes = db.Column(db.BigInteger)  # 写入字节数
    disk_read_ops = db.Column(db.Integer)  # 读取操作数
    disk_write_ops = db.Column(db.Integer)  # 写入操作数
    
    # 网络相关指标
    network_in_bytes = db.Column(db.BigInteger)  # 接收字节数
    network_out_bytes = db.Column(db.BigInteger)  # 发送字节数
    network_in_packets = db.Column(db.Integer)  # 接收包数
    network_out_packets = db.Column(db.Integer)  # 发送包数
    network_in_errors = db.Column(db.Integer)  # 接收错误数
    network_out_errors = db.Column(db.Integer)  # 发送错误数
    
    # 系统指标
    uptime = db.Column(db.BigInteger)  # 运行时间（秒）
    process_count = db.Column(db.Integer)  # 进程数
    user_count = db.Column(db.Integer)  # 用户数
    
    # 温度和其他硬件指标
    temperature = db.Column(db.Float)  # 温度（摄氏度）
    fan_speed = db.Column(db.Integer)  # 风扇转速（RPM）
    power_usage = db.Column(db.Float)  # 功耗（瓦特）
    
    # 自定义指标
    custom_metric_1 = db.Column(db.Float)
    custom_metric_2 = db.Column(db.Float)
    custom_metric_3 = db.Column(db.String(100))
    
    # 性能状态
    performance_status = db.Column(db.String(20), default='normal')  # normal, warning, critical
    
    # 采集信息
    collection_method = db.Column(db.String(50))  # snmp, ssh, agent, api
    response_time = db.Column(db.Float)  # 采集响应时间（毫秒）
    error_message = db.Column(db.Text)  # 错误信息
    
    # 关系定义 - 修正这里的 backref
    device = db.relationship('Device', backref=db.backref('performance_records', lazy='dynamic'))
    
    # 创建索引
    __table_args__ = (
        db.Index('idx_device_timestamp', 'device_id', 'timestamp'),
        db.Index('idx_timestamp', 'timestamp'),
        db.Index('idx_performance_status', 'performance_status'),
    )
    
    def __repr__(self):
        return f'<DevicePerformance device_id={self.device_id} timestamp={self.timestamp}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'device_id': self.device_id,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'cpu_usage': self.cpu_usage,
            'memory_usage': self.memory_usage,
            'disk_usage': self.disk_usage,
            'performance_status': self.performance_status,
            'response_time': self.response_time
        }


class PerformanceThreshold(db.Model):
    """性能阈值配置"""
    __tablename__ = 'performance_thresholds'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    device_type = db.Column(db.String(50))  # 设备类型，为空表示通用
    vendor = db.Column(db.String(50))
    model = db.Column(db.String(50))
    
    # CPU阈值
    cpu_warning = db.Column(db.Float, default=70.0)  # 警告阈值
    cpu_critical = db.Column(db.Float, default=90.0)  # 严重阈值
    
    # 内存阈值
    memory_warning = db.Column(db.Float, default=75.0)
    memory_critical = db.Column(db.Float, default=90.0)
    
    # 磁盘阈值
    disk_warning = db.Column(db.Float, default=80.0)
    disk_critical = db.Column(db.Float, default=95.0)
    
    # 网络阈值
    network_warning = db.Column(db.Float, default=80.0)  # 网络利用率
    network_critical = db.Column(db.Float, default=95.0)
    
    # 温度阈值
    temp_warning = db.Column(db.Float, default=60.0)  # 温度警告
    temp_critical = db.Column(db.Float, default=80.0)  # 温度严重
    
    # 其他阈值
    ping_warning = db.Column(db.Float, default=100.0)  # ping延迟警告（毫秒）
    ping_critical = db.Column(db.Float, default=500.0)  # ping延迟严重
    
    process_count_warning = db.Column(db.Integer, default=500)  # 进程数警告
    uptime_warning = db.Column(db.BigInteger, default=86400)  # 运行时间警告（秒）
    
    # 通知设置
    notify_warning = db.Column(db.Boolean, default=True)
    notify_critical = db.Column(db.Boolean, default=True)
    notify_email = db.Column(db.Boolean, default=True)
    notify_sms = db.Column(db.Boolean, default=False)
    
    is_active = db.Column(db.Boolean, default=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'device_type': self.device_type,
            'vendor': self.vendor,
            'model': self.model,
            'cpu_warning': self.cpu_warning,
            'cpu_critical': self.cpu_critical,
            'memory_warning': self.memory_warning,
            'memory_critical': self.memory_critical,
            'is_active': self.is_active
        }


class PerformanceBaseline(db.Model):
    """性能基线"""
    __tablename__ = 'performance_baselines'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    device_id = db.Column(db.Integer, db.ForeignKey('devices.id'))
    device_type = db.Column(db.String(50))
    
    # 基线时间段
    start_time = db.Column(db.Time)  # 开始时间（如09:00:00）
    end_time = db.Column(db.Time)    # 结束时间（如18:00:00）
    weekdays = db.Column(db.String(20))  # 工作日，如1,2,3,4,5 或 mon,tue,wed,thu,fri
    
    # 基线值
    avg_cpu = db.Column(db.Float)  # 平均CPU使用率
    max_cpu = db.Column(db.Float)  # 最大CPU使用率
    avg_memory = db.Column(db.Float)  # 平均内存使用率
    max_memory = db.Column(db.Float)  # 最大内存使用率
    avg_disk = db.Column(db.Float)  # 平均磁盘使用率
    max_disk = db.Column(db.Float)  # 最大磁盘使用率
    
    # 标准差（用于检测异常）
    std_cpu = db.Column(db.Float)
    std_memory = db.Column(db.Float)
    std_disk = db.Column(db.Float)
    
    # 样本数量和数据时间段
    sample_count = db.Column(db.Integer)
    data_start_date = db.Column(db.Date)
    data_end_date = db.Column(db.Date)
    
    is_active = db.Column(db.Boolean, default=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    device = db.relationship('Device', backref='performance_baselines')
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'device_id': self.device_id,
            'device_type': self.device_type,
            'avg_cpu': self.avg_cpu,
            'avg_memory': self.avg_memory,
            'avg_disk': self.avg_disk,
            'sample_count': self.sample_count,
            'is_active': self.is_active
        }


class PerformanceAlert(db.Model):
    """性能告警"""
    __tablename__ = 'performance_alerts'
    
    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.Integer, db.ForeignKey('devices.id'), nullable=False)
    metric_name = db.Column(db.String(50), nullable=False)  # cpu, memory, disk, etc.
    metric_value = db.Column(db.Float, nullable=False)
    threshold_value = db.Column(db.Float, nullable=False)
    severity = db.Column(db.String(20), nullable=False)  # warning, critical
    alert_type = db.Column(db.String(20))  # threshold, anomaly, baseline
    
    # 基线相关（如果是基线告警）
    baseline_id = db.Column(db.Integer, db.ForeignKey('performance_baselines.id'))
    deviation = db.Column(db.Float)  # 偏离标准差的倍数
    
    description = db.Column(db.Text)
    acknowledged = db.Column(db.Boolean, default=False)
    acknowledged_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    acknowledged_at = db.Column(db.DateTime)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    resolved_at = db.Column(db.DateTime)
    
    device = db.relationship('Device', backref='performance_alerts')
    baseline = db.relationship('PerformanceBaseline', backref='alerts')
    
    def to_dict(self):
        return {
            'id': self.id,
            'device_id': self.device_id,
            'metric_name': self.metric_name,
            'metric_value': self.metric_value,
            'threshold_value': self.threshold_value,
            'severity': self.severity,
            'alert_type': self.alert_type,
            'description': self.description,
            'acknowledged': self.acknowledged,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'resolved_at': self.resolved_at.isoformat() if self.resolved_at else None
        }
class PerformanceData(db.Model):
    """设备性能数据表"""
    __tablename__ = 'performance_data'

    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.Integer, db.ForeignKey('devices.id'), nullable=False, index=True)
    
    # 性能指标
    cpu_usage = db.Column(db.Float, nullable=True)       # CPU使用率（百分比）
    memory_usage = db.Column(db.Float, nullable=True)    # 内存使用率（百分比）
    disk_usage = db.Column(db.Float, nullable=True)      # 磁盘使用率（百分比）
    
    # 可选：其他常见指标
    load_average = db.Column(db.Float, nullable=True)    # 系统负载
    network_in = db.Column(db.BigInteger, nullable=True) # 网络入流量（字节）
    network_out = db.Column(db.BigInteger, nullable=True) # 网络出流量（字节）
    disk_read = db.Column(db.BigInteger, nullable=True)  # 磁盘读取（字节）
    disk_write = db.Column(db.BigInteger, nullable=True) # 磁盘写入（字节）
    
    # 时间戳
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # 关系
    device = db.relationship('Device', backref=db.backref('performance_data', lazy='dynamic', cascade='all, delete-orphan'))
    
    __table_args__ = (
        db.Index('idx_performance_device_time', 'device_id', 'timestamp'),
        db.Index('idx_performance_timestamp', 'timestamp'),
    )
    
    def __repr__(self):
        return f'<PerformanceData {self.device_id} @ {self.timestamp}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'device_id': self.device_id,
            'device_name': self.device.name if self.device else None,
            'cpu_usage': self.cpu_usage,
            'memory_usage': self.memory_usage,
            'disk_usage': self.disk_usage,
            'load_average': self.load_average,
            'network_in': self.network_in,
            'network_out': self.network_out,
            'disk_read': self.disk_read,
            'disk_write': self.disk_write,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
        }