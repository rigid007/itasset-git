# tasks/netflow_collect.py
"""NetFlow lifecycle + retention tasks, wired into scheduler.py.

  * start_netflow_collectors : one-shot job on app startup (start UDP listeners)
  * netflow_cleanup          : daily cron job (delete records older than retention)
  * seed_netflow_dictionaries: seed reference tables on first run
"""
import logging
from datetime import datetime, timedelta
from sqlalchemy import func

from extensions import get_bg_session
from services.netflow_service import (
    start_all_collectors, stop_all_collectors, seed_dictionaries,
    get_app_map, app_name_for, resolve_device_for_ip,
)
from models.netflow_models import NetFlowRecord, NetFlowAgg, NetFlowAlert

logger = logging.getLogger(__name__)


def _netflow_enabled():
    try:
        from flask import current_app
        return bool(current_app.config.get('NETFLOW_ENABLED', True))
    except RuntimeError:
        import os
        return os.environ.get('NETFLOW_ENABLED', '1') == '1'


def seed_netflow_dictionaries(app=None):
    if not _netflow_enabled():
        logger.info('NetFlow disabled; skip dictionary seed')
        return
    session = get_bg_session()
    try:
        seed_dictionaries(session)
        logger.info('NetFlow reference dictionaries seeded')
    except Exception as e:
        session.rollback()
        logger.error('NetFlow dictionary seed failed: %s', e)
    finally:
        session.close()


def start_netflow_collectors(app=None):
    """Start collectors for enabled probes. Idempotent; safe to run repeatedly."""
    if not _netflow_enabled():
        logger.info('NetFlow disabled; skip collector startup and stop running collectors')
        stop_netflow_collectors()
        return
    try:
        if app is not None:
            with app.app_context():
                _init_impl()
        else:
            _init_impl()
    except Exception as e:
        logger.exception('NetFlow collector startup failed: %s', e)


def _init_impl():
    session = get_bg_session()
    try:
        seed_dictionaries(session)
    finally:
        session.close()
    start_all_collectors()


def stop_netflow_collectors(app=None):
    stop_all_collectors()


def netflow_cleanup(app=None):
    """Delete flow records older than the configured retention window."""
    if not _netflow_enabled():
        logger.info('NetFlow disabled; skip cleanup')
        return
    from flask import current_app
    try:
        days = int(current_app.config.get('NETFLOW_RETENTION_DAYS', 30))
    except RuntimeError:
        days = 30
    session = get_bg_session()
    try:
        cutoff = datetime.utcnow() - timedelta(days=days)
        deleted = 0
        while True:
            ids = session.query(NetFlowRecord.id).filter(
                NetFlowRecord.received_at < cutoff
            ).limit(5000).all()
            if not ids:
                break
            id_list = [i[0] for i in ids]
            deleted += session.query(NetFlowRecord).filter(
                NetFlowRecord.id.in_(id_list)
            ).delete(synchronize_session=False)
            session.commit()
        logger.info('NetFlow cleanup: removed %d records older than %d days',
                    deleted, days)
    except Exception as e:
        session.rollback()
        logger.error('NetFlow cleanup failed: %s', e)
    finally:
        session.close()


def netflow_aggregate(app=None):
    """Roll raw netflow_records into 5-minute NetFlowAgg buckets."""
    if not _netflow_enabled():
        return
    if app is not None:
        with app.app_context():
            _aggregate_impl()
    else:
        _aggregate_impl()


