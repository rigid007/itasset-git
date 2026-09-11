# -*- coding: utf-8 -*-
"""NetFlow dashboard & management blueprint (权限 + 审计接入).

Routes:
  /netflow/                     dashboard page (netflow:view)
  /netflow/api/probes           list / create / update / delete collectors
                               (view for GET, edit for mutations + audit)
  /netflow/api/status|stats|records|apps|protocols   (netflow:view)
"""
import ipaddress
import logging
import threading
import time
from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, jsonify

from extensions import db
from models.netflow_models import (
    NetFlowProbe, NetFlowRecord, NetFlowApp, NetFlowProtocol, NetFlowAs,
    NetFlowAgg,
)
from services.netflow_service import (
    get_status, sync_probe, start_collector, dscp_name,
    get_app_map, app_name_for, load_ip_device_map,
)
from utils.permission import permission_required
from utils.audit import log_audit

logger = logging.getLogger(__name__)

_stats_cache = {}
_stats_cache_lock = threading.Lock()
_STATS_CACHE_TTL_SEC = 30

netflow_bp = Blueprint('netflow', __name__, url_prefix='/netflow')


@netflow_bp.route('/')
@permission_required('netflow:view')
def index():
    return render_template('netflow/index.html')


# ------------------------------------------------------------------ probes
@netflow_bp.route('/api/probes')
@permission_required('netflow:view')
def list_probes():
    probes = NetFlowProbe.query.order_by(NetFlowProbe.name).all()
    status = {s['id']: s for s in get_status()}
    out = []
    for p in probes:
        d = p.to_dict()
        d['running'] = bool(status.get(p.id, {}).get('running'))
        d['live_packets'] = status.get(p.id, {}).get('packets', 0)
        d['live_flows'] = status.get(p.id, {}).get('flows', 0)
        out.append(d)
    return jsonify(out)


@netflow_bp.route('/api/probes', methods=['POST'])
@permission_required('netflow:edit')
def create_probe():
    d = request.get_json(force=True) or {}
    probe = NetFlowProbe(
        name=(d.get('name') or '').strip(),
        listen_ip=d.get('listen_ip', '0.0.0.0'),
        port=int(d.get('port', 2055)),
        version=d.get('version', 'both'),
        description=d.get('description'),
        enabled=bool(d.get('enabled', True)),
    )
    if not probe.name:
        return jsonify({'error': 'name is required'}), 400
    db.session.add(probe)
    db.session.commit()
    start_collector(probe)
    log_audit('create', 'netflow_probe', probe.id,
              '创建 NetFlow 采集器 %s (%s:%s, %s)' % (
                  probe.name, probe.listen_ip, probe.port, probe.version),
              details={'name': probe.name, 'port': probe.port,
                       'version': probe.version})
    return jsonify(probe.to_dict()), 201


@netflow_bp.route('/api/probes/<int:pid>', methods=['PUT', 'PATCH'])
@permission_required('netflow:edit')
def update_probe(pid):
    probe = NetFlowProbe.query.get_or_404(pid)
    d = request.get_json(force=True) or {}
    changes = {}
    for field in ('name', 'listen_ip', 'description'):
        if field in d and getattr(probe, field) != d[field]:
            changes[field] = {'from': getattr(probe, field), 'to': d[field]}
            setattr(probe, field, d[field])
    if 'port' in d and probe.port != int(d['port']):
        changes['port'] = {'from': probe.port, 'to': int(d['port'])}
        probe.port = int(d['port'])
    if 'version' in d and probe.version != d['version']:
        changes['version'] = {'from': probe.version, 'to': d['version']}
        probe.version = d['version']
    if 'enabled' in d and probe.enabled != bool(d['enabled']):
        changes['enabled'] = {'from': probe.enabled, 'to': bool(d['enabled'])}
        probe.enabled = bool(d['enabled'])
    db.session.commit()
    sync_probe(probe.id)
    if changes:
        log_audit('update', 'netflow_probe', probe.id,
                  '更新 NetFlow 采集器 %s' % probe.name, changes=changes)
    return jsonify(probe.to_dict())


