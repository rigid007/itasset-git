# -*- coding: utf-8 -*-
"""复现“/24 扫描完成后任务卡在 running”的问题：
用真实的 background_device_scan + 模拟的 _run_snmp_scan_task_impl（254 个IP、多次 commit/rollback）。
"""
import sys, time, threading
sys.path.insert(0, r"D:\asset")

from app import app
from extensions import db
from models.models import DiscoveryTask
import blueprints.device as D


def fake_run_snmp_scan_task_impl(scan_task_id, scan_params):
    """模拟真实扫描：254 个 IP、进度更新、多次提交/回滚、最终写入 254 条结果"""
    import json
    total = 254
    results = []
    for i in range(total):
        ip = f"192.168.1.{i % 254}"
        results.append({
            'ip': ip,
            'device_name': f'设备_{ip}',
            'status': 'offline',
            'online': False,
            'snmp_status': D.SNMP_STATUS_UNSUPPORTED,
            'snmp_status_text': '不支持SNMP',
            'snmp_detail': '设备不支持SNMP或无SNMP响应',
            'added': False, 'updated': False, 'skipped': False,
            'type': 'non_snmp', 'device_id': None,
        })
        # 模拟真实扫描里的 commit / 偶发 rollback
        if i % 50 == 0:
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
        if i % 37 == 0:
            db.session.rollback()
        D.progress_manager.update_progress(
            scan_task_id,
            progress=5 + int((i + 1) / total * 85),
            processed=i + 1,
            current_step=f'扫描中 {i + 1}/{total}: {ip}',
        )
    D.progress_manager.update_progress(
        scan_task_id,
        status='completed',
        progress=100,
        added=0, updated=0, skipped=0, failed=0,
        end_time=__import__('datetime').datetime.now().isoformat(),
        results=results[:500],
        summary={'total': total, 'ok': 0, 'wrong_community': 0, 'unsupported': total},
        message=f'扫描 {total} 个IP：团体号正确 0 个，团体号错误 0 个，不支持SNMP {total} 个',
    )


def run():
    task = None
    try:
        with app.app_context():
            task = DiscoveryTask(
                name='__TEST_REPRO__',
                discovery_mode='device_scan',
                discovery_type='snmp_scan',
                target_type='ip_range',
                status='idle',
            )
            task.set_target_value({
                'ip_range': '192.168.1.1-254',
                'snmp_community': 'public',
                'snmp_version': '2c',
                'snmp_timeout': 2,
                'snmp_retries': 2,
                'auto_add': True,
                'skip_existing': True,
                'concurrent': 20,
            })
            db.session.add(task)
            db.session.commit()
            task_id = task.id

        D._run_snmp_scan_task_impl = fake_run_snmp_scan_task_impl
        # 用线程模拟 executor 调用
        from types import SimpleNamespace
        fake_app = SimpleNamespace(app_context=app.app_context)
        t = threading.Thread(target=D.background_device_scan, args=(task_id, fake_app), daemon=True)
        t.start()
        t.join(timeout=120)
        assert not t.is_alive(), "background_device_scan 线程未结束（疑似卡死）"

        with app.app_context():
            row = db.session.get(DiscoveryTask, task_id)
            print(f"[RESULT] status={row.status!r} progress={row.progress} last_result={str(row.last_result)[:60]}")
            if row.status == 'completed' and row.last_result and 'results' in row.last_result:
                print("[PASS] 扫描完成后任务状态为 completed 且结果已持久化")
            else:
                print("[FAIL] 复现：扫描完成后任务仍为 running / 无结果")
                raise SystemExit(1)
    finally:
        with app.app_context():
            if task is not None:
                db.session.delete(task)
                db.session.commit()


if __name__ == "__main__":
    run()