def _aggregate_impl():
    session = get_bg_session()
    try:
        now = datetime.utcnow()
        bucket = now.replace(minute=(now.minute // 5) * 5, second=0, microsecond=0)
        start = bucket - timedelta(minutes=5)
        app_map = get_app_map(session)
        rows = (session.query(
                    NetFlowRecord.probe_id,
                    NetFlowRecord.src_ip,
                    NetFlowRecord.dst_ip,
                    NetFlowRecord.src_port,
                    NetFlowRecord.dst_port,
                    NetFlowRecord.protocol,
                    func.sum(NetFlowRecord.octets).label('octets'),
                    func.sum(NetFlowRecord.packets).label('packets'),
                    func.count(NetFlowRecord.id).label('flows'),
                ).filter(NetFlowRecord.received_at >= start,
                         NetFlowRecord.received_at < bucket)
                .group_by(NetFlowRecord.probe_id,
                          NetFlowRecord.src_ip,
                          NetFlowRecord.dst_ip,
                          NetFlowRecord.src_port,
                          NetFlowRecord.dst_port,
                          NetFlowRecord.protocol)
                .all())
        # Replace the whole bucket each run (simple, idempotent).
        session.query(NetFlowAgg).filter_by(period='5m', bucket=bucket).delete(synchronize_session=False)
        if not rows:
            session.commit()
            return
        seen = {}
        def _dev_id(ip):
            if not ip or ip in seen:
                return seen.get(ip)
            dev = resolve_device_for_ip(session, ip)
            seen[ip] = dev.id if dev else None
            return seen[ip]
        objs = []
        for probe_id, src_ip, dst_ip, sport, dport, proto, octets, packets, flows in rows:
            objs.append(NetFlowAgg(
                probe_id=probe_id,
                period='5m',
                bucket=bucket,
                src_ip=src_ip,
                dst_ip=dst_ip,
                src_port=sport,
                dst_port=dport,
                protocol=proto,
                app_name=app_name_for(dport, proto, app_map),
                src_device_id=_dev_id(src_ip),
                dst_device_id=_dev_id(dst_ip),
                octets=octets or 0,
                packets=packets or 0,
                flows=flows or 0,
                created_at=now,
                updated_at=now,
            ))
        session.add_all(objs)
        session.commit()
        logger.info('NetFlow agg: inserted %d rows for bucket %s', len(objs), bucket)
    except Exception as e:
        session.rollback()
        logger.error('NetFlow aggregation failed: %s', e)
    finally:
        session.close()


def netflow_alert_check(app=None):
    """Create NetFlow anomaly alerts from recent aggregated flows."""
    if not _netflow_enabled():
        return
    if app is not None:
        with app.app_context():
            _alert_check_impl()
    else:
        _alert_check_impl()


def _alert_check_impl():
    from flask import current_app
    from models.models import AlertEvent
    try:
        threshold = float(current_app.config.get('NETFLOW_ALERT_THRESHOLD_MBPS', 0))
        severity = current_app.config.get('NETFLOW_ALERT_SEVERITY', 'warning')
    except RuntimeError:
        threshold = 0.0
        severity = 'warning'
    if threshold <= 0:
        return
    session = get_bg_session()
    try:
        now = datetime.utcnow()
        since = now - timedelta(minutes=10)
        rows = (session.query(NetFlowAgg)
                .filter(NetFlowAgg.period == '5m',
                        NetFlowAgg.bucket >= since)
                .order_by(NetFlowAgg.octets.desc())
                .limit(100).all())
        for agg in rows:
            mbps = (agg.octets or 0) * 8 / (300.0 * 1_000_000)
            if mbps < threshold:
                continue
            device = resolve_device_for_ip(session, agg.src_ip) or resolve_device_for_ip(session, agg.dst_ip)
            device_id = device.id if device else None
            title = 'NetFlow 流量异常: %s' % (agg.app_name or '未知应用')
            message = 'src=%s dst=%s app=%s 5min=%.2f Mbps 阈值=%.2f Mbps' % (
                agg.src_ip or '-', agg.dst_ip or '-', agg.app_name or '-', mbps, threshold)
            existing = (session.query(NetFlowAlert)
                        .filter(NetFlowAlert.metric_type == 'netflow_bandwidth',
                                NetFlowAlert.status == 'active',
                                NetFlowAlert.src_ip == agg.src_ip,
                                NetFlowAlert.dst_ip == agg.dst_ip,
                                NetFlowAlert.app_name == agg.app_name)
                        .first())
            if existing:
                existing.last_occurred = now
                existing.occurrence_count = (existing.occurrence_count or 1) + 1
                existing.metric_value = mbps
                existing.message = message
                continue
            session.add(NetFlowAlert(
                probe_id=agg.probe_id,
                device_id=device_id,
                src_ip=agg.src_ip,
                dst_ip=agg.dst_ip,
                app_name=agg.app_name,
                metric_type='netflow_bandwidth',
                metric_value=mbps,
                threshold=threshold,
                severity=severity,
                title=title,
                message=message,
                first_occurred=now,
                last_occurred=now,
                occurrence_count=1,
            ))
            if device_id:
                ev = (session.query(AlertEvent)
                      .filter(AlertEvent.device_id == device_id,
                              AlertEvent.metric_type == 'netflow_bandwidth',
                              AlertEvent.title == title,
                              AlertEvent.status == 'active')
                      .first())
                if ev:
                    ev.last_occurred = now
                    ev.occurrence_count = (ev.occurrence_count or 1) + 1
                    ev.metric_value = mbps
                    ev.message = message
                else:
                    session.add(AlertEvent(
                        device_id=device_id,
                        rule_id=None,
                        title=title,
                        message=message,
                        severity=severity,
                        metric_type='netflow_bandwidth',
                        metric_value=mbps,
                        status='active',
                        first_occurred=now,
                        last_occurred=now,
                        occurrence_count=1,
                        notified=False,
                    ))
        session.commit()
        logger.info('NetFlow alert check done (threshold %.1f Mbps)', threshold)
    except Exception as e:
        session.rollback()
        logger.error('NetFlow alert check failed: %s', e)
    finally:
        session.close()
