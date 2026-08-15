# tasks.py
"""
网络设备监控任务模块
包含设备状态检测、接口同步、连接监控等功能
"""
import json
import logging
import time
import subprocess
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, TimeoutError, as_completed
from typing import Tuple, Dict, Any, Optional, List

from pysnmp.entity.rfc3413.oneliner import cmdgen
import redis
from flask import current_app
from sqlalchemy.orm.exc import StaleDataError

from extensions import db
from models.models import ConnectionPath, Device, Interface, DeviceMonitorLog
from models.config_models import SystemLog
from models.monitoring import MetricData
from utils.utils import snmp_walk, snmp_get, walk_interfaces, snmp_get_with_timeout
from blueprints.topology import is_valid_target_ip

# ==================== 日志配置 ====================
logger = logging.getLogger(__name__)

# ==================== SNMP 超时配置 ====================
SNMP_TIMEOUT = 5
DEVICE_TIMEOUT = 30

# ==================== 基础工具函数 ====================

def ping_device(ip, timeout=3, retries=2):
    """
    使用原生 subprocess 调用系统 ping 命令，正确解析输出
    
    在 Windows 上，ping 命令的输出有以下几种情况：
    1. 成功: "来自 192.168.1.6 的回复: 字节=32 时间=1ms TTL=64"
    2. 目标主机不可达: "来自 192.168.1.2 的回复: 无法访问目标主机。"
    3. 请求超时: "请求超时。"
    4. 找不到主机: "Ping 请求找不到主机"
    """
    import platform
    
    system = platform.system().lower()
    logger.debug(f"Ping {ip}, 系统: {system}, 超时: {timeout}s, 重试: {retries}次")
    
    for attempt in range(retries):
        try:
            if system == 'windows':
                cmd = ['ping', '-n', '1', '-w', str(int(timeout * 1000)), ip]
            else:
                cmd = ['ping', '-c', '1', '-W', str(timeout), ip]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=timeout + 2,
                text=True,
                encoding='gbk' if system == 'windows' else 'utf-8'
            )
            
            output = result.stdout + result.stderr
            logger.debug(f"Ping 输出: {output.strip()}")
            
            # ========== 成功标志 ==========
            if 'TTL=' in output or 'ttl=' in output.lower():
                logger.debug(f"Ping {ip} 成功 (检测到 TTL)")
                return True
            
            if '来自' in output and '回复' in output and '无法访问目标主机' not in output:
                logger.debug(f"Ping {ip} 成功 (检测到 '来自' 和 '回复')")
                return True
            
            if 'Reply from' in output:
                logger.debug(f"Ping {ip} 成功 (检测到 'Reply from')")
                return True
            
            if system != 'windows' and ('1 received' in output or '1 packets received' in output):
                logger.debug(f"Ping {ip} 成功 (检测到 received)")
                return True
            
            if system != 'windows' and result.returncode == 0:
                logger.debug(f"Ping {ip} 成功 (返回码 0)")
                return True
            
            # ========== 失败标志 ==========
            failure_keywords = [
                '无法访问目标主机', '请求超时', '超时', '找不到主机',
                'Ping request could not find host', 'Destination host unreachable',
                'Request timed out', 'timed out'
            ]
            
            for keyword in failure_keywords:
                if keyword.lower() in output.lower():
                    logger.debug(f"Ping {ip} 失败 (检测到: {keyword})")
                    return False
            
            if not output or output.strip() == '':
                logger.debug(f"Ping {ip} 失败 (输出为空)")
                return False
            
            if ip in output:
                logger.debug(f"Ping {ip} 失败 (包含IP但无成功标志)")
                return False
            
            logger.debug(f"Ping {ip} 结果不明确，重试...")
            
        except subprocess.TimeoutExpired:
            logger.debug(f"Ping {ip} 进程超时")
        except Exception as e:
            logger.debug(f"Ping {ip} 异常: {e}")
        
        if attempt < retries - 1:
            time.sleep(0.5)
    
    logger.debug(f"Ping {ip} 最终结果: 失败")
    return False


