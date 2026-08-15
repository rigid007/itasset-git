# scheduler.py
"""
统一的调度器管理模块
单例模式，确保整个应用只有一个调度器实例
"""
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
import logging
import atexit
import traceback
import datetime

logger = logging.getLogger(__name__)

# 全局调度器单例
_scheduler = None
_app = None  # Flask 应用引用，用于动态任务调度


def _get_app():
    """获取 Flask 应用实例"""
    return _app


def get_scheduler():
    """获取调度器单例"""
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler(
            job_defaults={
                'coalesce': False,
                'max_instances': 1,
                'misfire_grace_time': 60
            }
        )
    return _scheduler


def shutdown_scheduler():
    """关闭调度器"""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("调度器已关闭")
        _scheduler = None


def configure_scheduler(app):
    """
    配置并启动调度器
    只应调用一次，在应用启动时
    """
    global _app
    _app = app

    scheduler = get_scheduler()
    
    # 如果已经在运行，先停止（避免重复启动）
    if scheduler.running:
        logger.info("调度器已在运行，跳过启动")
        return scheduler
    
    # 导入任务函数（延迟导入避免循环依赖）
    from utils.tasks import (
        poll_all_devices_interfaces,
        check_all_devices_status,
    )
    from tasks.monitor import collect_device_metrics, evaluate_alerts
    from tasks.link_monitor import run_link_monitor, discover_topology, prune_stale_links_task
    from utils.ac_discovery import discover_all_controllers_task
    from tasks.sla_calculator import calculate_sla
    from tasks.sla_monitor import monitor_work_order_sla
    from tasks.retention import cleanup_monitoring_data
    from utils.logging_config import cleanup_old_log_files
    
    # =========== 轮询检测设备状态 ===============
    job_id = 'check_devices_status_job'
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
    
    scheduler.add_job(
        func=check_all_devices_status,
        args=[app],
        trigger=IntervalTrigger(minutes=5),  # 1分钟轮询1次
        id=job_id,
        replace_existing=True,
        max_instances=1
    )
    
    # =========== 轮询检测设备接口状态 ===============
    job_id = 'poll_interfaces_job'
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
    
    scheduler.add_job(
        func=poll_all_devices_interfaces,
        args=[app],
        trigger=IntervalTrigger(minutes=5),  # 5分钟轮询1次
        id=job_id,
        replace_existing=True,
        max_instances=1
    )
    
    # =========== 监控指标采集任务 ===============
    job_id = 'collect_metrics_job'
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
    
    scheduler.add_job(
        func=collect_device_metrics,
        args=[app],
        trigger=IntervalTrigger(seconds=60),  # 原 30s，改为 60s 配合并发采集，降低 DB 写入频率
        id=job_id,
        replace_existing=True,
        max_instances=1
    )
    
    # =========== 链路状态监控任务（新增） ===============
    job_id = 'link_monitor_job'
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
    
    scheduler.add_job(
        func=run_link_monitor,
        args=[app],
        trigger=IntervalTrigger(seconds=300),  # 原 120s，改为 300s 减轻链路全量扫描压力
        id=job_id,
        replace_existing=True,
        max_instances=1
    )
    
    # =========== LLDP拓扑自动发现任务（新增） ===============
    job_id = 'lldp_discovery_job'
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)

    scheduler.add_job(
        func=discover_topology,
        args=[app],
        trigger=IntervalTrigger(hours=1),  # 每小时发现一次
        id=job_id,
        replace_existing=True,
        max_instances=1
    )

    # =========== 僵尸链路老化清理任务（新增） ===============
    # 每日凌晨 3:10 执行：将超过 TTL 未再被 LLDP 确认的自动发现链路标记为 stale
    job_id = 'prune_stale_links_job'
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)

    scheduler.add_job(
        func=prune_stale_links_task,
        args=[app],
        trigger=CronTrigger(hour=3, minute=10),
        id=job_id,
        replace_existing=True,
        max_instances=1
    )

    # =========== 无线控制器(AC) AP 发现任务 ===============
    job_id = 'ac_ap_discovery_job'
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)

    scheduler.add_job(
        func=discover_all_controllers_task,
        args=[app],
        trigger=CronTrigger(hour=2, minute=30),  # 每日 02:30 发现一次 AP
        id=job_id,
        replace_existing=True,
        max_instances=1
    )

    # =========== SLA在线率计算任务 ===============
    job_id = 'sla_calculation_job'
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)

    scheduler.add_job(
        func=calculate_sla,
        args=[app],
        trigger=IntervalTrigger(hours=6),  # 每6小时计算一次
        id=job_id,
        replace_existing=True,
        max_instances=1
    )

    # =========== 真实可用率采集任务（CSI/SLA 仪表盘数据源） ===============
    # 每日凌晨 2:30 执行：基于 DeviceMonitorLog 计算设备级/服务级真实可用率，
    # 供 CSI 仪表盘与 SLA 报表读取，避免回退到基于工单时长的偏弱代理算法。
    job_id = 'availability_collect_job'
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)

    def collect_availability_job():
        from extensions import db
        from utils.availability import collect_availability
        with app.app_context():
            try:
                stats = collect_availability(db.session, days=30)
                db.session.commit()
                app.logger.info(
                    f"[可用率] 定时采集完成: {stats['written']} 条 "
                    f"(设备 {len(stats['device_rows'])} / 服务 {len(stats['service_rows'])})"
                )
            except Exception as e:
                db.session.rollback()
                app.logger.error(f"[可用率] 定时采集失败: {e}")

    scheduler.add_job(
        func=collect_availability_job,
        trigger=CronTrigger(hour=2, minute=30),
        id=job_id,
        replace_existing=True,
        max_instances=1
    )

        # =========== 告警规则评估任务 ===============
    job_id = 'evaluate_alerts_job'
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)

    scheduler.add_job(
        func=evaluate_alerts,
        args=[app],
        trigger=IntervalTrigger(minutes=5),  # every 5 min evaluate alert rules
        id=job_id,
        replace_existing=True,
        max_instances=1
    )

    # =========== 工单 SLA 违约监控任务（新增） ===============
    job_id = 'work_order_sla_monitor_job'
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)

    scheduler.add_job(
        func=monitor_work_order_sla,
        args=[app],
        trigger=IntervalTrigger(minutes=15),  # 每15分钟检测一次 SLA 违约
        id=job_id,
        replace_existing=True,
        max_instances=1
    )

    # =========== 监控数据保留清理任务（新增） ===============
    # 每日凌晨 3:00 执行，按 CollectionSetting.data_retention_days 分批清理过期时序数据
    job_id = 'cleanup_monitoring_data_job'
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)

    scheduler.add_job(
        func=cleanup_monitoring_data,
        args=[app],
        trigger=CronTrigger(hour=3, minute=0),
        id=job_id,
        replace_existing=True,
        max_instances=1
    )

    # =========== 应用日志文件保留清理任务（新增） ===============
    # 每日凌晨 3:30 执行，删除 logs/ 目录下修改时间超过 180 天的日志轮转备份（app.log.N 等）
    job_id = 'cleanup_old_logs_job'
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)

    scheduler.add_job(
        func=cleanup_old_log_files,
        trigger=CronTrigger(hour=3, minute=30),
        id=job_id,
        replace_existing=True,
        max_instances=1
    )

    # 启动调度器
    scheduler.start()
    logger.info("APScheduler 已启动，所有定时任务已添加")

    # =========== 加载数据库中已配置的间隔发现任务 ===========
    bootstrap_discovery_tasks(app)

    # =========== 加载数据库中已启用的监控计划（MonitorSchedule） ===========
    bootstrap_monitor_schedules(app)

    # =========== 启动事件驱动监控（SNMP Trap / Syslog / 心跳） ===========
    try:
        from services.event_monitor import start_event_monitor
        start_event_monitor(app)
    except Exception as e:
        logger.error(f"启动事件驱动监控失败: {e}")

    # 打印当前任务列表
    jobs = scheduler.get_jobs()
    logger.info(f"当前调度任务: {[job.id for job in jobs]}")
    for job in jobs:
        logger.info(f"任务 {job.id} 下次执行时间: {job.next_run_time}")
    
    # 注册应用退出时关闭调度器
    atexit.register(shutdown_scheduler)
    
    return scheduler


