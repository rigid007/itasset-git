# -*- coding: utf-8 -*-
"""批量执行中心核心服务：多协议执行引擎、任务状态机、定时调度、结果通知。"""
import hashlib
import logging
import os
import re
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from extensions import db
from models.exec_models import ExecTask, ExecTaskDevice
from models.models import Device, User

logger = logging.getLogger(__name__)

OUTPUT_MAX = 200_000

NETWORK_TYPES = {'router', 'switch', 'firewall', 'ap', 'load_balancer'}


# ==================== 协议解析 ====================

def resolve_device_protocol(device, preferred='auto'):
    """根据设备类型/品牌解析执行协议。"""
    if preferred and preferred != 'auto':
        return preferred
    brand = (device.brand or '').lower()
    dtype = (device.device_type or '').lower()
    osv = (device.os_version or '').lower()
    if dtype in NETWORK_TYPES or 'windows' in osv or 'win' in dtype:
        if 'windows' in osv or dtype in ('windows', 'win'):
            return 'winrm'
        return 'netmiko'
    from utils.device_config import resolve_vendor_family
    family = resolve_vendor_family(device)
    if family in ('huawei', 'cisco', 'juniper', 'ruijie', 'arista', 'procurve', 'generic'):
        return 'netmiko'
    if 'linux' in osv or family == 'linux':
        return 'ssh'
    if brand in ('windows', 'microsoft') or dtype == 'windows':
        return 'winrm'
    return 'ssh'


# ==================== 单协议执行 ====================

def _truncate(text, limit=OUTPUT_MAX):
    if not text:
        return ''
    text = str(text)
    return text if len(text) <= limit else text[:limit] + f'\n...[输出过长，已截断，共 {len(text)} 字符]'


def _run_local(content, is_script, timeout):
    """在本机执行（测试/管理机执行）。"""
    try:
        if is_script:
            if os.name == 'nt':
                proc = subprocess.run(
                    ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', content],
                    capture_output=True, text=True, timeout=timeout,
                )
            else:
                proc = subprocess.run(
                    ['/bin/bash', '-s'], input=content,
                    capture_output=True, text=True, timeout=timeout,
                )
        else:
            proc = subprocess.run(content, shell=True, capture_output=True, text=True, timeout=timeout)
        output = (proc.stdout or '') + ('\n' + proc.stderr if proc.stderr else '')
        return proc.returncode, _truncate(output), ''
    except subprocess.TimeoutExpired:
        return 124, '', f'命令执行超时（{timeout}秒）'
    except Exception as e:
        return 1, '', f'本地执行失败: {e}'


def _run_ssh(device, content, is_script, timeout, cancel_event=None):
    """通过 paramiko 在 Linux/通用设备上执行。"""
    import paramiko
    from utils.device_config import resolve_device_credential
    host = device.management_ip or device.ip_address
    username, password, port = resolve_device_credential(device)
    if not username:
        return 1, '', '设备未配置 SSH 凭据'
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        host, port=port, username=username, password=password,
        timeout=min(timeout, 15), look_for_keys=False, allow_agent=False,
    )
    try:
        if is_script:
            stdin, stdout, stderr = client.exec_command('/bin/bash -s', timeout=timeout)
            stdin.write(content)
            stdin.channel.shutdown_write()
        else:
            stdin, stdout, stderr = client.exec_command(content, timeout=timeout)
        out = stdout.read().decode(errors='replace')
        err = stderr.read().decode(errors='replace')
        code = stdout.channel.recv_exit_status()
        output = out + ('\n' + err if err else '')
        return code, _truncate(output), '' if code == 0 else err
    finally:
        client.close()


def _run_winrm(device, content, is_script, timeout):
    """通过 WinRM 在 Windows 主机上执行（优先 pywinrm，本机回退 PowerShell）。"""
    host = device.management_ip or device.ip_address
    try:
        import winrm  # pywinrm
    except ImportError:
        if host in ('127.0.0.1', 'localhost', '::1'):
            return _run_local(content, True, timeout)
        return 1, '', (
            '未安装 pywinrm 且目标非本机。请在服务端安装 pywinrm '
            '（pip install pywinrm）并在目标 Windows 主机启用 WinRM。'
        )
    from utils.device_config import resolve_device_credential
    username, password, port = resolve_device_credential(device)
    if not username:
        return 1, '', '设备未配置 WinRM 凭据'
    try:
        session = winrm.Session(
            host, auth=(username, password), transport='ntlm',
            server_cert_validation='ignore',
        )
        result = session.run_ps(content) if is_script else session.run_cmd(content)
        output = (result.std_out or '') + ('\n' + result.std_err if result.std_err else '')
        return result.status_code, _truncate(output), '' if result.status_code == 0 else result.std_err
    except Exception as e:
        return 1, '', f'WinRM 执行失败: {e}'