def record_system_log(level, module, source, message, details=None, user_id=None, ip_address=None):
    """插入一条系统日志"""
    log = SystemLog(
        timestamp=datetime.utcnow(),
        level=level,
        module=module,
        source=source,
        message=message,
        details=json.dumps(details) if details else None,
        user_id=user_id,
        ip_address=ip_address,
        request_id=None
    )
    db.session.add(log)


# ==================== 接口同步函数 ====================

def sync_device_interfaces(device_id, ip, community):
    """
    同步设备的接口 ifindex
    """
    ifindex_to_name = walk_interfaces(ip, community)
    updated = 0
    for ifindex, ifname in ifindex_to_name.items():
        interface = Interface.query.filter_by(device_id=device_id, name=ifname).first()
        if not interface:
            interface = Interface(device_id=device_id, name=ifname)
            db.session.add(interface)
        interface.ifindex = ifindex
        updated += 1
    db.session.commit()
    return updated


def get_ifindex_via_snmp(device, port_name):
    """
    通过 SNMP 获取设备指定端口的 ifindex。
    返回 ifindex 字符串或 None。
    """
    ip = device.management_ip or device.ip_address
    if not ip:
        logger.debug(f"设备 {device.id} 无管理 IP，无法获取 ifindex")
        return None
    
    community = getattr(device, 'snmp_community', 'public')
    version = getattr(device, 'snmp_version', '2c')
    
    try:
        desc_entries = snmp_walk(ip, '1.3.6.1.2.1.2.2.1.2', community, version=version, timeout=3)
        index_entries = snmp_walk(ip, '1.3.6.1.2.1.2.2.1.1', community, version=version, timeout=3)

        desc_to_index = {}
        for oid_desc, desc in desc_entries:
            idx = oid_desc.split('.')[-1]
            desc_clean = str(desc).strip('"').strip()
            desc_to_index[desc_clean] = idx

        for if_desc, if_idx in desc_to_index.items():
            if port_name in if_desc or if_desc == port_name:
                logger.info(f"通过 SNMP 为接口 {port_name} 匹配到 ifindex={if_idx}")
                return if_idx
        
        return desc_to_index.get(port_name)
    except Exception as e:
        logger.warning(f"SNMP 获取 ifindex 失败: {e}")
        return None



# ==================== 连接状态更新 ====================


def update_connection_status(interface):
    """
    更新与该接口相关的所有连接的状态
    当接口状态发生变化时调用
    """
    from tasks.link_monitor import LinkMonitor
    monitor = LinkMonitor()

    connections = ConnectionPath.query.filter(
        (ConnectionPath.source_interface_id == interface.id) |
        (ConnectionPath.target_interface_id == interface.id)
    ).all()

    if not connections:
        connections = ConnectionPath.query.filter(
            (ConnectionPath.source_device_id == interface.device_id) &
            (ConnectionPath.source_port == interface.name)
        ).all()
        connections += ConnectionPath.query.filter(
            (ConnectionPath.target_device_id == interface.device_id) &
            (ConnectionPath.target_port == interface.name)
        ).all()

    if not connections:
        logger.debug(f"接口 {interface.name} 没有关联的连接")
        return

    updated = 0
    for conn in connections:
        try:
            result = monitor.check_single_link(conn.id, db.session)
            new_status = result['status']
            if conn.link_status != new_status:
                old_status = conn.link_status
                conn.link_status = new_status
                conn.updated_at = datetime.utcnow()
                # 链路状态改变：告警信息写入系统日志
                src_name = getattr(conn.source_device, 'name', None) or str(conn.source_device_id)
                dst_name = getattr(conn.target_device, 'name', None) or str(conn.target_device_id)
                reason = result.get('reason', '')
                record_system_log(
                    level='warning' if new_status == 'down' else 'info',
                    module='link_monitor',
                    source=f'link:{conn.id}',
                    message=(
                        f'链路 {src_name}:{conn.source_port} -> '
                        f'{dst_name}:{conn.target_port} '
                        f'状态变化: {old_status} -> {new_status}'
                        + (f'，原因: {reason}' if reason else '')
                    ),
                    details={
                        'alert_title': (
                            f'链路断开: {conn.source_port} -> {conn.target_port}'
                            if new_status == 'down'
                            else f'链路恢复: {conn.source_port} -> {conn.target_port}'
                        ),
                        'severity': 'critical' if new_status == 'down' else 'info',
                        'monitor_type': 'link_monitor',
                        'reason': reason,
                    }
                )
                logger.info(f"连接 {conn.id} 状态变更: {old_status} → {new_status}")
                updated += 1
        except Exception as e:
            logger.error(f"更新连接 {conn.id} 状态失败: {e}")

    db.session.commit()
    if updated:
        logger.info(f"接口 {interface.name} 触发更新了 {updated} 条连接")