@netflow_bp.route('/api/probes/<int:pid>', methods=['DELETE'])
@permission_required('netflow:edit')
def delete_probe(pid):
    probe = NetFlowProbe.query.get_or_404(pid)
    name = probe.name
    db.session.delete(probe)
    db.session.commit()
    sync_probe(pid)   # stops listener if running
    log_audit('delete', 'netflow_probe', pid,
              '删除 NetFlow 采集器 %s' % name, status='success')
    return jsonify({'ok': True})


@netflow_bp.route('/api/probes/<int:pid>/restart', methods=['POST'])
@permission_required('netflow:edit')
def restart_probe(pid):
    probe = NetFlowProbe.query.get_or_404(pid)
    sync_probe(probe.id)
    log_audit('execute', 'netflow_probe', pid,
              '重启 NetFlow 采集器 %s' % probe.name)
    return jsonify(probe.to_dict())


# ------------------------------------------------------------------ status / stats
@netflow_bp.route('/api/status')
@permission_required('netflow:view')
def status():
    return jsonify(get_status())


@netflow_bp.route('/api/stats')
@permission_required('netflow:view')
def stats():
    """Aggregate stats over a lookback window (default 15 min)."""
    minutes = request.args.get('minutes', 15, type=int)
    probe_id = request.args.get('probe', type=int)
    cache_key = (minutes, probe_id)
    _now_ts = time.time()
    with _stats_cache_lock:
        hit = _stats_cache.get(cache_key)
        if hit and (_now_ts - hit['ts']) < _STATS_CACHE_TTL_SEC:
            return jsonify(hit['data'])

    since = datetime.utcnow() - timedelta(minutes=max(1, minutes))
    if probe_id is not None:
        base = NetFlowRecord.probe_id == probe_id
    else:
        base = None

    def _scoped(q):
        q = q.filter(NetFlowRecord.received_at >= since)
        if base is not None:
            q = q.filter(base)
        return q

    top_sources = _top('src_ip', since, 10, probe_id)
    top_destinations = _top('dst_ip', since, 10, probe_id)
    top_protocols = _top('protocol', since, 8, probe_id)
    top_ports = _top('dst_port', since, 10, probe_id)
    device_map = load_ip_device_map()

    def _decorate(row):
        d = _r(row)
        info = device_map.get(row.k)
        if info:
            d['label'] = info[1]
        return d

    top_sources = [_decorate(r) for r in top_sources]
    top_destinations = [_decorate(r) for r in top_destinations]
    total = _scoped(db.session.query(
        db.func.sum(NetFlowRecord.octets).label('octets'),
        db.func.sum(NetFlowRecord.packets).label('packets'),
        db.func.count(NetFlowRecord.id).label('flows'),
    )).one()

    # 分钟级分桶在 SQL 侧完成，避免把窗口内全部记录拉到 Python 逐条聚合
    trend_rows = (_scoped(db.session.query(
                    _minute_bucket(NetFlowRecord.received_at).label('minute'),
                    db.func.sum(NetFlowRecord.octets).label('octets'),
                    db.func.count(NetFlowRecord.id).label('flows'),
                  ).group_by('minute').order_by('minute'))).all()
    trend = [{'t': m, 'octets': o, 'flows': f}
             for m, o, f in trend_rows]

    payload = {
        'window_minutes': minutes,
        'total': {
            'octets': total.octets or 0,
            'packets': total.packets or 0,
            'flows': total.flows or 0,
        },
        'top_sources': [_r(r) for r in top_sources],
        'top_destinations': [_r(r) for r in top_destinations],
        'top_protocols': [_r(r) for r in top_protocols],
        'top_ports': [_r(r) for r in top_ports],
        'trend': trend,
    }
    with _stats_cache_lock:
        _stats_cache[cache_key] = {'ts': _now_ts, 'data': payload}
    return jsonify(payload)