def add_job_to_scheduler(job_func, trigger, job_id=None, **kwargs):
    """
    动态添加任务到调度器
    :param job_func: 任务函数
    :param trigger: 触发器 (IntervalTrigger 或 CronTrigger)
    :param job_id: 任务ID (可选)
    :param kwargs: 其他参数
    """
    scheduler = get_scheduler()
    
    if job_id and scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
    
    job = scheduler.add_job(
        func=job_func,
        trigger=trigger,
        id=job_id,
        replace_existing=True,
        max_instances=1,
        **kwargs
    )
    
    logger.info(f"动态添加任务: {job.id}")
    return job


def remove_job_from_scheduler(job_id):
    """
    从调度器移除任务
    :param job_id: 任务ID
    """
    scheduler = get_scheduler()
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
        logger.info(f"移除任务: {job_id}")
        return True
    return False


# ==================== 系统内置任务元信息 ====================
# key = configure_scheduler() 中注册的 job_id
# 供"系统任务"页面展示中文名/说明/分类，以及判定哪些任务允许手动触发
SYSTEM_JOB_META = {
    'check_devices_status_job': {
        'name': '设备状态检测',
        'category': '监控采集',
        'desc': '对全部在网设备做 SNMP+Ping 探测，状态跃迁时写监控日志并产生设备离线告警（走事件关联引擎）',
        'manual': True,
    },
    'poll_interfaces_job': {
        'name': '接口状态轮询',
        'category': '监控采集',
        'desc': '轮询设备接口 up/down 与流量计数',
        'manual': True,
    },
    'collect_metrics_job': {
        'name': '性能指标采集',
        'category': '监控采集',
        'desc': '采集 CPU/内存/温度等性能指标',
        'manual': True,
    },
    'link_monitor_job': {
        'name': '链路监控',
        'category': '监控采集',
        'desc': '检测链路连通性，链路 down 时产生告警并走事件关联引擎',
        'manual': True,
    },
    'lldp_discovery_job': {
        'name': 'LLDP 拓扑发现',
        'category': '拓扑发现',
        'desc': '通过 LLDP 邻居表自动发现并维护设备间连接关系',
        'manual': True,
    },
    'prune_stale_links_job': {
        'name': '过期链路清理',
        'category': '拓扑发现',
        'desc': '清理长期未被发现确认的失效链路',
        'manual': True,
    },
    'ac_ap_discovery_job': {
        'name': '无线 AC/AP 发现',
        'category': '拓扑发现',
        'desc': '从无线控制器拉取 AP 列表并匹配接入交换机端口',
        'manual': True,
    },
    'sla_calculation_job': {
        'name': 'SLA 在线率计算',
        'category': 'ITSM',
        'desc': '基于 DeviceMonitorLog 计算设备月/季/年在线率，写入 SlaUptime',
        'manual': True,
    },
    'availability_collect_job': {
        'name': '真实可用率采集',
        'category': 'ITSM',
        'desc': '基于监控日志停机区间并集计算设备/服务真实可用率，写入 AvailabilityRecord（CSI 仪表盘数据源）',
        'manual': True,
    },
    'evaluate_alerts_job': {
        'name': '告警规则评估',
        'category': '告警',
        'desc': '按阈值规则评估最新指标并生成告警历史',
        'manual': True,
    },
    'work_order_sla_monitor_job': {
        'name': '工单 SLA 违约检测',
        'category': 'ITSM',
        'desc': '扫描进行中工单的响应/解决时限，标记临期与违约',
        'manual': True,
    },
    'cleanup_monitoring_data_job': {
        'name': '监控数据清理',
        'category': '维护',
        'desc': '按保留策略清理过期监控明细数据',
        'manual': True,
    },
    'cleanup_old_logs_job': {
        'name': '日志文件清理',
        'category': '维护',
        'desc': '按保留天数轮转并删除过期日志文件',
        'manual': True,
    },
}