# ==================== 设备状态检测 ====================

def check_device_status(app, device_id, snap):
    """
    检测单个设备的状态（在线/离线）及其接口状态。

    性能修复：网络检测（SNMP / Ping）在「不持有 DB 连接」的情况下进行，
    仅在实际需要写库时短暂打开 app_context。避免在慢速网络 I/O 期间占用
    连接池，导致 HTTP 请求因 QueuePool 耗尽而超时（TimeoutError）。
    """
    ip = snap.get('ip')
    community = snap.get('community', 'public')
    version = snap.get('version', '2c')
    name = snap.get('name') or f'#{device_id}'

    try:
        # ============ 阶段1：网络检测（无 DB 连接） ============
        no_ip = not ip
        if no_ip:
            snmp_ok = False
            ping_ok = False
            is_online = False
            new_status = 'offline'
        else:
            snmp_ok = False
            try:
                sysname = snmp_get_with_timeout(
                    ip, community, version, '1.3.6.1.2.1.1.5.0', timeout=2)
                snmp_ok = sysname is not None
            except Exception as e:
                logger.debug(f"SNMP 查询异常: {e}")
            ping_ok = ping_device(ip, timeout=2, retries=2)
            is_online = snmp_ok or ping_ok
            new_status = 'online' if is_online else 'offline'

        # ============ 阶段2：短暂 DB 持久化 ============
        with app.app_context():
            dev = Device.query.get(device_id)
            if not dev:
                return
            dev.last_checked = datetime.utcnow()

            if no_ip:
                if dev.status != 'offline':
                    old_status = dev.status
                    dev.status = 'offline'
                    record_system_log(
                        level='warning',
                        module='device_monitor',
                        source=f'device:{dev.id}',
                        message=f'设备 {dev.name} (ID:{dev.id}) 无管理IP，标记为离线',
                        details={
                            'alert_title': f'设备离线: {dev.name}',
                            'severity': 'critical',
                            'monitor_type': 'device_ping',
                            'ip': 'N/A',
                        }
                    )
                    try:
                        db.session.add(DeviceMonitorLog(
                            device_id=dev.id,
                            device_ip='N/A',
                            old_status=old_status,
                            new_status='offline',
                            ping_time=0,
                            is_online=False,
                            monitor_type='device_ping',
                            error_message='无管理IP'
                        ))
                        db.session.commit()
                    except Exception:
                        db.session.rollback()
                else:
                    db.session.commit()
                return

            status_changed = (dev.status != new_status)
            old_status = dev.status

            if status_changed:
                dev.status = new_status
                record_system_log(
                    level='info' if new_status == 'online' else 'warning',
                    module='device_monitor',
                    source=f'device:{dev.id}',
                    message=f'设备 {dev.name} 状态变化: {old_status} -> {new_status}',
                    details={
                        'alert_title': (
                            f'设备离线: {dev.name}' if new_status == 'offline'
                            else f'设备恢复: {dev.name}'
                        ),
                        'severity': 'critical' if new_status == 'offline' else 'info',
                        'monitor_type': 'device_ping',
                        'ip': ip,
                    }
                )
                logger.info(f"设备 {dev.name} 状态变化: {old_status} -> {new_status}")

            if status_changed:
                try:
                    db.session.add(DeviceMonitorLog(
                        device_id=dev.id,
                        device_ip=ip,
                        old_status=old_status,
                        new_status=new_status,
                        ping_time=dev.ping_time or 0,
                        is_online=is_online,
                        monitor_type='device_ping',
                        error_message=None if is_online else (
                            'SNMP+Ping均失败' if not snmp_ok and not ping_ok
                            else 'SNMP失败,Ping成功但设备异常' if not snmp_ok
                            else 'Ping失败'
                        )
                    ))
                    # 设备离线/恢复：接入事件关联引擎(去重/归一化/升级/自动建单)
                    # 仅对真实状态跃迁(非每轮轮询)触发，避免告警风暴。
                    if new_status == 'offline':
                        try:
                            from models.models import AlertEvent
                            alert = AlertEvent(
                                device_id=dev.id,
                                rule_id=None,
                                title=f'设备离线: {dev.name}',
                                message=f'设备 {dev.name} ({ip}) 状态变化: {old_status} -> offline',
                                severity='critical',
                                status='active',
                                first_occurred=datetime.utcnow(),
                                last_occurred=datetime.utcnow(),
                                occurrence_count=1,
                                notified=False,
                            )
                            db.session.add(alert)
                            db.session.flush()
                            try:
                                from utils.event_correlation import process_alert_correlation
                                process_alert_correlation(db.session, alert)
                            except Exception as ce:
                                logger.error(f"事件关联规则应用失败(忽略): {ce}")
                        except Exception as ae:
                            logger.error(f"创建设备离线告警失败(忽略): {ae}")
                    elif new_status == 'online':
                        # 恢复在线：关闭该设备仍活跃的离线告警(含被关联抑制的)
                        try:
                            from models.models import AlertEvent
                            dev_alerts = AlertEvent.query.filter_by(device_id=dev.id).filter(
                                AlertEvent.status.in_(['active', 'suppressed']),
                                AlertEvent.title.like('设备离线%')
                            ).all()
                            for a in dev_alerts:
                                a.status = 'resolved'
                                a.resolved_at = datetime.utcnow()
                                a.resolved_by = 'system'
                            if dev_alerts:
                                db.session.flush()
                        except Exception as re:
                            logger.error(f"关闭设备离线告警失败(忽略): {re}")
                    db.session.commit()
                except Exception as log_err:
                    logger.error(f"写入 DeviceMonitorLog 失败: {log_err}")
                    db.session.rollback()

            # 设备离线处理
            if not is_online:
                interfaces = Interface.query.filter_by(device_id=dev.id).all()
                for iface in interfaces:
                    if iface.oper_status != 'down':
                        iface.oper_status = 'down'
                        iface.updated_at = datetime.utcnow()
                        update_connection_status(iface)
                db.session.commit()
                return

            # 设备在线，同步接口信息
            if snmp_ok:
                logger.info(f"设备 {dev.name} SNMP 可用，开始同步接口信息")
                try:
                    sync_device_interfaces(dev.id, ip, community)
                except Exception as e:
                    logger.error(f"同步设备 {dev.name} 接口 ifindex 失败: {e}")
                try:
                    if_oper_entries = snmp_walk(
                        ip, '1.3.6.1.2.1.2.2.1.8', community, version=version, timeout=3)
                    if if_oper_entries:
                        interface_count = 0
                        for oid, val in if_oper_entries:
                            idx = oid.split('.')[-1]
                            oper = 'up' if val == '1' else 'down' if val == '2' else 'unknown'
                            interface = Interface.query.filter_by(
                                device_id=dev.id, ifindex=idx).first()
                            if not interface:
                                continue
                            if interface.oper_status != oper:
                                interface.oper_status = oper
                                interface.updated_at = datetime.utcnow()
                                update_connection_status(interface)
                                interface_count += 1
                        db.session.commit()
                        logger.info(f"设备 {dev.name} 更新了 {interface_count} 个接口状态")
                except Exception as e:
                    logger.error(f"获取接口状态失败: {e}")
                    db.session.rollback()

            db.session.commit()
            logger.info(f"设备 {dev.name} 检测完成，状态: {dev.status}")

    except Exception as e:
        logger.error(f"检测设备 {name} 时发生异常: {e}")
        try:
            db.session.rollback()
        except Exception:
            pass