def _run_netmiko(device, content, timeout, config_mode=False, cancel_event=None):
    """通过 paramiko/netmiko 在网络设备上执行。"""
    from utils.device_config import run_device_commands
    result = run_device_commands(device, content, timeout=timeout, config_mode=config_mode)
    if result.get('success'):
        return 0, _truncate(result.get('output')), ''
    return 1, _truncate(result.get('output')), result.get('error') or '设备执行失败'


# ==================== 单设备执行 ====================

def _save_config_snapshot(record, task):
    """config_push 前保存配置快照（写入 record 与 ConfigVersion）。"""
    from utils.device_config import capture_device_config
    from models.compliance_models import ConfigVersion
    device = db.session.get(Device, record.device_id)
    if not device:
        return
    snap = capture_device_config(device, config_type='running', timeout=min(task.timeout or 30, 60))
    if snap.get('success'):
        record.snapshot_config = snap.get('content') or ''
        last = ConfigVersion.query.filter_by(device_id=device.id, config_type='running') \
            .order_by(ConfigVersion.version_number.desc()).first()
        version_number = (last.version_number + 1) if last else 1
        db.session.add(ConfigVersion(
            device_id=device.id,
            version_number=version_number,
            config_type='running',
            content=record.snapshot_config,
            change_summary=f'批量执行任务 #{task.id} {task.name} 变更前快照',
            checksum=hashlib.sha256((record.snapshot_config or '').encode()).hexdigest(),
            changed_by=f'task-{task.id}',
        ))
        db.session.flush()


def _run_device_exec(app, record_id, task_id, cancel_event):
    """在线程中执行单台设备，写入结果。"""
    with app.app_context():
        record = db.session.get(ExecTaskDevice, record_id)
        task = db.session.get(ExecTask, task_id)
        if not record or not task:
            return
        device = db.session.get(Device, record.device_id)
        if not device:
            record.status = 'failed'
            record.error = '设备不存在'
            db.session.commit()
            return
        if cancel_event.is_set():
            record.status = 'cancelled'
            db.session.commit()
            return

        record.status = 'running'
        record.started_at = datetime.utcnow()
        record.output = ''
        record.error = ''
        record.snapshot_config = None
        db.session.commit()
        start = time.time()
        try:
            if task.task_type == 'config_push':
                _save_config_snapshot(record, task)
                db.session.commit()
            protocol = resolve_device_protocol(device, record.protocol or task.protocol)
            record.protocol = protocol
            db.session.commit()
            is_script = task.task_type == 'script'
            if protocol == 'local':
                code, out, err = _run_local(task.content, is_script, task.timeout or 30)
            elif protocol == 'ssh':
                code, out, err = _run_ssh(device, task.content, is_script, task.timeout or 30, cancel_event)
            elif protocol == 'winrm':
                code, out, err = _run_winrm(device, task.content, is_script, task.timeout or 30)
            else:  # netmiko
                code, out, err = _run_netmiko(
                    device, task.content, task.timeout or 30,
                    config_mode=(task.task_type == 'config_push'), cancel_event=cancel_event,
                )
            record.exit_code = code
            record.output = out
            record.error = err
            record.status = 'success' if code == 0 else 'failed'
        except Exception as e:
            logger.exception(f"[exec] 设备 {record.device_name} 执行异常")
            record.status = 'failed'
            record.error = f'执行异常: {e}'
        finally:
            record.finished_at = datetime.utcnow()
            record.duration = round(time.time() - start, 2)
            db.session.commit()


# ==================== 任务级控制 ====================

_cancel_events = {}


def _get_cancel_event(task_id):
    return _cancel_events.setdefault(task_id, threading.Event())


def _clear_cancel_event(task_id):
    _cancel_events.pop(task_id, None)


