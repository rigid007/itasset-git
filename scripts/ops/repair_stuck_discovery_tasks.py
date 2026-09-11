# -*- coding: utf-8 -*-
"""
修复“扫描已完成但任务卡在 running”的发现任务。

背景：last_result 曾为 MySQL TEXT(64KB)，/24 扫描的数百条结果 JSON 超过上限，
导致最终状态写入失败、任务停留在 running。列已改为 MEDIUMTEXT 后，
本脚本把仍卡住的任务从进度管理器临时文件中找回已完成的结果并恢复状态。

用法：
    python scripts/ops/repair_stuck_discovery_tasks.py --dry-run   # 只预览
    python scripts/ops/repair_stuck_discovery_tasks.py             # 实际修复
"""
import sys, os, json, tempfile, argparse
from datetime import datetime, timedelta

sys.path.insert(0, r"D:\asset")

from app import app
from extensions import db
from models.models import DiscoveryTask

LOCAL_UTC_OFFSET = timedelta(hours=8)  # Asia/Shanghai
MATCH_TOLERANCE = timedelta(minutes=5)


def load_progress_file():
    path = os.path.join(tempfile.gettempdir(), 'device_import_progress.json')
    if not os.path.exists(path):
        return {}
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def find_matching_progress(task, progress_tasks):
    """按 last_run(UTC) 与进度任务的 start_time(本地) 匹配，返回最接近的进度任务"""
    if not task.last_run:
        return None
    last_run_local = task.last_run + LOCAL_UTC_OFFSET
    best, best_diff = None, None
    for tid, pt in progress_tasks.items():
        if pt.get('status') != 'completed':
            continue
        try:
            start = datetime.fromisoformat(pt['start_time'])
        except (KeyError, ValueError):
            continue
        diff = abs(start - last_run_local)
        if diff <= MATCH_TOLERANCE and (best_diff is None or diff < best_diff):
            best, best_diff = (tid, pt), diff
    return best


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true', help='只预览，不写库')
    args = parser.parse_args()

    progress_tasks = load_progress_file()
    repaired = 0
    with app.app_context():
        stuck = DiscoveryTask.query.filter(
            DiscoveryTask.discovery_mode == 'device_scan',
            DiscoveryTask.status == 'running',
            DiscoveryTask.progress >= 100,
        ).all()
        if not stuck:
            print('没有需要修复的卡住任务')
            return 0

        for task in stuck:
            match = find_matching_progress(task, progress_tasks)
            if not match:
                print(f'[跳过] 任务 #{task.id} {task.name!r}: 未找到匹配的已完成扫描进度')
                continue
            tid, pt = match
            results = pt.get('results', [])
            summary = pt.get('summary', {})
            print(f'[修复] 任务 #{task.id} {task.name!r}: 进度任务 {tid}, {len(results)} 条结果, '
                  f'汇总 {summary}')
            if args.dry_run:
                continue
            task.status = 'completed'
            task.progress = 100
            task.run_count = (task.run_count or 0) + 1
            task.success_count = (task.success_count or 0) + 1
            task.set_last_result({
                'progress_task_id': tid,
                'summary': summary,
                'results': results,
                'completed_at': pt.get('end_time') or datetime.now().isoformat(),
            })
            db.session.commit()
            repaired += 1
            print(f'  -> 已恢复为 completed，结果已写回 last_result')

    print(f'完成: 修复 {repaired} 个任务' + ('（dry-run，未写库）' if args.dry_run else ''))
    return 0


if __name__ == '__main__':
    sys.exit(main())
