# tasks/retention.py
"""
监控时序数据保留/清理任务。

按 CollectionSetting.data_retention_days（默认 30 天）分批删除过期的
MetricData 与 InterfaceMonitorData，避免全表锁与库体无限膨胀。
在 scheduler.py 中作为每日定时任务注册（建议凌晨低峰执行）。
"""
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

DEFAULT_RETENTION_DAYS = 30
BATCH_SIZE = 5000  # 每批删除行数，避免长事务/全表锁


def _get_retention_days():
    """读取采集设置中的保留天数，失败回退默认 30 天。"""
    try:
        from models.config_models import CollectionSetting
        setting = CollectionSetting.query.filter_by(enabled=True).first()
        if setting and setting.data_retention_days:
            return max(1, int(setting.data_retention_days))
    except Exception as e:
        logger.warning(f"读取保留天数失败，使用默认 {DEFAULT_RETENTION_DAYS} 天: {e}")
    return DEFAULT_RETENTION_DAYS


def _delete_expired(model, retention_days, batch_size=BATCH_SIZE):
    """
    分批删除过期记录。每次仅删除 batch_size 行，循环直到无更多过期数据，
    避免单次大事务导致的锁表与回滚段膨胀。返回删除总数。
    """
    from extensions import db
    cutoff = datetime.utcnow() - timedelta(days=retention_days)
    total = 0
    while True:
        try:
            with db.session.begin():
                # 用一层子查询包装，兼容 SQLite / MySQL 对 "DELETE ... IN (子查询)" 的限制
                subq = db.session.query(model.id).filter(
                    model.collected_at < cutoff
                ).limit(batch_size).subquery()
                deleted = db.session.query(model).filter(
                    model.id.in_(subq)
                ).delete(synchronize_session=False)
        except Exception as e:
            logger.error(f"删除 {model.__tablename__} 过期数据出错: {e}")
            try:
                db.session.rollback()
            except Exception:
                pass
            break
        if deleted == 0:
            break
        total += deleted
        logger.info(f"已删除 {model.__tablename__} 过期记录 {total} 条（保留 {retention_days} 天）")
    return total


def cleanup_monitoring_data(app, retention_days=None):
    """
    清理监控时序数据（MetricData + InterfaceMonitorData）。
    可由 scheduler 定时调用，也可手动传入 retention_days 覆盖配置。
    """
    if retention_days is None:
        retention_days = _get_retention_days()
    with app.app_context():
        from models.monitoring import MetricData
        from models.models import InterfaceMonitorData

        logger.info(f"开始清理监控数据，保留 {retention_days} 天")
        n_metric = _delete_expired(MetricData, retention_days)
        n_iface = _delete_expired(InterfaceMonitorData, retention_days)
        logger.info(
            f"监控数据清理完成: MetricData 删除 {n_metric} 条, "
            f"InterfaceMonitorData 删除 {n_iface} 条"
        )
        return {'metric_data': n_metric, 'interface_monitor_data': n_iface}