def run_task(app, task_id, retry_failed=False):
    """执行任务：为每台设备创建线程并发执行。"""
    with app.app_context():
        task = db.session.get(ExecTask, task_id)
        if not task:
            return False
        if task.status == 'running':
            return False
        query = task.devices
        if retry_failed:
            query = query.filter(ExecTaskDevice.status.in_(['failed', 'cancelled']))
        records = query.all()
        if not records:
            task.status = 'failed'
            task.result_summary = '没有可执行的设备'
            task.finished_at = datetime.utcnow()
            db.session.commit()
            return False
        _clear_cancel_event(task.id)
        task.status = 'running'
        task.started_at = datetime.utcnow()
        task.finished_at = None
        task.last_run_at = datetime.utcnow()
        task.success_count = 0
        task.failed_count = 0
        db.session.commit()

    cancel_event = _get_cancel_event(task_id)
    max_workers = min(10, max(1, len(records)))
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(_run_device_exec, app, r.id, task_id, cancel_event) for r in records]
        for f in futures:
            try:
                f.result()
            except Exception:
                logger.exception('[exec] 线程执行异常')

    with app.app_context():
        task = db.session.get(ExecTask, task_id)
        if not task:
            return False
        _refresh_task_summary(task)
        _notify_task_finished(task)
        if task.schedule_enabled:
            task.next_run_at = _compute_next_run(task)
        db.session.commit()
    return True


def _refresh_task_summary(task):
    rows = task.devices.all()
    success = sum(1 for r in rows if r.status == 'success')
    failed = sum(1 for r in rows if r.status == 'failed')
    cancelled = sum(1 for r in rows if r.status == 'cancelled')
    total = len(rows)
    task.device_count = total
    task.success_count = success
    task.failed_count = failed
    if task.status == 'cancelled':
        pass
    elif total and failed == total:
        task.status = 'failed'
    elif total and cancelled == total:
        task.status = 'cancelled'
    elif total and success == total:
        task.status = 'completed'
    else:
        task.status = 'partial'
    task.finished_at = datetime.utcnow()
    task.result_summary = (
        f'共 {total} 台：成功 {success}，失败 {failed}，取消 {cancelled}'
    )


def cancel_task(app, task_id):
    """取消正在执行的任务。"""
    with app.app_context():
        task = db.session.get(ExecTask, task_id)
        if not task or task.status != 'running':
            return False
        event = _get_cancel_event(task.id)
        event.set()
        pending = task.devices.filter(ExecTaskDevice.status.in_(['pending'])).all()
        for r in pending:
            r.status = 'cancelled'
            r.finished_at = datetime.utcnow()
        db.session.commit()
        return True


def rollback_device(app, task_id, record_id):
    """按快照回滚单台设备的配置（config_push 任务）。"""
    from utils.device_config import rollback_device_config
    with app.app_context():
        record = db.session.get(ExecTaskDevice, record_id)
        if not record or not record.snapshot_config:
            return False, '该设备没有配置快照，无法回滚'
        device = db.session.get(Device, record.device_id)
        if not device:
            return False, '设备不存在'
        result = rollback_device_config(device, record.snapshot_config, timeout=60)
        record.status = 'success' if result.get('success') else 'failed'
        record.output = (record.output or '') + '\n\n[回滚结果]\n' + (result.get('output') or result.get('error') or '')
        record.error = '' if result.get('success') else (result.get('error') or '回滚失败')
        db.session.commit()
        return result.get('success', False), result.get('error') or '回滚完成'


# ==================== 通知 ====================

def _notify_task_finished(task):
    if not task.notify_enabled:
        return
    try:
        from services.notification_service import get_alert_settings, send_email, send_wechat
        settings = get_alert_settings()
        title = f'【执行中心】任务 {task.name} - {task.status}'
        content = (
            f'任务：{task.name}\n'
            f'状态：{task.status}\n'
            f'结果：{task.result_summary or ""}\n'
            f'开始：{task.started_at}\n'
            f'结束：{task.finished_at}'
        )
        recipients = []
        if task.created_by_user and task.created_by_user.email:
            recipients.append(task.created_by_user.email)
        if not recipients:
            admin = User.query.filter_by(role='admin').first()
            if admin and admin.email:
                recipients.append(admin.email)
        if recipients:
            send_email(recipients, title, content)
        if settings.get('wechat_webhook_url'):
            send_wechat([], title, content)
    except Exception as e:
        logger.warning(f'[exec] 任务完成通知发送失败: {e}')


# ==================== 定时调度 ====================

