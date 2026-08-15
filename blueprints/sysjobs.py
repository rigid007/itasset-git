"""系统定时任务管理

提供调度器内置任务的可视化与手动触发入口：
  GET  /system/jobs                  任务列表页面
  GET  /system/jobs/api/list         任务列表 JSON（供页面轮询刷新下次执行时间）
  POST /system/jobs/<job_id>/run     立即执行指定任务

手动触发通过 scheduler.run_job_now() 实现（改写 next_run_time），
仍受 max_instances=1 保护，不会与正在运行的同名任务并发。

蓝图名: sysjobs_bp
"""
from flask import Blueprint, render_template, jsonify, request
from flask_login import login_required, current_user

from utils.permission import permission_required
from utils.audit import log_audit

sysjobs_bp = Blueprint('sysjobs', __name__, url_prefix='/system/jobs')


def _load_jobs():
    """读取调度器任务并按分类分组"""
    from scheduler import get_all_jobs, get_scheduler, SYSTEM_JOB_META

    scheduler = get_scheduler()
    jobs = get_all_jobs()

    # 内置任务在前、按分类聚合；动态任务(发现任务/监控计划)归入"动态任务"
    order = ['监控采集', '拓扑发现', 'ITSM', '告警', '维护', '其他']
    grouped = {}
    for job in jobs:
        cat = job['category'] if job['is_system'] else '动态任务'
        grouped.setdefault(cat, []).append(job)

    categories = [c for c in order if c in grouped]
    categories += [c for c in grouped if c not in categories]

    # 已在元信息中登记但当前未注册到调度器的任务（便于发现"任务没起来"）
    registered = {j['id'] for j in jobs}
    missing = [
        {'id': jid, **meta}
        for jid, meta in SYSTEM_JOB_META.items()
        if jid not in registered
    ]

    return {
        'running': scheduler.running,
        'grouped': grouped,
        'categories': categories,
        'total': len(jobs),
        'missing': missing,
    }


@sysjobs_bp.route('/')
@login_required
@permission_required('system:jobs')
def job_list():
    """系统定时任务列表页面"""
    data = _load_jobs()
    return render_template(
        'system/jobs.html',
        scheduler_running=data['running'],
        grouped=data['grouped'],
        categories=data['categories'],
        total=data['total'],
        missing=data['missing'],
    )


@sysjobs_bp.route('/api/list')
@login_required
@permission_required('system:jobs')
def api_list():
    """任务列表 JSON（用于页面局部刷新）"""
    data = _load_jobs()
    flat = []
    for cat in data['categories']:
        flat.extend(data['grouped'][cat])
    return jsonify({
        'success': True,
        'scheduler_running': data['running'],
        'jobs': flat,
        'job_count': data['total'],
        'missing': [m['id'] for m in data['missing']],
    })


@sysjobs_bp.route('/<job_id>/run', methods=['POST'])
@login_required
@permission_required('system:jobs:run')
def api_run(job_id):
    """立即执行指定任务"""
    from scheduler import run_job_now, SYSTEM_JOB_META

    meta = SYSTEM_JOB_META.get(job_id)
    # 只允许触发登记为可手动执行的内置任务，避免误触发动态任务造成重复采集
    if meta is None:
        return jsonify({'success': False, 'message': f'非内置任务，不支持手动触发: {job_id}'}), 400
    if not meta.get('manual'):
        return jsonify({'success': False, 'message': f'该任务不允许手动触发: {job_id}'}), 400

    ok, message = run_job_now(job_id)
    if ok:
        log_audit('execute', 'scheduler_job', 0,
                  f"手动触发系统任务: {meta.get('name') or job_id} ({job_id})",
                  user_id=current_user.id)
    return jsonify({'success': ok, 'message': message}), (200 if ok else 400)