def _describe_job(job):
    """把 APScheduler Job 转成带元信息的字典"""
    meta = SYSTEM_JOB_META.get(job.id, {})
    return {
        'id': job.id,
        'name': meta.get('name') or job.name or job.id,
        'raw_name': job.name,
        'category': meta.get('category') or '其他',
        'desc': meta.get('desc') or '',
        'manual': bool(meta.get('manual')),
        'is_system': job.id in SYSTEM_JOB_META,
        'trigger': str(job.trigger),
        'next_run_time': job.next_run_time.strftime('%Y-%m-%d %H:%M:%S') if job.next_run_time else None,
        'pending': job.pending,
    }


def get_all_jobs():
    """
    获取所有任务信息（含中文名/说明/触发器/下次执行时间）
    :return: 任务列表
    """
    scheduler = get_scheduler()
    return [_describe_job(job) for job in scheduler.get_jobs()]


def run_job_now(job_id):
    """
    立即触发一个已注册的调度任务（不影响其原有周期）

    实现方式：把 next_run_time 改为当前时间，交由 APScheduler 自己调度执行。
    好处是仍然受 max_instances=1 保护，不会与正在运行的同名任务并发；
    执行完毕后 APScheduler 会按原 trigger 重新计算下次执行时间。

    :param job_id: 任务 ID
    :return: (success: bool, message: str)
    """
    scheduler = get_scheduler()
    if not scheduler.running:
        return False, '调度器未运行'

    job = scheduler.get_job(job_id)
    if not job:
        return False, f'任务不存在: {job_id}'

    try:
        now = datetime.datetime.now(scheduler.timezone)
    except Exception:
        now = datetime.datetime.now()

    try:
        scheduler.modify_job(job_id, next_run_time=now)
        logger.info(f"手动触发调度任务: {job_id}")
        return True, '已提交执行（后台异步运行，请稍后查看结果）'
    except Exception as e:
        logger.error(f"手动触发任务 {job_id} 失败: {e}")
        return False, f'触发失败: {e}'