@netflow_bp.route('/api/records')
@permission_required('netflow:view')
def records():
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 50, type=int), 200)
    q = NetFlowRecord.query
    src = request.args.get('src')
    dst = request.args.get('dst')
    proto = request.args.get('protocol', type=int)
    probe_id = request.args.get('probe', type=int)
    if src:
        q = q.filter(NetFlowRecord.src_ip == src)
    if dst:
        q = q.filter(NetFlowRecord.dst_ip == dst)
    if proto is not None:
        q = q.filter(NetFlowRecord.protocol == proto)
    if probe_id is not None:
        q = q.filter(NetFlowRecord.probe_id == probe_id)
    rows = q.order_by(NetFlowRecord.received_at.desc()) \
            .offset((page - 1) * per_page).limit(per_page).all()
    total = q.count()
    return jsonify({'items': [r.to_dict() for r in rows],
                    'page': page, 'per_page': per_page, 'total': total})


# ------------------------------------------------------------------ dictionaries
@netflow_bp.route('/api/apps')
@permission_required('netflow:view')
def apps():
    return jsonify([a.to_dict() for a in
                    NetFlowApp.query.order_by(NetFlowApp.port).limit(500).all()])


@netflow_bp.route('/api/protocols')
@permission_required('netflow:view')
def protocols():
    return jsonify([p.to_dict() for p in NetFlowProtocol.query.all()])



@netflow_bp.route('/api/top_apps')
@permission_required('netflow:view')
def top_apps():
    """Top applications over a window (uses 5m pre-aggregation when available)."""
    minutes = request.args.get('minutes', 60, type=int)
    probe_id = request.args.get('probe', type=int)
    since = datetime.utcnow() - timedelta(minutes=max(1, minutes))
    q = (db.session.query(
                NetFlowAgg.app_name,
                db.func.sum(NetFlowAgg.octets).label('octets'),
                db.func.sum(NetFlowAgg.packets).label('packets'),
                db.func.sum(NetFlowAgg.flows).label('flows'),
            ).filter(NetFlowAgg.period == '5m',
                     NetFlowAgg.bucket >= since))
    if probe_id is not None:
        q = q.filter(NetFlowAgg.probe_id == probe_id)
    rows = (q.group_by(NetFlowAgg.app_name)
            .order_by(db.func.sum(NetFlowAgg.octets).desc())
            .limit(10).all())
    if rows:
        items = [{'key': r.app_name or '未知', 'octets': r.octets or 0,
                  'packets': r.packets or 0, 'flows': r.flows or 0}
                 for r in rows]
    else:
        # Fallback: aggregate raw records by (dst_port, protocol)
        raw_q = (db.session.query(
                    NetFlowRecord.dst_port,
                    NetFlowRecord.protocol,
                    db.func.sum(NetFlowRecord.octets).label('octets'),
                    db.func.sum(NetFlowRecord.packets).label('packets'),
                    db.func.count(NetFlowRecord.id).label('flows'),
                ).filter(NetFlowRecord.received_at >= since))
        if probe_id is not None:
            raw_q = raw_q.filter(NetFlowRecord.probe_id == probe_id)
        raw = (raw_q.group_by(NetFlowRecord.dst_port, NetFlowRecord.protocol)
               .order_by(db.func.sum(NetFlowRecord.octets).desc())
               .limit(10).all())
        app_map = get_app_map()
        items = []
        for sport, proto, octets, packets, flows in raw:
            name = app_name_for(sport, proto, app_map) or ('端口-%s' % sport)
            items.append({'key': name, 'octets': octets or 0,
                          'packets': packets or 0, 'flows': flows or 0})
    return jsonify({'minutes': minutes, 'items': items})


