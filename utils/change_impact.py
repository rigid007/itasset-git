"""变更影响模拟(先算影响再实施)

基于变更直接受影响设备 + CMDB 依赖关系(CIDependency)做 BFS 向上游传播，
计算级联受影响设备、受影响服务目录(经 ServiceCatalogDevice 映射)、
估算受影响用户数与风险评分，并持久化为 ChangeImpactAnalysis 快照。
"""
import json
from datetime import datetime


def _resolve_direct_devices(change):
    """变更直接关联设备：ChangeAffectedDevice 链接 + affected_devices(JSON)。"""
    ids = set()
    for link in change.affected_device_links.all():
        if link.device_id:
            ids.add(link.device_id)
    raw = getattr(change, 'affected_devices', None)
    if raw:
        try:
            data = json.loads(raw)
            for d in data:
                if isinstance(d, dict) and d.get('id'):
                    ids.add(int(d['id']))
                elif isinstance(d, int):
                    ids.add(d)
                elif isinstance(d, str) and d.isdigit():
                    ids.add(int(d))
        except Exception:
            pass
    return ids


def _propagate(direct_ids):
    """沿 CIDependency 向上游传播：target 故障 -> 所有 source(上游依赖方)受影响。"""
    from models.maintenance_models import CIDependency
    edges = CIDependency.query.all()
    rev_adj = {}
    for e in edges:
        rev_adj.setdefault(e.target_id, set()).add(e.source_id)
    impacted = set(direct_ids)
    stack = list(direct_ids)
    while stack:
        cur = stack.pop()
        for src_id in rev_adj.get(cur, []):
            if src_id not in impacted:
                impacted.add(src_id)
                stack.append(src_id)
    return impacted


def _impacted_services(impacted_device_ids):
    from models.maintenance_models import service_catalog_devices
    from sqlalchemy import select
    from extensions import db
    if not impacted_device_ids:
        return []
    stmt = select(service_catalog_devices.c.service_catalog_id).where(
        service_catalog_devices.c.device_id.in_(list(impacted_device_ids))
    )
    res = db.session.execute(stmt).fetchall()
    return sorted({r[0] for r in res})


def _estimate_users(impacted_device_ids, impacted_service_ids):
    """粗略估算受影响用户数(可调参数)。"""
    return max(len(impacted_device_ids) * 5, len(impacted_service_ids) * 20)


def simulate_change_impact(change):
    """执行影响模拟，返回结果 dict。"""
    direct = _resolve_direct_devices(change)
    impacted = _propagate(direct)
    services = _impacted_services(impacted)
    users = _estimate_users(impacted, services)

    risk_rank = {'low': 1, 'medium': 2, 'high': 3}
    base = len(impacted) * 1.0 + len(services) * 2.0
    risk_lvl = getattr(change, 'risk_level', None) or 'medium'
    mult = risk_rank.get(risk_lvl, 2)
    risk_score = round(base * (0.6 + 0.2 * mult), 1)
    risk_level = 'high' if risk_score >= 20 else ('medium' if risk_score >= 8 else 'low')

    downtime = (getattr(change, 'estimated_duration_hours', None) or 1) * 60.0
    return {
        'direct_device_ids': sorted(direct),
        'impacted_device_ids': sorted(impacted),
        'impacted_service_ids': services,
        'cascade_count': len(impacted) - len(direct),
        'affected_user_count': users,
        'downtime_estimate_min': round(downtime, 1),
        'risk_score': risk_score,
        'risk_level': risk_level,
    }


def persist_impact_analysis(change, result, session=None):
    """将模拟结果持久化为 ChangeImpactAnalysis 快照。"""
    from models.maintenance_models import ChangeImpactAnalysis
    from extensions import db
    s = session or db.session
    ana = ChangeImpactAnalysis(
        change_id=change.id,
        direct_device_ids=json.dumps(result['direct_device_ids']),
        impacted_device_ids=json.dumps(result['impacted_device_ids']),
        impacted_service_ids=json.dumps(result['impacted_service_ids']),
        affected_user_count=result['affected_user_count'],
        downtime_estimate_min=result['downtime_estimate_min'],
        risk_score=result['risk_score'],
        risk_level=result['risk_level'],
        summary=(f"直接影响设备 {len(result['direct_device_ids'])} 台，"
                 f"级联影响 {result['cascade_count']} 台，"
                 f"涉及服务 {len(result['impacted_service_ids'])} 项，"
                 f"估算影响用户 {result['affected_user_count']} 人。"),
    )
    s.add(ana)
    s.flush()
    return ana


def run_and_persist(change, session=None):
    """便捷函数：模拟并落库，返回 (result, analysis)。"""
    result = simulate_change_impact(change)
    ana = persist_impact_analysis(change, result, session)
    return result, ana
