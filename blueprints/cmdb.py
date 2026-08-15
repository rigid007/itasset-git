"""CMDB 依赖关系与影响分析

提供：
- 依赖关系图谱（有向图）的查看与维护
- 影响分析：给定一个 CI 故障，向上游(它依赖什么) / 下游(谁依赖它) 做 BFS 传播，
  支撑 ITIL「配置管理 + 事件/问题影响分析」的闭环。
"""
from flask import (
    Blueprint, request, jsonify, flash, redirect, url_for, render_template, abort
)
from flask_login import login_required, current_user

from utils.permission import permission_required
from extensions import db
from models.models import Device
from models.maintenance_models import CIDependency

cmdb_bp = Blueprint('cmdb', __name__, url_prefix='/cmdb')


# ---------------------------------------------------------------------------
# 影响分析核心：有向图 BFS
# ---------------------------------------------------------------------------
def _bfs(device_id, direction):
    """direction='downstream' 表示“谁依赖它”(受影响的下游)；
       direction='upstream'   表示“它依赖谁”(上游依赖)。
    返回 (ordered_ids, edges) —— ordered_ids 为 BFS 遍历顺序(不含起点)，edges 为传播边。
    """
    visited = {device_id}
    ordered = []
    edges = []
    frontier = [device_id]
    while frontier:
        nxt = []
        for cur in frontier:
            if direction == 'downstream':
                rels = CIDependency.query.filter_by(target_id=cur).all()
                for r in rels:
                    edges.append({'from': r.source_id, 'to': r.target_id,
                                  'type': r.dependency_type, 'criticality': r.criticality})
                    if r.source_id not in visited:
                        visited.add(r.source_id)
                        ordered.append(r.source_id)
                        nxt.append(r.source_id)
            else:  # upstream
                rels = CIDependency.query.filter_by(source_id=cur).all()
                for r in rels:
                    edges.append({'from': r.source_id, 'to': r.target_id,
                                  'type': r.dependency_type, 'criticality': r.criticality})
                    if r.target_id not in visited:
                        visited.add(r.target_id)
                        ordered.append(r.target_id)
                        nxt.append(r.target_id)
        frontier = nxt
    return ordered, edges


def compute_impact(device_id):
    downstream_ids, down_edges = _bfs(device_id, 'downstream')
    upstream_ids, up_edges = _bfs(device_id, 'upstream')

    def node_info(did):
        d = Device.query.get(did)
        if not d:
            return None
        return {
            'id': d.id, 'name': d.name, 'type': d.device_type or 'unknown',
            'ip': d.ip_address or '', 'status': d.status or 'unknown',
        }

    return {
        'origin': node_info(device_id),
        'downstream': [node_info(i) for i in downstream_ids if node_info(i)],
        'upstream': [node_info(i) for i in upstream_ids if node_info(i)],
        'downstream_count': len(downstream_ids),
        'upstream_count': len(upstream_ids),
        'graph': {
            'nodes': [node_info(device_id)] +
                     [node_info(i) for i in downstream_ids if node_info(i)] +
                     [node_info(i) for i in upstream_ids if node_info(i)],
            'down_edges': down_edges,
            'up_edges': up_edges,
        },
    }


# ---------------------------------------------------------------------------
# 页面与 API
# ---------------------------------------------------------------------------
@cmdb_bp.route('/dependencies')
@login_required
@permission_required('cmdb:view')
def dependencies():
    devices = Device.query.filter_by(is_decommissioned=False).order_by(Device.name).all()
    deps = CIDependency.query.order_by(CIDependency.criticality.desc()).all()
    return render_template('cmdb/dependencies.html',
                           devices=devices, deps=deps,
                           dep_types=CIDependency.DEPENDENCY_TYPES)


@cmdb_bp.route('/api/graph')
@login_required
@permission_required('cmdb:view')
def api_graph():
    deps = CIDependency.query.all()
    device_ids = set()
    for d in deps:
        device_ids.add(d.source_id)
        device_ids.add(d.target_id)
    nodes = []
    for did in device_ids:
        dev = Device.query.get(did)
        if dev:
            nodes.append({
                'id': dev.id,
                'label': dev.name,
                'group': dev.device_type or 'unknown',
                'title': f"{dev.name}<br>IP: {dev.ip_address or '-'}<br>状态: {dev.status or '-'}",
            })
    edges = [{
        'from': d.source_id,
        'to': d.target_id,
        'label': CIDependency.DEPENDENCY_TYPES.get(d.dependency_type, d.dependency_type),
        'criticality': d.criticality,
        'arrows': 'to',
    } for d in deps]
    return jsonify({'nodes': nodes, 'edges': edges})


@cmdb_bp.route('/dependency/add', methods=['POST'])
@login_required
@permission_required('cmdb:edit')
def dependency_add():
    source_id = request.form.get('source_id', type=int)
    target_id = request.form.get('target_id', type=int)
    dependency_type = request.form.get('dependency_type') or 'depends_on'
    criticality = request.form.get('criticality') or 'medium'
    description = request.form.get('description', '').strip()

    if not source_id or not target_id:
        return jsonify({'success': False, 'message': '请选择源与目标设备'}), 400
    if source_id == target_id:
        return jsonify({'success': False, 'message': '源设备与目标设备不能相同'}), 400
    if dependency_type not in CIDependency.DEPENDENCY_TYPES:
        return jsonify({'success': False, 'message': '依赖类型非法'}), 400

    existing = CIDependency.query.filter_by(
        source_id=source_id, target_id=target_id, dependency_type=dependency_type).first()
    if existing:
        return jsonify({'success': False, 'message': '该依赖关系已存在'}), 409

    dep = CIDependency(
        source_id=source_id, target_id=target_id,
        dependency_type=dependency_type, criticality=criticality,
        description=description, created_by=current_user.username)
    db.session.add(dep)
    db.session.commit()
    try:
        from utils.audit import log_audit
        log_audit('create', 'ci_dependency', dep.id,
                  f"添加依赖: {dep.source.name} {dependency_type} {dep.target.name}",
                  user_id=current_user.id)
    except Exception:
        pass
    return jsonify({'success': True, 'message': '依赖关系已添加', 'dependency': dep.to_dict()})


@cmdb_bp.route('/dependency/<int:dep_id>/delete', methods=['POST'])
@login_required
@permission_required('cmdb:edit')
def dependency_delete(dep_id):
    dep = CIDependency.query.get_or_404(dep_id)
    db.session.delete(dep)
    db.session.commit()
    try:
        from utils.audit import log_audit
        log_audit('delete', 'ci_dependency', dep_id, f"删除依赖: id={dep_id}",
                  user_id=current_user.id)
    except Exception:
        pass
    return jsonify({'success': True, 'message': '依赖关系已删除'})


@cmdb_bp.route('/api/impact')
@login_required
@permission_required('cmdb:view')
def api_impact():
    device_id = request.args.get('device_id', type=int)
    if not device_id:
        return jsonify({'success': False, 'message': '缺少 device_id'}), 400
    device = Device.query.get(device_id)
    if not device:
        return jsonify({'success': False, 'message': '设备不存在'}), 404
    return jsonify({'success': True, **compute_impact(device_id)})
