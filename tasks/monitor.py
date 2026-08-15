# tasks/monitor.py
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from flask import Flask, current_app
from  extensions import db
#from models.models import DeviceConfig, 
from models.monitoring import MetricData,DeviceConfig, AlertHistory
from models.models import AlertRule
from utils.utils import ping_device, snmp_get, get_device_snmp_data
from datetime import datetime
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

# 并发采集线程数：网络 I/O 密集型，连接仅在「读快照」阶段短暂占用，
# 故并发主要受网络/SNMP 响应制约；设为 30 以留足连接池余量给其他请求。
METRIC_COLLECT_WORKERS = 30

def _collect_metrics_for_config(app, cfg_id):
    """子线程内采集单个 DeviceConfig 的指标，仅返回待写入行，不直接写库（避免跨线程共享 session）。

    性能修复：网络采集（Ping / SNMP）在「无 DB 连接」状态下进行，
    仅开头短暂读取配置/设备快照，避免 METRIC_COLLECT_WORKERS(50) 个并发
    worker 在慢速网络 I/O 期间占满连接池导致 HTTP 请求 TimeoutError。
    """
    rows = []
    # 阶段1：短暂读取配置与设备快照（读取后立即释放连接）
    try:
        with app.app_context():
            cfg = DeviceConfig.query.get(cfg_id)
            if not cfg or not cfg.enabled:
                return rows
            device = cfg.device
            if not device or not device.management_ip:
                return rows
            snap = {
                'ip': device.management_ip,
                'enable_ping': cfg.enable_ping,
                'enable_snmp': cfg.enable_snmp,
                'ping_timeout': cfg.ping_timeout,
            }
    except Exception as e:
        logger.error(f"读取配置 #{cfg_id} 快照失败: {e}")
        return rows

    # 阶段2：网络采集（无 DB 连接，连接池零占用）
    try:
        if snap['enable_ping']:
            success, rtt = ping_device(snap['ip'], timeout=snap['ping_timeout'])
            loss_rate = 0.0 if success else 100.0
            rows.append({
                'device_config_id': cfg_id,
                'metric_name': 'ping_loss_rate',
                'value': float(loss_rate),
                'collected_at': datetime.utcnow(),
            })
            if success:
                rows.append({
                    'device_config_id': cfg_id,
                    'metric_name': 'ping_avg_rtt',
                    'value': float(rtt),
                    'collected_at': datetime.utcnow(),
                })

        if snap['enable_snmp']:
            # device 对象在阶段1已加载（标量属性已缓存），脱离 session 后仍可用于 SNMP 采集
            data = get_device_snmp_data(device)
            for metric, value in data.items():
                if value is None:
                    continue
                try:
                    rows.append({
                        'device_config_id': cfg_id,
                        'metric_name': metric,
                        'value': float(value),
                        'collected_at': datetime.utcnow(),
                    })
                except (ValueError, TypeError):
                    continue
    except Exception as e:
        logger.error(f"采集配置 #{cfg_id} 指标失败: {e}")
    return rows


def collect_device_metrics(app: Flask):
    """并发采集所有启用设备的监控指标，主线程一次性批量写入（去掉逐条 commit，大幅降低事务数）。

    优化：主线程只在「读取配置 ID」与「批量写入」时短暂打开 app_context，
    采集扫描阶段不持有 DB 连接，避免与并发 worker 争用连接池。
    """
    # 阶段1：短暂读取启用的配置 ID
    with app.app_context():
        configs = DeviceConfig.query.filter_by(enabled=True).all()
        cfg_ids = [c.id for c in configs]
    logger.info(f"开始指标采集任务，共 {len(cfg_ids)} 个监控配置（并发 {METRIC_COLLECT_WORKERS}）")

    all_rows = []
    start = time.time()
    with ThreadPoolExecutor(max_workers=METRIC_COLLECT_WORKERS) as executor:
        futures = {
            executor.submit(_collect_metrics_for_config, app, cid): cid
            for cid in cfg_ids
        }
        for future in as_completed(futures):
            try:
                all_rows.extend(future.result() or [])
            except Exception as e:
                logger.error(f"指标采集子任务异常: {e}")

    # 阶段2：批量写入（短暂上下文）
    if all_rows:
        with app.app_context():
            try:
                db.session.bulk_insert_mappings(MetricData, all_rows)
                db.session.commit()
                logger.info(f"批量写入 {len(all_rows)} 条指标完成")
            except Exception as e:
                db.session.rollback()
                logger.error(f"批量写入指标失败: {e}")

    elapsed = time.time() - start
    logger.info(f"指标采集任务完成: 共 {len(all_rows)} 条，耗时 {elapsed:.2f}s")


from sqlalchemy import and_
from datetime import timedelta

def evaluate_alerts(app: Flask):
    with app.app_context():
        rules = AlertRule.query.filter_by(enabled=True).all()
        for rule in rules:
            cutoff = datetime.utcnow() - timedelta(seconds=rule.duration)
            metrics = MetricData.query.filter(
                and_(
                    MetricData.device_config_id == rule.device_config_id,
                    MetricData.metric_name == rule.metric_name,
                    MetricData.collected_at >= cutoff
                )
            ).order_by(MetricData.collected_at.desc()).all()

            if not metrics:
                continue

            # 检查是否所有指标值都满足阈值条件
            violated = all(_compare(m.value, rule.operator, rule.threshold) for m in metrics if m.value is not None)
            if violated:
                # 防止重复告警（默认 1 小时内不重复）
                if rule.last_alert_at and (datetime.utcnow() - rule.last_alert_at).total_seconds() < 3600:
                    continue
                _trigger_alert(rule, metrics[0].value)
            else:
                # 检查是否有未恢复的告警，标记为 resolved
                unresolved = AlertHistory.query.filter_by(rule_id=rule.id, status='firing').first()
                if unresolved:
                    unresolved.resolved_at = datetime.utcnow()
                    unresolved.status = 'resolved'
                    db.session.commit()

def _compare(value, operator, threshold):
    if value is None:
        return False
    if operator == '>':
        return value > threshold
    elif operator == '<':
        return value < threshold
    elif operator == '>=':
        return value >= threshold
    elif operator == '<=':
        return value <= threshold
    elif operator == '==':
        return value == threshold
    return False

def _trigger_alert(rule, current_value):
    device = rule.device_config.device
    message = f"设备 {device.name}({device.management_ip}) 的 {rule.metric_name} 当前值 {current_value} 触发告警 (阈值 {rule.operator}{rule.threshold})"
    history = AlertHistory(
        rule_id=rule.id,
        device_config_id=rule.device_config_id,
        metric_name=rule.metric_name,
        current_value=current_value,
        threshold=rule.threshold,
        operator=rule.operator,
        message=message,
        triggered_at=datetime.utcnow()
    )
    db.session.add(history)
    rule.last_alert_at = datetime.utcnow()
    db.session.commit()

    # 发送通知（根据 rule.notify_channels 和 rule.notify_targets）
    _send_notification(rule, message)

def _send_notification(rule, message):
    """根据告警规则的通知配置发送通知"""
    from services.notification_service import send_notification
    from models.models import NotificationConfig

    # 查询所有启用的通知配置
    configs = NotificationConfig.query.filter_by(enabled=True).all()
    if not configs:
        return

    title = f'【告警】{rule.name} - {rule.severity.upper()}'

    for nc in configs:
        try:
            send_notification(nc, title=title, content=message)
        except Exception as e:
            print(f"发送通知失败 [{nc.name}]: {e}")