# ------------------------------------------------------------------ external subnet sessions
@netflow_bp.route('/api/sessions')
@permission_required('netflow:view')
def external_sessions():
    """Top cross-subnet sessions (对外网段会话). dst subnet external => flagged."""
    minutes = request.args.get('minutes', 60, type=int)
    top = min(request.args.get('top', 10, type=int), 50)
    since = datetime.utcnow() - timedelta(minutes=max(1, minutes))

    internal = _internal_subnets()
    as_map = {}
    for a in NetFlowAs.query.all():
        as_map[a.asn] = (a.name, a.region)

    # 先按 IP 对在 SQL 侧聚合成唯一组合，再在 Python 内归并到 /24 网段，
    # 避免把窗口内每条流记录都拉到内存（流量大时数量级差异巨大）
    rows = (db.session.query(
                NetFlowRecord.src_ip, NetFlowRecord.dst_ip,
                NetFlowRecord.src_as, NetFlowRecord.dst_as,
                db.func.sum(NetFlowRecord.octets).label('octets'),
                db.func.sum(NetFlowRecord.packets).label('packets'),
                db.func.count(NetFlowRecord.id).label('flows'),
            ).filter(NetFlowRecord.received_at >= since)
            .group_by(NetFlowRecord.src_ip, NetFlowRecord.dst_ip,
                      NetFlowRecord.src_as, NetFlowRecord.dst_as)
            .all())

    def _subnet(ip):
        if not ip or ':' in ip:
            return None
        p = ip.split('.')
        return '.'.join(p[:3]) + '.0/24'

    def _region(asn):
        if not asn:
            return None
        return as_map.get(asn, (None, None))[1]

    agg = {}
    for src_ip, dst_ip, src_as, dst_as, octets, packets, flows in rows:
        s = _subnet(src_ip)
        d = _subnet(dst_ip)
        if not s or not d or s == d:
            continue  # 同网段会话不计入“对外”
        key = (s, d)
        v = agg.setdefault(key, [0, 0, 0, None, None])
        v[0] += octets or 0
        v[1] += packets or 0
        v[2] += flows or 0
        v[3] = _region(src_as)
        v[4] = _region(dst_as)

    device_map = load_ip_device_map()
    items = []
    for (s, d), (octets, packets, flows, sr, dr) in agg.items():
        # device names are best-effort; session rows are subnet-level
        src_dev = device_map.get(s) if s else None
        dst_dev = device_map.get(d) if d else None
        items.append({
            'src_subnet': s, 'dst_subnet': d,
            'src_region': sr, 'dst_region': dr,
            'src_device': src_dev[1] if src_dev else None,
            'dst_device': dst_dev[1] if dst_dev else None,
            'octets': octets, 'packets': packets, 'flows': flows,
            'external': not _in_subnets(d, internal),
        })
    items.sort(key=lambda x: x['octets'], reverse=True)
    return jsonify({'minutes': minutes, 'items': items[:top]})


def _internal_subnets():
    """Parse NETFLOW_INTERNAL_SUBNETS (comma separated CIDRs) from config."""
    from flask import current_app
    try:
        raw = current_app.config.get('NETFLOW_INTERNAL_SUBNETS', '')
    except RuntimeError:
        raw = ''
    out = []
    for cidr in (raw or '').split(','):
        cidr = cidr.strip()
        if not cidr:
            continue
        try:
            out.append(ipaddress.ip_network(cidr, strict=False))
        except ValueError:
            logger.warning('Invalid NETFLOW_INTERNAL_SUBNETS entry ignored: %r', cidr)
    return out


def _in_subnets(subnet, internal):
    if not internal or not subnet:
        return False
    try:
        net = ipaddress.ip_network(subnet, strict=False)
    except ValueError:
        return False
    return any(isinstance(net, type(internal_net)) and net.subnet_of(internal_net)
                   for internal_net in internal)


# ------------------------------------------------------------------ helpers
def _minute_bucket(col):
    """Dialect-aware minute bucket expression for trend aggregation."""
    try:
        if db.engine.dialect.name == 'mysql':
            return db.func.date_format(col, '%Y-%m-%d %H:%i')
    except Exception:
        pass
    return db.func.strftime('%Y-%m-%d %H:%M', col)