def pause_scheduler():
    """暂停调度器"""
    scheduler = get_scheduler()
    if scheduler.running:
        scheduler.pause()
        logger.info("调度器已暂停")
        return True
    return False


def resume_scheduler():
    """恢复调度器"""
    scheduler = get_scheduler()
    if not scheduler.running:
        scheduler.resume()
        logger.info("调度器已恢复")
        return True
    return False


def is_scheduler_running():
    """检查调度器是否在运行"""
    scheduler = get_scheduler()
    return scheduler.running


# ==================== MonitorSchedule 动态调度 ====================
# monitor_type（含历史兼容别名）-> 实际任务函数
def _get_monitor_task_map():
    from utils.tasks import check_all_devices_status, poll_all_devices_interfaces
    from tasks.monitor import collect_device_metrics, evaluate_alerts
    from tasks.link_monitor import run_link_monitor, discover_topology
    return {
        # 规范键（新表单值）
        'device_status': check_all_devices_status,
        'interface_poll': poll_all_devices_interfaces,
        'metrics': collect_device_metrics,
        'link_monitor': run_link_monitor,
        'lldp_discovery': discover_topology,
        'alert_evaluate': evaluate_alerts,
        # 历史兼容别名（旧表单值 ping/snmp 均指设备状态检测）
        'ping': check_all_devices_status,
        'snmp': check_all_devices_status,
    }