def check_all_devices_status(app):
    """定时任务：检测所有设备状态（并发优化版）

    优化点：
    - 并发度随设备数量提升（上限 45，控制在 DB 连接池容量内），
      网络 I/O 密集型，线程等待为主，可安全提高并发
    - 使用 as_completed 避免慢设备阻塞快设备
    - 跳过已下架设备（is_decommissioned）
    - 单设备超时 15s（SNMP 2s + Ping 2s×2 重试 + 余量）
    - 全局时间预算自适应（按 设备数/并发数×单设备最坏耗时 估算，至少 240s），
      确保 5 分钟间隔内总能跑完一轮完整扫描
    - 主线程只在取快照时打开 app_context，扫描期间不持有 DB 连接，
      避免与 worker 争用连接池
    - 全局预算耗尽时优雅降级：已完成的设备照常处理，未完成设备下轮重试，
      且不阻塞等待未完成线程（其网络 I/O 期间不持 DB 连接），避免拖垮调度器
    """
    # 阶段1：短暂读取设备快照（IP / 团体字 / 版本），随后立即释放连接
    with app.app_context():
        devices = Device.query.filter_by(is_decommissioned=False).all()
        snapshots = [{
            'id': d.id,
            'ip': d.management_ip or d.ip_address,
            'community': getattr(d, 'snmp_community', 'public'),
            'version': getattr(d, 'snmp_version', '2c'),
            'name': d.name,
        } for d in devices]
        total = len(snapshots)
    # 注意：上面 with 块已退出，主线程连接已归还，扫描阶段不再占用

    logger.info(f"开始状态检测任务，共 {total} 台设备（已排除下架设备）")

    if not total:
        return

    start_time = time.time()
    success_count = 0
    fail_count = 0
    timeout_count = 0

    # 并发度：网络 I/O 密集、线程等待为主。上限 45 控制在 DB 连接池容量
    # (pool_size=20 + max_overflow=30 = 50) 之内，并为其他任务/HTTP 留余量；
    # 随设备数量提升并发，小规模则用较少线程省资源。
    worker_count = min(45, max(10, total // 10)) if total > 50 else 10

    # 全局时间预算：依据 设备数 / 并发数 × 单设备最坏耗时(~9s) 估算并留 1.5 倍余量；
    # 至少 240s，确保 5 分钟间隔内总能跑完一轮完整扫描，避免 as_completed 提前抛 TimeoutError。
    per_device_worst = 9.0
    est = (total / worker_count) * per_device_worst
    global_timeout = max(240, int(est * 1.5))

    executor = ThreadPoolExecutor(max_workers=worker_count)
    futures = {
        executor.submit(check_device_status, app, s['id'], s): s['id']
        for s in snapshots
    }
    processed = set()
    try:
        for future in as_completed(futures, timeout=global_timeout):
            device_id = futures[future]
            processed.add(device_id)
            try:
                future.result(timeout=15)
                success_count += 1
            except TimeoutError:
                timeout_count += 1
                logger.warning(f"设备 #{device_id} 检测超时(15s)")
            except Exception as e:
                fail_count += 1
                logger.error(f"设备 #{device_id} 检测失败: {e}")
    except TimeoutError:
        # 全局预算耗尽：收集其余已完成结果，未完成设备下轮重试
        logger.warning(
            f"状态检测全局预算 {global_timeout}s 耗尽，部分设备未完成，"
            f"将在下个周期重试"
        )
        for future, device_id in futures.items():
            if future.done() and device_id not in processed:
                try:
                    future.result(timeout=0)
                except Exception:
                    pass
                processed.add(device_id)
        logger.warning(f"未完成设备数: {total - len(processed)}（下个周期重试）")
    finally:
        # 不阻塞等待未完成线程（避免拖垮调度器）；这些线程网络 I/O 期间不持 DB 连接，
        # 跑完后自行退出，其状态变更仍会落库，只是略晚。
        executor.shutdown(wait=False)

    elapsed = time.time() - start_time
    logger.info(
        f"状态检测任务完成: 成功 {success_count}, 失败 {fail_count}, "
        f"超时 {timeout_count}, 总计 {total}, 耗时 {elapsed:.1f}s, "
        f"并发 {worker_count}"
    )


# ==================== 接口数据采集任务 ====================

# 接口采集并发数与单轮时间预算（超过预算停止提交新设备，避免无限堆积）
POLL_WORKERS = 40
POLL_TIME_BUDGET = 240  # 秒；在 5min 间隔内留出余量


def _collect_device_interfaces(app, device_id, redis_params):
    """
    子线程内采集单台设备的接口流量数据，返回记录列表并自行推送到 Redis。
    每个线程使用独立的 Redis 连接（redis-py 连接对象非线程安全），避免共享连接。
    """
    records = []
    try:
        with app.app_context():
            device = Device.query.get(device_id)
            if not device:
                return records
            ip = device.management_ip or device.ip_address
            community = getattr(device, 'snmp_community', 'public')
            version = getattr(device, 'snmp_version', '2c')
            if not ip:
                return records

            interfaces = Interface.query.filter_by(device_id=device.id).all()
            valid_ifaces = [i for i in interfaces if i.ifindex]
            for interface in valid_ifaces:
                oid_in = f'1.3.6.1.2.1.2.2.1.10.{interface.ifindex}'
                oid_out = f'1.3.6.1.2.1.2.2.1.16.{interface.ifindex}'
                oid_admin = f'1.3.6.1.2.1.2.2.1.7.{interface.ifindex}'
                oid_oper = f'1.3.6.1.2.1.2.2.1.8.{interface.ifindex}'
                oid_speed = f'1.3.6.1.2.1.2.2.1.5.{interface.ifindex}'

                try:
                    bytes_in = snmp_get_with_timeout(ip, community, version, oid_in, timeout=3)
                    bytes_out = snmp_get_with_timeout(ip, community, version, oid_out, timeout=3)
                    admin_val = snmp_get_with_timeout(ip, community, version, oid_admin, timeout=3)
                    oper_val = snmp_get_with_timeout(ip, community, version, oid_oper, timeout=3)
                    speed_val = snmp_get_with_timeout(ip, community, version, oid_speed, timeout=3)
                except Exception as e:
                    logger.debug(f"接口 {interface.name} SNMP 请求异常: {e}，跳过")
                    continue

                admin_status = 'up' if str(admin_val) == '1' else 'down' if str(admin_val) == '2' else 'unknown'
                oper_status = 'up' if str(oper_val) == '1' else 'down' if str(oper_val) == '2' else 'unknown'

                try:
                    bytes_in_val = int(bytes_in) if bytes_in is not None else 0
                    bytes_out_val = int(bytes_out) if bytes_out is not None else 0
                    speed_val_int = int(speed_val) if speed_val is not None else 0
                except (ValueError, TypeError):
                    logger.debug(f"接口 {interface.name} 数值转换失败，跳过")
                    continue

                records.append({
                    'interface_id': interface.id,
                    'device_id': device.id,
                    'bytes_in': bytes_in_val,
                    'bytes_out': bytes_out_val,
                    'packets_in': 0,
                    'packets_out': 0,
                    'errors_in': 0,
                    'errors_out': 0,
                    'drops_in': 0,
                    'drops_out': 0,
                    'speed_in': None,
                    'speed_out': None,
                    'bandwidth_usage': None,
                    'admin_status': admin_status,
                    'oper_status': oper_status,
                    'speed': speed_val_int,
                    'collected_at': datetime.now(timezone.utc).isoformat(),
                    'created_at': datetime.now(timezone.utc).isoformat()
                })
    except Exception as e:
        logger.error(f"采集设备 #{device_id} 接口时异常: {e}")
        return records

    # 本线程独立连接，批量推送到 Redis
    if records and redis_params:
        try:
            r = redis.Redis(
                host=redis_params['host'],
                port=redis_params['port'],
                db=redis_params['db'],
                password=redis_params['password'],
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
            )
            pipe = r.pipeline()
            for rec in records:
                pipe.rpush(redis_params['queue_key'], json.dumps(rec))
            pipe.execute()
            r.close()
        except redis.exceptions.RedisError as e:
            logger.error(f"设备 #{device_id} 推送失败: {e}")
    return records


def poll_all_devices_interfaces(app):
    """
    定时采集任务（生产者，并发版）：
    并发采集所有在线设备的接口流量数据，并推送到 Redis 队列。
    单轮设有时间预算，超过预算即停止提交新设备，避免任务无限堆积。
    """
    if app is None:
        from flask import current_app
        app = current_app._get_current_object()
    logger.info("=========== 开始执行接口数据采集任务（生产者，并发）===============")

    with app.app_context():
        redis_host = app.config.get('REDIS_HOST', 'localhost')
        redis_port = app.config.get('REDIS_PORT', 6379)
        redis_db = app.config.get('REDIS_DB', 0)
        redis_password = app.config.get('REDIS_PASSWORD', None)
        redis_queue_key = app.config.get('REDIS_QUEUE_KEY', 'interface_monitor:queue')

        # 主线程先验证 Redis 连通性
        try:
            test_r = redis.Redis(
                host=redis_host, port=redis_port, db=redis_db,
                password=redis_password, decode_responses=True,
                socket_connect_timeout=5, socket_timeout=5,
            )
            test_r.ping()
            test_r.close()
            logger.info(f"Redis 连接成功：{redis_host}:{redis_port}/{redis_db}")
        except Exception as e:
            logger.error(f"Redis 连接失败，任务终止：{e}")
            return

        redis_params = {
            'host': redis_host, 'port': redis_port, 'db': redis_db,
            'password': redis_password, 'queue_key': redis_queue_key,
        }

        devices = Device.query.filter(Device.status.in_(['online', 'active'])).all()
        device_ids = [d.id for d in devices]
        # 主线程读取完毕，立即归还连接，避免扫描期间长期占用连接池
        db.session.remove()
        logger.info(f"找到 {len(device_ids)} 个在线设备（并发 {POLL_WORKERS}，预算 {POLL_TIME_BUDGET}s）")

        start = time.time()
        processed = 0
        total_records = 0
        skipped = 0

        with ThreadPoolExecutor(max_workers=POLL_WORKERS) as executor:
            futures = {}
            for did in device_ids:
                if time.time() - start > POLL_TIME_BUDGET:
                    skipped = len(device_ids) - len(futures)
                    logger.warning(f"接口采集达到时间预算，停止提交剩余 {skipped} 台设备（下轮继续）")
                    break
                futures[executor.submit(_collect_device_interfaces, app, did, redis_params)] = did

            for future in as_completed(futures):
                try:
                    recs = future.result() or []
                    total_records += len(recs)
                    processed += 1
                except Exception as e:
                    logger.error(f"接口采集子任务异常: {e}")

        elapsed = time.time() - start
        logger.info(f"=========== 接口数据采集任务执行完毕 =============")
        logger.info(f"处理设备数: {processed}/{len(device_ids)}（跳过 {skipped}）")
        logger.info(f"推送记录总数: {total_records}")
        logger.info(f"总耗时: {elapsed:.2f}秒")



