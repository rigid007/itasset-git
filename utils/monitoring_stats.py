from flask import current_app
from extensions import db
from datetime import datetime, timedelta

# 导入所有需要的模型
from models import (
    Alert, AlertRule, DeviceMonitor, DeviceMonitorConfig, MonitorData,
    MonitorLog, MonitorSchedule, MonitorSetting, NotificationConfig,
)

def get_monitor_data_size():
    """获取监控数据表大小"""
    try:
        count = MonitorData.query.count()
        return f"{count} 条记录"
    except Exception as e:
        current_app.logger.error(f"获取监控数据表大小失败: {e}")
        return "统计失败"
    

def get_alert_rule_count():
    """获取告警规则数量"""
    try:
        return AlertRule.query.count()
    except Exception as e:
        current_app.logger.error(f"获取告警规则数量失败: {e}")
        return 0

def get_last_monitor_time():
    """获取最近监控时间"""
    try:
        last_log = MonitorLog.query.order_by(MonitorLog.created_at.desc()).first()
        if last_log and last_log.created_at:
            return last_log.created_at.strftime('%Y-%m-%d %H:%M:%S')
        return "无记录"
    except Exception as e:
        current_app.logger.error(f"获取最近监控时间失败: {e}")
        return "无记录"


# 修改 get_enabled_device_monitor_count 函数
def get_enabled_device_monitor_count():
    """获取启用的设备监控数量"""
    try:
        # 方法1: 从 DeviceMonitor 表获取
        count = DeviceMonitor.query.filter_by(enabled=True).count()
        if count > 0:
            return count
        
        # 方法2: 从 DeviceMonitorConfig 表获取
        return DeviceMonitorConfig.query.filter_by(enabled=True).count()
    except Exception as e:
        current_app.logger.error(f"获取启用的设备监控数量失败: {e}")
        return 0

def get_active_alert_count():
    """获取活跃告警数量"""
    try:
        return Alert.query.filter_by(status='active', resolved=False).count()
    except Exception as e:
        current_app.logger.error(f"获取活跃告警数量失败: {e}")
        return 0

def get_global_settings():
    """获取全局设置（按分类分组）"""
    try:
        # 获取所有设置分类
        categories = db.session.query(MonitorSetting.category).distinct().all()
        
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
        
        return global_settings
    except Exception as e:
        current_app.logger.error(f"获取全局设置失败: {e}")
        return {}

def get_schedules():
    """获取所有监控调度任务"""
    try:
        return MonitorSchedule.query.order_by(MonitorSchedule.name).all()
    except Exception as e:
        current_app.logger.error(f"获取监控调度任务失败: {e}")
        return []

def get_notifications():
    """获取所有通知配置"""
    try:
        return NotificationConfig.query.order_by(NotificationConfig.name).all()
    except Exception as e:
        current_app.logger.error(f"获取通知配置失败: {e}")
        return []

def get_device_config_count():
    """获取设备监控配置数量"""
    try:
        return DeviceMonitorConfig.query.count()
    except Exception as e:
        current_app.logger.error(f"获取设备监控配置数量失败: {e}")
        return 0

def get_monitoring_status():
    """获取监控系统整体状态"""
    try:
        # 检查是否有启用的调度任务
        enabled_schedules = MonitorSchedule.query.filter_by(enabled=True).count()
        
        # 检查最近24小时是否有监控数据
        time_24h_ago = datetime.now() - timedelta(hours=24)
        recent_monitor_count = MonitorData.query.filter(
            MonitorData.collected_at >= time_24h_ago
        ).count()
        
        # 检查是否有未处理的告警
        unhandled_alerts = Alert.query.filter_by(
            resolved=False,
            status='active'
        ).count()
        
        # 综合判断系统状态
        if unhandled_alerts > 10:
            return {"status": "warning", "message": f"有{unhandled_alerts}个未处理告警"}
        elif recent_monitor_count == 0:
            return {"status": "warning", "message": "最近24小时无监控数据"}
        elif enabled_schedules == 0:
            return {"status": "warning", "message": "没有启用的监控调度"}
        else:
            return {"status": "success", "message": "运行正常"}
            
    except Exception as e:
        current_app.logger.error(f"获取监控系统状态失败: {e}")
        return {"status": "error", "message": "状态检查失败"}

def get_monitoring_summary():
    """获取监控系统概览"""
    return {
        "monitor_data_size": get_monitor_data_size(),
        "alert_rule_count": get_alert_rule_count(),
        "last_monitor_time": get_last_monitor_time(),
        "enabled_device_monitor_count": get_enabled_device_monitor_count(),
        "active_alert_count": get_active_alert_count(),
        "device_config_count": get_device_config_count(),
        "status": get_monitoring_status()
    }
    