# 规范 monitor_type -> 硬编码基线任务 job_id（被 MonitorSchedule 覆盖时移除，避免双跑）
_BASELINE_JOB_MAP = {
    'device_status': 'check_devices_status_job',
    'interface_poll': 'poll_interfaces_job',
    'metrics': 'collect_metrics_job',
    'link_monitor': 'link_monitor_job',
    'lldp_discovery': 'lldp_discovery_job',
    'alert_evaluate': 'evaluate_alerts_job',
}

# monitor_type -> 规范键（用于判断覆盖哪个基线任务）
_ALIAS_TO_CANON = {
    'device_status': 'device_status', 'interface_poll': 'interface_poll',
    'metrics': 'metrics', 'link_monitor': 'link_monitor',
    'lldp_discovery': 'lldp_discovery', 'alert_evaluate': 'alert_evaluate',
    'ping': 'device_status', 'snmp': 'device_status',
}


def _in_time_window(schedule, now=None):
    """检查当前是否处于调度时间窗口内（weekdays / start_time / end_time）"""
    now = now or datetime.datetime.now(datetime.timezone.utc).astimezone()
    if schedule.weekdays:
        # 表单 1=周一 ... 7=周日；datetime.weekday() 周一=0
        allowed = set()
        for part in str(schedule.weekdays).split(','):
            part = part.strip()
            if not part:
                continue
            try:
                allowed.add((int(part) - 1) % 7)
            except ValueError:
                pass
        if allowed and now.weekday() not in allowed:
            return False
    cur = now.time()
    if schedule.start_time and schedule.end_time:
        if not (schedule.start_time <= cur <= schedule.end_time):
            return False
    elif schedule.start_time and cur < schedule.start_time:
        return False
    elif schedule.end_time and cur > schedule.end_time:
        return False
    return True


def _make_windowed_run(app, func, schedule):
    """生成一个带时间窗口判断的包装任务"""
    def _run():
        if not _in_time_window(schedule):
            logger.debug(f"监控计划 #{schedule.id} {schedule.name} 当前不在时间窗口，跳过")
            return
        logger.info(f"执行监控计划 #{schedule.id} {schedule.name} (monitor_type={schedule.monitor_type})")
        try:
            func(app)
            schedule.last_status = 'success'
            schedule.success_count = (schedule.success_count or 0) + 1
        except Exception as e:
            schedule.last_status = 'error'
            schedule.last_error = str(e)[:500]
            schedule.fail_count = (schedule.fail_count or 0) + 1
            logger.error(f"监控计划 #{schedule.id} 执行失败: {e}")
        finally:
            schedule.last_run = datetime.datetime.utcnow()
            schedule.run_count = (schedule.run_count or 0) + 1
            try:
                from extensions import db
                db.session.commit()
            except Exception:
                pass
    return _run