def _top(column, since, limit, probe_id=None):
    col = getattr(NetFlowRecord, column)
    q = (db.session.query(col.label('k'),
                          db.func.sum(NetFlowRecord.octets).label('octets'),
                          db.func.sum(NetFlowRecord.packets).label('packets'),
                          db.func.count(NetFlowRecord.id).label('flows'))
         .filter(NetFlowRecord.received_at >= since))
    if probe_id is not None:
        q = q.filter(NetFlowRecord.probe_id == probe_id)
    return (q.group_by(col).order_by(db.func.sum(NetFlowRecord.octets).desc())
            .limit(limit).all())


def _r(row):
    return {'key': row.k, 'octets': row.octets or 0,
            'packets': row.packets or 0, 'flows': row.flows or 0}


# ------------------------------------------------------------------ report (AS / region / DSCP)
@netflow_bp.route('/report')
@permission_required('netflow:view')
def report():
    return render_template('netflow/report.html')


@netflow_bp.route('/api/report')
@permission_required('netflow:view')
def report_data():
    """Aggregate by ASN / subnet-region / DSCP over a window (default 60 min)."""
    group = request.args.get('group', 'as')
    minutes = request.args.get('minutes', 60, type=int)
    since = datetime.utcnow() - timedelta(minutes=max(1, minutes))

    # 先按 (IP对 + AS + ToS) 在 SQL 侧聚合成唯一组合，Python 侧只做语义分组，
    # 避免把窗口内每条流记录都拉到内存
    rows = (db.session.query(
                NetFlowRecord.src_ip, NetFlowRecord.dst_ip,
                NetFlowRecord.src_as, NetFlowRecord.dst_as,
                NetFlowRecord.tos,
                db.func.sum(NetFlowRecord.octets).label('octets'),
                db.func.sum(NetFlowRecord.packets).label('packets'),
                db.func.count(NetFlowRecord.id).label('flows'),
            ).filter(NetFlowRecord.received_at >= since)
            .group_by(NetFlowRecord.src_ip, NetFlowRecord.dst_ip,
                      NetFlowRecord.src_as, NetFlowRecord.dst_as,
                      NetFlowRecord.tos)
            .all())

    # ASN -> (name, region)
    as_map = {}
    for a in NetFlowAs.query.all():
        as_map[a.asn] = (a.name, a.region)

    def _as_info(asn):
        if not asn:
            return ('未知AS', None)
        name, region = as_map.get(asn, ('AS%d' % asn, None))
        return (name, region)

    out = {}
    for src_ip, dst_ip, src_as, dst_as, tos, octets, packets, flows in rows:
        key = None
        if group == 'as':
            for asn in (src_as, dst_as):
                if not asn:
                    continue
                name, reg = _as_info(asn)
                key = ('AS%d' % asn, name, reg)
                _accum(out, key, octets, packets, flows)
        elif group == 'region':
            for ip in (src_ip, dst_ip):
                if not ip or ':' in ip:
                    continue
                parts = ip.split('.')
                prefix = '.'.join(parts[:3]) + '.0/24'
                _accum(out, (prefix, prefix, None), octets, packets, flows)
        elif group == 'asregion':
            # 区域(国家/运营商)来自 AS 字典的 region 字段
            for asn in (src_as, dst_as):
                if not asn:
                    continue
                _name, reg = _as_info(asn)
                reg = reg or '未知'
                key = ('region-%s' % reg, reg, None)
                _accum(out, key, octets, packets, flows)
        elif group == 'dscp':
            dscp = dscp_name(tos)
            key = ('dscp-%s' % (tos or 0), dscp or ('DSCP-%s' % tos), None)
            _accum(out, key, octets, packets, flows)
        else:
            return jsonify({'error': 'invalid group, use as|region|asregion|dscp'}), 400

    items = [{'key': k[0], 'label': k[1], 'region': k[2],
              'octets': v[0], 'packets': v[1], 'flows': v[2]}
             for k, v in out.items()]
    items.sort(key=lambda x: x['octets'], reverse=True)
    return jsonify({'group': group, 'minutes': minutes,
                    'total': len(rows), 'items': items[:200]})


def _accum(out, key, octets, packets, flows=1):
    v = out.setdefault(key, [0, 0, 0])
    v[0] += octets or 0
    v[1] += packets or 0
    v[2] += flows or 0
