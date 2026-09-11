# -*- coding: utf-8 -*-
"""
backup_bmc_web_scheduler_patch.py
=================================
把「BMC Web 控制台配置备份」挂接到项目 APScheduler 的示范片段。

⚠️ 本文件不直接运行，仅供复制以下代码到 scheduler.py 的 configure_scheduler() 中。
   放在现有任务注册之后即可，不改动任何其他任务，避免回归。

依赖：scripts/ops/ 已加入 sys.path（见下方 import 段），selenium + msedgedriver 已就位。
"""
import sys
import os

# 确保能 import scripts/ops 下的模块
_OPS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts', 'ops')
if _OPS_DIR not in sys.path:
    sys.path.insert(0, _OPS_DIR)


def register_bmc_web_backup_job(scheduler, app):
    """在 configure_scheduler() 内调用：注册 BMC Web 备份定时任务。"""
    from backup_bmc_web import backup_all_bmc_web

    job_id = 'bmc_web_backup_job'
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)

    scheduler.add_job(
        func=backup_all_bmc_web,
        args=[app],
        # 默认每天 03:30 执行（BMC 备份属低峰批处理，避开业务高峰）
        trigger=CronTrigger(hour=3, minute=30),
        id=job_id,
        replace_existing=True,
        max_instances=1,
    )
    return job_id


# ---- 在 scheduler.py 的 configure_scheduler(app) 末尾追加一行调用 ----
#
#   from scripts.ops.backup_bmc_web_scheduler_patch import register_bmc_web_backup_job
#   register_bmc_web_backup_job(scheduler, app)
#
# 如要手动立即触发一次（受 max_instances=1 保护，不会与定时任务并发冲突）：
#   scheduler.modify_job('bmc_web_backup_job', next_run_time=datetime.now())
#   或调用 scheduler.run_job_now? 本项目用 modify_job 方式触发（见 link_monitor）。