def _register_monitor_schedule(schedule):
    """把一个 MonitorSchedule 注册到调度器（覆盖式）"""
    app = _get_app()
    if not app:
        logger.error("无法注册监控计划：应用实例未初始化")
        return None
    func = _get_monitor_task_map().get(schedule.monitor_type)
    if not func:
        logger.warning(f"监控计划 #{schedule.id} monitor_type={schedule.monitor_type} 无对应任务函数，跳过")
        return None

    job_id = f'monitor_schedule_{schedule.id}'
    scheduler = get_scheduler()
    try:
        scheduler.remove_job(job_id)
    except Exception:
        pass

    run = _make_windowed_run(app, func, schedule)

    if schedule.schedule_type == 'cron' and schedule.cron_expression:
        try:
            minute, hour, day, month, dow = schedule.cron_expression.strip().split()
            job = scheduler.add_job(
                func=run,
                trigger=CronTrigger(minute=minute, hour=hour, day=day, month=month, day_of_week=dow),
                id=job_id, replace_existing=True, max_instances=1)
        except Exception as e:
            logger.error(f"监控计划 #{schedule.id} Cron 表达式无效: {e}")
            return None
    elif schedule.schedule_type == 'interval':
        secs = max(int(schedule.interval_seconds or 60), 5)
        job = scheduler.add_job(
            func=run, trigger=IntervalTrigger(seconds=secs),
            id=job_id, replace_existing=True, max_instances=1)
    else:
        logger.info(f"监控计划 #{schedule.id} 为手动类型，不注册自动调度")
        return None

    schedule.next_run = job.next_run_time
    try:
        from extensions import db
        db.session.commit()
    except Exception:
        pass
    logger.info(f"已注册监控计划 #{schedule.id} {schedule.name} (下次执行: {job.next_run_time})")
    return job


def apply_monitor_schedule(schedule):
    """保存/启用后调用：注册或更新调度；未启用则移除"""
    if schedule.enabled:
        return _register_monitor_schedule(schedule)
    return remove_monitor_schedule(schedule.id)


def remove_monitor_schedule(schedule_id):
    """移除某个监控计划的调度任务"""
    job_id = f'monitor_schedule_{schedule_id}'
    scheduler = get_scheduler()
    try:
        scheduler.remove_job(job_id)
        logger.info(f"已移除监控计划 #{schedule_id} 调度")
        return True
    except Exception:
        return False


def bootstrap_monitor_schedules(app):
    """启动时加载所有启用中的监控计划，并覆盖对应硬编码基线任务以避免双跑"""
    from models.models import MonitorSchedule
    with app.app_context():
        schedules = MonitorSchedule.query.filter_by(enabled=True).all()
        overridden = set()
        count = 0
        for s in schedules:
            canon = _ALIAS_TO_CANON.get(s.monitor_type)
            if _register_monitor_schedule(s):
                count += 1
                if canon:
                    overridden.add(canon)
        # 移除被覆盖的硬编码基线任务
        sched = get_scheduler()
        for canon in overridden:
            jid = _BASELINE_JOB_MAP.get(canon)
            if jid and sched.get_job(jid):
                sched.remove_job(jid)
                logger.info(f"监控计划已覆盖硬编码基线任务 {jid}，已移除避免双跑")
        logger.info(f"已从数据库加载 {count} 个监控计划调度（覆盖 {len(overridden)} 个基线任务）")


def run_monitor_schedule_now(schedule):
    """立即执行某个监控计划对应的任务（用于"立即运行"按钮）"""
    app = _get_app()
    if not app:
        return False, "应用实例未初始化"
    func = _get_monitor_task_map().get(schedule.monitor_type)
    if not func:
        return False, f"monitor_type={schedule.monitor_type} 无对应任务函数"
    import threading
    def _worker():
        try:
            with app.app_context():
                func(app)
                schedule.last_status = 'success'
                schedule.success_count = (schedule.success_count or 0) + 1
        except Exception as e:
            schedule.last_status = 'error'
            schedule.last_error = str(e)[:500]
            schedule.fail_count = (schedule.fail_count or 0) + 1
            logger.error(f"立即执行监控计划 #{schedule.id} 失败: {e}")
        finally:
            schedule.last_run = datetime.datetime.utcnow()
            schedule.run_count = (schedule.run_count or 0) + 1
            try:
                from extensions import db
                db.session.commit()
            except Exception:
                pass
    threading.Thread(target=_worker, daemon=True).start()
    return True, "已触发执行"


# ==================== 任务工厂函数 ====================