def _parse_interval(expr):
    m = re.match(r'^(\d+)\s*(s|m|h|d)$', (expr or '').strip().lower())
    if not m:
        return None
    num = int(m.group(1))
    unit = m.group(2)
    return num * {'s': 1, 'm': 60, 'h': 3600, 'd': 86400}[unit]


def _compute_next_run(task):
    seconds = _parse_interval(task.schedule_value)
    if task.schedule_type == 'interval' and seconds:
        return datetime.utcnow() + timedelta(seconds=seconds)
    return None


def _build_trigger(task):
    from apscheduler.triggers.interval import IntervalTrigger
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.date import DateTrigger
    if task.schedule_type == 'interval':
        seconds = _parse_interval(task.schedule_value)
        if seconds:
            return IntervalTrigger(seconds=seconds)
    elif task.schedule_type == 'cron':
        try:
            return CronTrigger.from_crontab(task.schedule_value)
        except Exception:
            return None
    elif task.schedule_type == 'once':
        try:
            dt = datetime.strptime(task.schedule_value, '%Y-%m-%d %H:%M')
            return DateTrigger(run_date=dt)
        except (ValueError, TypeError):
            return None
    return None


def validate_exec_schedule(schedule_type, schedule_value):
    """?????????????? (????, ????)?"""
    schedule_type = (schedule_type or '').strip()
    schedule_value = (schedule_value or '').strip()
    if not schedule_value:
        return False, '???????'
    if schedule_type == 'interval':
        if not _parse_interval(schedule_value):
            return False, '?????????????+????? 5m?1h?1d'
        return True, ''
    if schedule_type == 'cron':
        from apscheduler.triggers.cron import CronTrigger
        try:
            CronTrigger.from_crontab(schedule_value)
            return True, ''
        except Exception:
            return False, 'Cron ??????????0 3 * * *'
    if schedule_type == 'once':
        try:
            run_at = datetime.strptime(schedule_value, '%Y-%m-%d %H:%M')
        except (ValueError, TypeError):
            return False, '?????????? YYYY-MM-DD HH:MM'
        if run_at <= datetime.now():
            return False, '??????????????'
        return True, ''
    return False, '??????????'


def job_id_for(task_id):
    return f'exec_task_{task_id}'


def run_scheduled_exec_task(app, task_id):
    """定时任务触发入口。"""
    with app.app_context():
        task = db.session.get(ExecTask, task_id)
        if not task or not task.schedule_enabled:
            return
        if task.status == 'running':
            logger.info(f'[exec] 任务 {task.id} 正在执行，跳过本次调度')
            return
        task.status = 'ready'
        db.session.commit()
    run_task(app, task_id)


def register_scheduled_exec_tasks(scheduler, app):
    """启动时为所有启用调度的任务注册 APScheduler 作业。"""
    with app.app_context():
        tasks = ExecTask.query.filter_by(schedule_enabled=True).all()
        for task in tasks:
            trigger = _build_trigger(task)
            if not trigger:
                continue
            scheduler.add_job(
                func=run_scheduled_exec_task,
                args=[app, task.id],
                trigger=trigger,
                id=job_id_for(task.id),
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )
    logger.info(f'[exec] 已注册 {len(tasks)} 个定时执行任务')


def reschedule_exec_task(task_id):
    """任务保存后动态更新调度作业。"""
    from flask import current_app
    from scheduler import get_scheduler
    scheduler = get_scheduler()
    if not scheduler or not scheduler.running:
        return
    try:
        app = current_app._get_current_object()
    except Exception:
        return
    with app.app_context():
        task = db.session.get(ExecTask, task_id)
        jid = job_id_for(task_id)
        if scheduler.get_job(jid):
            scheduler.remove_job(jid)
        if task and task.schedule_enabled:
            trigger = _build_trigger(task)
            if trigger:
                scheduler.add_job(
                    func=run_scheduled_exec_task,
                    args=[app, task.id],
                    trigger=trigger,
                    id=jid,
                    replace_existing=True,
                    max_instances=1,
                    coalesce=True,
                )


def remove_exec_task_job(task_id):
    try:
        from scheduler import get_scheduler
        scheduler = get_scheduler()
        if scheduler and scheduler.running:
            jid = job_id_for(task_id)
            if scheduler.get_job(jid):
                scheduler.remove_job(jid)
    except Exception:
        pass
