#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""ITSM 高级模块冒烟测试（事件关联 / SLA / KEDB / CSI）

用途：上线前或改动后快速验证四大模块的"接线"是否完好——
      表在不在、路由通不通、权限播没播、调度任务注册没注册、引擎跑不跑得起来。

特点：
  * 所有写操作都在一个事务里进行，结束时统一 ROLLBACK，**不会污染生产库**。
  * 只读检查与功能检查分开计分，任何一项失败都会以非 0 退出码结束（便于接 CI）。

用法：
    # 针对当前配置的数据库（读取 config.py / DATABASE_URL 环境变量）
    python smoke_test_itsm.py

    # 针对一个临时 SQLite（完全隔离，适合在开发机验证代码改动）
    DATABASE_URL="sqlite:///D:/asset/.smoke/smoke.db" python smoke_test_itsm.py

    # 只跑只读检查，跳过所有写操作
    python smoke_test_itsm.py --readonly
"""
import os
import sys
import argparse
import traceback
from datetime import datetime, timedelta

# 使脚本可从任意目录运行（scripts/tests -> 项目根）
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))

# 避免测试时启动 SNMP Trap / Syslog 监听端口
os.environ.setdefault('EVENT_MONITOR_ENABLED', '0')

RESULTS = []


def check(name, category='通用'):
    """装饰器：把一个检查函数登记为冒烟用例"""
    def deco(fn):
        fn._smoke_name = name
        fn._smoke_category = category
        RESULTS.append(fn)
        return fn
    return deco


# ===========================================================================
# A. 结构性检查（只读）
# ===========================================================================
@check('ITSM 模型可导入', '结构')
def t_models_import(ctx):
    from models.models import AlertEvent, Device, DeviceMonitorLog  # noqa: F401
    from models.maintenance_models import (  # noqa: F401
        WorkOrder, ProblemRecord, KnownError, KnowledgeArticle,
        ServiceCatalog, SLAPolicy, CSIImprovement, EventCorrelationRule,
        CSATSurvey, AvailabilityRecord, ChangeImpactAnalysis, ChangeRequest,
    )
    return '13 个核心模型全部可导入'


@check('数据库表已建立', '结构')
def t_tables_exist(ctx):
    from sqlalchemy import inspect
    from extensions import db

    expected = [
        'alert_events', 'work_orders', 'problem_records', 'known_errors',
        'knowledge_articles', 'service_catalogs', 'sla_policies',
        'csi_improvements', 'event_correlation_rules', 'csat_surveys',
        'availability_records', 'change_impact_analyses', 'device_monitor_logs',
    ]
    existing = set(inspect(db.engine).get_table_names())
    missing = [t for t in expected if t not in existing]
    if missing:
        raise AssertionError(f'缺失表: {missing}')
    return f'{len(expected)} 张表齐备'


@check('ITSM 路由已注册', '结构')
def t_routes(ctx):
    app = ctx['app']
    endpoints = {r.endpoint for r in app.url_map.iter_rules()}

    required = [
        'itsm_adv.event_rules',          # 事件关联规则管理
        'itsm_adv.availability_collect',  # 可用率采集
        'itsm_adv.availability_report',
        'sysjobs.job_list',              # 系统任务页面
        'sysjobs.api_run',               # 手动触发
    ]
    missing = [e for e in required if e not in endpoints]
    if missing:
        raise AssertionError(f'缺失路由: {missing}')

    itsm_count = len([e for e in endpoints if e.startswith('itsm_adv.')])
    return f'itsm_adv 路由 {itsm_count} 个，关键入口齐全'


@check('权限键已播种', '结构')
def t_permissions(ctx):
    from models.config_models import Permission

    required = [
        'csi:view', 'csi:edit', 'event:rules', 'availability:collect',
        'csat:view', 'change:impact', 'report:sla',
        'system:jobs', 'system:jobs:run',
    ]
    codes = {p.code for p in Permission.query.all()}
    if not codes:
        return 'SKIP（该库尚未初始化权限，属全新库正常现象）'
    missing = [c for c in required if c not in codes]
    if missing:
        raise AssertionError(
            f'权限未播种: {missing}\n'
            f'         修复: python sync_permissions.py --execute'
            f'（或重启应用，init_database 会自动播种）'
        )
    return f'{len(required)} 个权限键齐备（库内共 {len(codes)} 个）'


@check('调度任务全部注册', '结构')
def t_scheduler_jobs(ctx):
    """
    注意：调度器由 configure_scheduler() 启动，import app 不会触发。
    因此这里分两种情形：
      - 调度器在跑（例如在真实服务进程内执行本测试）→ 校验实际注册情况
      - 调度器没跑（独立跑脚本的常见情况）→ 静态校验 configure_scheduler 源码中的 job_id
    """
    import re
    from scheduler import SYSTEM_JOB_META, get_scheduler

    critical = ['sla_calculation_job', 'availability_collect_job',
                'work_order_sla_monitor_job', 'check_devices_status_job']

    scheduler = get_scheduler()
    registered = {j.id for j in scheduler.get_jobs()}

    if registered:
        missing = [jid for jid in SYSTEM_JOB_META if jid not in registered]
        critical_missing = [j for j in critical if j not in registered]
        if critical_missing:
            raise AssertionError(f'ITSM 关键调度任务未注册: {critical_missing}')
        if missing:
            return f'运行中，已注册 {len(registered)} 个；非关键任务未注册: {missing}'
        return f'运行中，{len(SYSTEM_JOB_META)} 个内置任务全部注册'

    # 调度器未启动 → 静态校验源码
    path = os.path.join(PROJECT_ROOT, 'scheduler.py')
    src = open(path, encoding='utf-8').read()
    body = src.split('def configure_scheduler')[1].split('\ndef add_job_to_scheduler')[0]
    ids = set(re.findall(r"job_id = '([a-z_0-9]+)'", body))

    critical_missing = [j for j in critical if j not in ids]
    if critical_missing:
        raise AssertionError(f'configure_scheduler 中缺少关键任务: {critical_missing}')

    meta_gap = sorted(ids - set(SYSTEM_JOB_META))
    if meta_gap:
        raise AssertionError(f'这些任务缺少 SYSTEM_JOB_META 元信息（页面上会显示为"其他"）: {meta_gap}')

    return f'调度器未在本进程启动；静态校验通过：源码注册 {len(ids)} 个任务，元信息一一对应'


@check('生产入口会启动调度器', '结构')
def t_wsgi_bootstrap(ctx):
    """
    app.py 的 init_database/init_link_monitor/configure_scheduler 都在
    `if __name__ == '__main__':` 内，用 waitress/gunicorn 指向 app:app 时不会执行，
    定时任务会全部失效。这里校验存在一个正确初始化的 WSGI 入口。
    """
    wsgi_path = os.path.join(PROJECT_ROOT, 'wsgi.py')
    if not os.path.exists(wsgi_path):
        raise AssertionError(
            'wsgi.py 不存在。若生产用 waitress/gunicorn 指向 app:app 部署，'
            'configure_scheduler() 不会被执行，所有定时任务将不运行'
        )
    src = open(wsgi_path, encoding='utf-8').read()
    missing = [f for f in ('configure_scheduler', 'init_database', 'init_link_monitor')
               if f not in src]
    if missing:
        raise AssertionError(f'wsgi.py 未调用: {missing}')
    return 'wsgi.py 已补齐 建表/链路监控/调度器 三项初始化'


@check('设备离线告警已接入关联引擎', '结构')
def t_device_down_wiring(ctx):
    """静态校验 utils/tasks.py 中的接线（该逻辑需真实设备状态跃迁才会触发，无法在此实跑）"""
    src = open(os.path.join(PROJECT_ROOT, 'utils', 'tasks.py'), encoding='utf-8').read()
    checks = {
        '创建离线告警': "title=f'设备离线: {dev.name}'",
        '调用关联引擎': 'process_alert_correlation(db.session, alert)',
        '恢复时关闭告警': "AlertEvent.title.like('设备离线%')",
    }
    missing = [k for k, v in checks.items() if v not in src]
    if missing:
        raise AssertionError(f'接线缺失: {missing}')
    return '离线建单 / 关联调用 / 恢复关闭 三处接线到位'


@check('时间戳 default 为 callable', '结构')
def t_timestamp_default_callable(ctx):
    """防回归：Column 的 default 若写成 datetime.now(...) 会在导入时求值一次，
    同进程内所有新行时间戳相同，直接毁掉 SLA 宕机时长与可用率计算。
    """
    import re
    root = PROJECT_ROOT
    bad_pat = re.compile(
        r'(?:default|onupdate)\s*=\s*datetime\.(?:now\([^)]*\)|utcnow\(\))'
    )
    offenders = []
    for dirpath, dirnames, filenames in os.walk(os.path.join(root, 'models')):
        dirnames[:] = [d for d in dirnames if d != '__pycache__']
        for fn in filenames:
            if not fn.endswith('.py'):
                continue
            path = os.path.join(dirpath, fn)
            with open(path, encoding='utf-8') as f:
                for lineno, line in enumerate(f, 1):
                    if bad_pat.search(line):
                        offenders.append(f'{fn}:{lineno}')
    if offenders:
        raise AssertionError(
            f'{len(offenders)} 处 default/onupdate 写成了常量调用（应传函数引用）: '
            f'{offenders[:6]}{" ..." if len(offenders) > 6 else ""}'
        )

    # 运行时验证：连续两次取默认值应不同
    from models.models import DeviceMonitorLog
    col = DeviceMonitorLog.__table__.c.created_at
    default = col.default
    if default is None or not default.is_callable:
        raise AssertionError('DeviceMonitorLog.created_at 的 default 不是 callable')

    return 'models/ 下无常量时间默认值，created_at default 为 callable'


# ===========================================================================
# B. 功能性检查（写操作，全部回滚）
# ===========================================================================
@check('事件关联引擎：抑制去重', '功能')
def t_correlation_suppress(ctx):
    if ctx['readonly']:
        return 'SKIP（只读模式）'

    from extensions import db
    from models.models import AlertEvent, Device
    from models.maintenance_models import EventCorrelationRule
    from utils.event_correlation import process_alert_correlation

    device = ctx['device']

    # 造一条临时规则：标题含 SMOKE 的同设备告警，60 分钟内抑制去重
    rule = EventCorrelationRule(
        name='__SMOKE_TEST__抑制规则', enabled=True, priority_order=1,
        match_scope='title', match_operator='contains', match_value='SMOKE',
        action='suppress', group_by='device_id', suppression_window_min=60,
    )
    db.session.add(rule)
    db.session.flush()

    now = datetime.utcnow()
    first = AlertEvent(
        device_id=device.id, title='SMOKE 测试告警', message='第一条',
        severity='critical', status='active',
        first_occurred=now, last_occurred=now,
    )
    db.session.add(first)
    db.session.flush()
    process_alert_correlation(db.session, first)
    db.session.flush()

    second = AlertEvent(
        device_id=device.id, title='SMOKE 测试告警', message='第二条(应被抑制)',
        severity='critical', status='active',
        first_occurred=now, last_occurred=now,
    )
    db.session.add(second)
    db.session.flush()
    action, target = process_alert_correlation(db.session, second)
    db.session.flush()

    if not second.suppressed:
        raise AssertionError(f'第二条重复告警未被抑制 (action={action})')
    if first.suppressed:
        raise AssertionError('首条告警被误抑制')
    if (first.occurrence_count or 1) < 2:
        raise AssertionError(f'首条告警计数未累加: {first.occurrence_count}')

    return f'重复告警被抑制，首条计数累加至 {first.occurrence_count}（action={action}）'


@check('事件关联引擎：标题归一化', '功能')
def t_correlation_normalize(ctx):
    if ctx['readonly']:
        return 'SKIP（只读模式）'

    from extensions import db
    from models.models import AlertEvent
    from models.maintenance_models import EventCorrelationRule
    from utils.event_correlation import process_alert_correlation

    device = ctx['device']

    rule = EventCorrelationRule(
        name='__SMOKE_TEST__归一化规则', enabled=True, priority_order=2,
        match_scope='message', match_operator='contains', match_value='NORMALIZE_ME',
        action='group', group_by='device_id', suppression_window_min=0,
        normalize_template='标准化事件 - {host}', auto_ticket=False,
    )
    db.session.add(rule)
    db.session.flush()

    now = datetime.utcnow()
    alert = AlertEvent(
        device_id=device.id, title='原始杂乱标题 xyz-9931',
        message='NORMALIZE_ME payload', severity='warning', status='active',
        first_occurred=now, last_occurred=now,
    )
    db.session.add(alert)
    db.session.flush()
    process_alert_correlation(db.session, alert)
    db.session.flush()

    if '{host}' in (alert.title or ''):
        raise AssertionError('归一化模板占位符未被替换')
    if not alert.title.startswith('标准化事件'):
        raise AssertionError(f'标题未被归一化: {alert.title}')
    if not alert.correlation_group:
        raise AssertionError('分组键未写入')

    return f'标题归一化为「{alert.title}」，分组键={alert.correlation_group}'


@check('SLA：策略匹配与违约判定', '功能')
def t_sla(ctx):
    if ctx['readonly']:
        return 'SKIP（只读模式）'

    from extensions import db
    from models.maintenance_models import WorkOrder, SLAPolicy

    policy = SLAPolicy(
        name='__SMOKE_TEST__SLA策略', category='incident', priority='high',
        response_time=1, resolution_time=4, is_active=True,
    )
    db.session.add(policy)
    db.session.flush()

    ten_hours_ago = datetime.utcnow() - timedelta(hours=10)
    wo = WorkOrder(
        work_order_number='__SMOKE__WO001', title='冒烟测试工单',
        description='用于验证 SLA 计算', work_order_type='incident',
        priority='high', status='in_progress',
        created_at=ten_hours_ago,
        requested_at=ten_hours_ago,  # compute_sla_status 以 requested_at 为基准
    )
    db.session.add(wo)
    db.session.flush()

    wo.apply_sla_policy()
    if wo.sla_resolution_time != 4:
        raise AssertionError(f'SLA 解决时限未匹配到策略: {wo.sla_resolution_time}')

    # 已过 10 小时 > 4 小时时限，应判为违约
    wo.compute_sla_status()
    if wo.sla_status != 'breached':
        raise AssertionError(f'超时 10h(限 4h) 的工单应判违约，实际: {wo.sla_status}')
    if wo.breached_at is None:
        raise AssertionError('违约时间未记录')

    # 未超时工单应为 monitoring
    fresh = WorkOrder(
        work_order_number='__SMOKE__WO002', title='冒烟测试工单-未超时',
        work_order_type='incident', priority='high', status='in_progress',
        created_at=datetime.utcnow(), requested_at=datetime.utcnow(),
    )
    db.session.add(fresh)
    db.session.flush()
    fresh.apply_sla_policy()
    fresh.compute_sla_status()
    if fresh.sla_status != 'monitoring':
        raise AssertionError(f'未超时工单状态异常: {fresh.sla_status}')

    return (f'策略匹配(响应{wo.sla_response_time}h/解决{wo.sla_resolution_time}h)；'
            f'超时工单→breached，未超时工单→monitoring')


@check('KEDB：问题→已知错误→知识库联动', '功能')
def t_kedb(ctx):
    if ctx['readonly']:
        return 'SKIP（只读模式）'

    from extensions import db
    from models.maintenance_models import ProblemRecord, KnownError, KnowledgeArticle

    problem = ProblemRecord(
        problem_number='__SMOKE__PRB001', title='冒烟测试问题',
        description='验证 KEDB 联动', status='investigating', priority='medium',
    )
    db.session.add(problem)
    db.session.flush()

    ke = KnownError(
        ke_number='__SMOKE__KE001', title='冒烟测试已知错误',
        description='验证 KEDB', symptom='服务偶发不可用',
        root_cause='连接池耗尽', workaround='重启服务',
        severity='medium', status='active', linked_problem_id=problem.id,
    )
    db.session.add(ke)
    db.session.flush()

    if ke.linked_problem_id != problem.id:
        raise AssertionError('已知错误与问题记录未关联')

    # 知识库联动字段（author_id 为 NOT NULL，需要一个用户）
    article = KnowledgeArticle(
        title='冒烟测试知识文章', content='内容', category='troubleshooting',
        author_id=ctx['user'].id,
    )
    db.session.add(article)
    db.session.flush()
    ke.knowledge_article_id = article.id
    db.session.flush()

    reloaded = db.session.get(KnownError, ke.id)
    if reloaded.knowledge_article_id != article.id:
        raise AssertionError('已知错误与知识库文章未关联')

    return f'问题 #{problem.id} → 已知错误 #{ke.id} → 知识文章 #{article.id} 三级联动正常'


@check('CSI：改进项生命周期', '功能')
def t_csi(ctx):
    if ctx['readonly']:
        return 'SKIP（只读模式）'

    from extensions import db
    from models.maintenance_models import CSIImprovement

    item = CSIImprovement(
        code='__SMOKE__CSI001', title='__SMOKE_TEST__改进项',
        description='验证 CSI 状态流转',
        source_type='incident', status='proposed', priority='medium',
        target_metric='MTTR', baseline_value=8.0, target_value=4.0,
    )
    db.session.add(item)
    db.session.flush()

    for status in ['approved', 'in_progress', 'completed']:
        item.status = status
        if status == 'completed':
            item.actual_value = 3.5
            item.completed_at = datetime.utcnow()
        db.session.flush()
        if db.session.get(CSIImprovement, item.id).status != status:
            raise AssertionError(f'状态流转失败于 {status}')

    return ('proposed → approved → in_progress → completed 流转正常，'
            f'MTTR 基线 {item.baseline_value}h → 达成 {item.actual_value}h')


@check('可用率采集引擎可执行', '功能')
def t_availability(ctx):
    if ctx['readonly']:
        return 'SKIP（只读模式）'

    from extensions import db
    from utils.availability import collect_availability

    stats = collect_availability(db.session, days=1)
    db.session.flush()

    if not isinstance(stats, dict) or 'written' not in stats:
        raise AssertionError(f'返回结构异常: {stats}')

    return (f"采集执行成功：写入 {stats['written']} 条 "
            f"(设备 {len(stats.get('device_rows', []))} / 服务 {len(stats.get('service_rows', []))})")


@check('变更影响模拟可执行', '功能')
def t_change_impact(ctx):
    if ctx['readonly']:
        return 'SKIP（只读模式）'

    from extensions import db
    from models.maintenance_models import ChangeRequest
    from utils.change_impact import simulate_change_impact

    change = ChangeRequest(
        change_number='__SMOKE__CHG001', title='冒烟测试变更',
        change_type='normal', risk_level='medium',
        estimated_duration_hours=2.0,
    )
    db.session.add(change)
    db.session.flush()

    result = simulate_change_impact(change)
    if not isinstance(result, dict):
        raise AssertionError(f'返回结构异常: {type(result)}')
    for key in ('impacted_device_ids', 'impacted_service_ids', 'cascade_count'):
        if key not in result:
            raise AssertionError(f'返回缺少字段 {key}')

    return (f"模拟成功：影响设备 {len(result['impacted_device_ids'])} 台 / "
            f"服务 {len(result['impacted_service_ids'])} 个 / "
            f"风险分 {result.get('risk_score')}")


# ===========================================================================
# 执行器
# ===========================================================================
def main():
    parser = argparse.ArgumentParser(description='ITSM 高级模块冒烟测试')
    parser.add_argument('--readonly', action='store_true',
                        help='只跑结构性检查，跳过所有写操作')
    args = parser.parse_args()

    print('=' * 72)
    print(' ITSM 高级模块冒烟测试 (事件关联 / SLA / KEDB / CSI)')
    print('=' * 72)

    import app as appmod
    from extensions import db
    from models.models import Device

    flask_app = appmod.app
    print(f"数据库: {flask_app.config.get('SQLALCHEMY_DATABASE_URI', '?').split('@')[-1]}")
    print(f"模式  : {'只读' if args.readonly else '读写（结束时回滚）'}")
    print('-' * 72)

    passed = failed = skipped = 0

    with flask_app.app_context():
        # 功能检查需要一台设备作为载体；库里没有就临时造一台（结束时随事务回滚）
        device = None
        if not args.readonly:
            device = Device.query.first()
            if device is None:
                try:
                    device = Device(name='__SMOKE_TEST__设备', ip_address='127.0.0.253')
                    db.session.add(device)
                    db.session.flush()
                    print('  (库中无设备，已创建临时测试设备，结束时回滚)')
                except Exception as e:
                    db.session.rollback()
                    print(f'! 无法创建临时设备({e})，功能性检查将被跳过')
                    args.readonly = True
                    device = None

        # 部分模型有 NOT NULL 外键指向用户，功能检查需要一个用户
        user = None
        if not args.readonly:
            from models.models import User
            user = User.query.first()
            if user is None:
                try:
                    user = User(username='__smoke_test__', email='smoke@test.local')
                    if hasattr(user, 'set_password'):
                        user.set_password('smoke-test-only')
                    db.session.add(user)
                    db.session.flush()
                    print('  (库中无用户，已创建临时测试用户，结束时回滚)')
                except Exception as e:
                    db.session.rollback()
                    print(f'! 无法创建临时用户({e})，部分功能检查可能失败')

        ctx = {'app': flask_app, 'readonly': args.readonly,
               'device': device, 'user': user}

        # 每个用例包在 SAVEPOINT 中，单个失败不会污染 session、后续用例照常执行
        try:
            for fn in RESULTS:
                name = fn._smoke_name
                cat = fn._smoke_category
                sp = None
                try:
                    if fn._smoke_category == '功能' and not args.readonly:
                        sp = db.session.begin_nested()
                    detail = fn(ctx)
                    if sp is not None and sp.is_active:
                        sp.rollback()   # 用例数据即刻回退，互不干扰
                    if detail and str(detail).startswith('SKIP'):
                        print(f'  [SKIP] [{cat}] {name}  — {detail}')
                        skipped += 1
                    else:
                        print(f'  [ OK ] [{cat}] {name}  — {detail}')
                        passed += 1
                except Exception as e:
                    try:
                        if sp is not None and sp.is_active:
                            sp.rollback()
                    except Exception:
                        pass
                    print(f'  [FAIL] [{cat}] {name}')
                    print(f'         {type(e).__name__}: {str(e).splitlines()[0]}')
                    if os.environ.get('SMOKE_VERBOSE'):
                        traceback.print_exc()
                    failed += 1
        finally:
            # 无论成败一律回滚，绝不落库
            try:
                db.session.rollback()
                db.session.remove()
                print('-' * 72)
                print('已回滚所有测试数据（数据库未被修改）')
            except Exception as e:
                print(f'! 回滚异常: {e}')

    print('=' * 72)
    print(f' 结果: 通过 {passed} / 失败 {failed} / 跳过 {skipped}')
    print('=' * 72)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