def create_monitor_job(app, job_name: str, interval: int, func):
    """
    创建监控任务的辅助函数
    :param app: Flask应用
    :param job_name: 任务名称
    :param interval: 间隔时间（秒）
    :param func: 任务函数
    """
    job_id = f'{job_name}_job'
    scheduler = get_scheduler()
    
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
    
    scheduler.add_job(
        func=func,
        args=[app],
        trigger=IntervalTrigger(seconds=interval),
        id=job_id,
        replace_existing=True,
        max_instances=1
    )
    
    logger.info(f"创建监控任务: {job_name} (间隔: {interval}秒)")
    return job_id


def create_cron_job(app, job_name: str, cron_expr: str, func):
    """
    创建Cron任务的辅助函数
    :param app: Flask应用
    :param job_name: 任务名称
    :param cron_expr: Cron表达式 (如: '0 3 * * *')
    :param func: 任务函数
    """
    job_id = f'{job_name}_job'
    scheduler = get_scheduler()
    
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
    
    # 解析Cron表达式
    parts = cron_expr.split()
    if len(parts) != 5:
        raise ValueError(f"无效的Cron表达式: {cron_expr}")
    
    minute, hour, day, month, day_of_week = parts
    
    scheduler.add_job(
        func=func,
        args=[app],
        trigger=CronTrigger(
            minute=minute,
            hour=hour,
            day=day,
            month=month,
            day_of_week=day_of_week
        ),
        id=job_id,
        replace_existing=True,
        max_instances=1
    )
    
    logger.info(f"创建Cron任务: {job_name} (表达式: {cron_expr})")
    return job_id


# ==================== 发现任务动态调度 ====================

def schedule_discovery_task(task_id: int, interval_seconds: int):
    """
    为发现任务注册间隔调度器任务
    :param task_id: 发现任务 ID
    :param interval_seconds: 执行间隔（秒）
    :return: job 对象，失败返回 None
    """
    app = _get_app()
    if not app:
        logger.error(f"无法注册发现任务 #{task_id}：应用实例未初始化")
        return None

    job_id = f'discovery_task_{task_id}'
    scheduler = get_scheduler()

    # 强制移除旧任务
    try:
        scheduler.remove_job(job_id)
        print(f"[调度] 发现任务 #{task_id} 旧调度已移除")
    except Exception:
        pass  # 旧任务不存在，忽略

    try:
        # 延迟导入避免循环依赖
        from blueprints.topology import background_discovery

        job = scheduler.add_job(
            func=background_discovery,
            args=[task_id, app],
            trigger=IntervalTrigger(seconds=max(interval_seconds, 10)),  # 最少10秒
            id=job_id,
            replace_existing=True,
            max_instances=1
        )

        print(f"[调度] 发现任务 #{task_id} 间隔调度已注册: {interval_seconds}秒 (下次执行: {job.next_run_time})")
        logger.info(f"已注册发现任务 #{task_id} 间隔调度: {interval_seconds}秒 (下次执行: {job.next_run_time})")
        return job

    except Exception as e:
        logger.error(f"发现任务 #{task_id} 间隔调度注册失败: {e}")
        traceback.print_exc()
        return None


def schedule_discovery_task_cron(task_id: int, cron_expr: str):
    """
    为发现任务注册 Cron 调度器任务
    :param task_id: 发现任务 ID
    :param cron_expr: Cron 表达式 (5 字段: 分 时 日 月 周)
    :return: job 对象，失败返回 None
    """
    app = _get_app()
    if not app:
        logger.error(f"无法注册发现任务 #{task_id}：应用实例未初始化")
        return None

    # ===== 先移除旧的调度任务（强制，不依赖 get_job 检查） =====
    job_id = f'discovery_task_{task_id}'
    scheduler = get_scheduler()

    # 强制移除旧任务
    try:
        scheduler.remove_job(job_id)
        print(f"[调度] 发现任务 #{task_id} 旧调度已移除")
    except Exception:
        pass  # 旧任务不存在，忽略

    # ===== 验证 Cron 表达式 =====
    if not cron_expr or not cron_expr.strip():
        logger.error(f"发现任务 #{task_id} Cron 表达式为空")
        return None

    parts = cron_expr.strip().split()
    if len(parts) != 5:
        logger.error(f"发现任务 #{task_id} Cron 表达式无效，需要5个字段: '{cron_expr}'")
        return None

    try:
        minute, hour, day, month, day_of_week = parts

        # 延迟导入避免循环依赖
        from blueprints.topology import background_discovery

        job = scheduler.add_job(
            func=background_discovery,
            args=[task_id, app],
            trigger=CronTrigger(
                minute=minute,
                hour=hour,
                day=day,
                month=month,
                day_of_week=day_of_week
            ),
            id=job_id,
            replace_existing=True,
            max_instances=1
        )

        print(f"[调度] 发现任务 #{task_id} Cron 调度已注册: {cron_expr} (下次执行: {job.next_run_time})")
        logger.info(f"已注册发现任务 #{task_id} Cron 调度: {cron_expr} (下次执行: {job.next_run_time})")
        return job

    except Exception as e:
        logger.error(f"发现任务 #{task_id} Cron 调度注册失败: {e}")
        return None


def unschedule_discovery_task(task_id: int):
    """
    移除发现任务的调度器任务（强制移除，不依赖 get_job 检查）
    :param task_id: 发现任务 ID
    :return: 是否成功移除
    """
    job_id = f'discovery_task_{task_id}'
    scheduler = get_scheduler()

    # 先打印当前所有任务，方便排查
    all_job_ids = [j.id for j in scheduler.get_jobs()]
    print(f"[调度] 当前调度器中的任务: {all_job_ids}")

    # 方法1: 直接 remove_job（如果不存在会抛异常）
    try:
        scheduler.remove_job(job_id)
        print(f"[调度] 发现任务 #{task_id} 调度已移除 (job_id={job_id})")
        logger.info(f"移除发现任务 #{task_id} 调度")
        return True
    except Exception as e:
        # remove_job 在 job 不存在时可能抛 JobLookupError 或其他异常
        print(f"[调度] 发现任务 #{task_id} 调度不存在或已移除 ({e})")

    # 方法2: 二次确认，遍历所有 job 按 ID 前缀匹配清除
    for job in scheduler.get_jobs():
        if str(task_id) in job.id:
            try:
                scheduler.remove_job(job.id)
                print(f"[调度] 通过遍历移除了可疑任务: {job.id}")
            except Exception:
                pass

    return False


def bootstrap_discovery_tasks(app):
    """
    应用启动时加载数据库中所有配置了间隔/Cron 调度的发现任务
    :param app: Flask 应用实例
    """
    from models.models import DiscoveryTask

    with app.app_context():
        tasks = DiscoveryTask.query.filter(
            DiscoveryTask.schedule_type.in_(['interval', 'cron']),
            DiscoveryTask.enabled == True
        ).all()

        count = 0
        for task in tasks:
            try:
                if task.schedule_type == 'interval':
                    schedule_discovery_task(task.id, task.interval_seconds or 3600)
                    count += 1
                elif task.schedule_type == 'cron' and task.cron_expression:
                    schedule_discovery_task_cron(task.id, task.cron_expression)
                    count += 1
            except Exception as e:
                logger.error(f"加载发现任务 #{task.id} '{task.name}' 调度失败: {e}")

        logger.info(f"已从数据库加载 {count} 个发现任务调度")


def get_discovery_job_info(task_id: int) -> dict:
    """
    获取发现任务的调度器任务信息
    :param task_id: 发现任务 ID
    :return: 包含 job 信息的字典，或 None
    """
    job_id = f'discovery_task_{task_id}'
    scheduler = get_scheduler()
    job = scheduler.get_job(job_id)
    if job:
        return {
            'job_id': job.id,
            'next_run_time': str(job.next_run_time) if job.next_run_time else None,
            'pending': job.pending,
        }
    return None