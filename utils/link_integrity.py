# utils/link_integrity.py
"""连接（ConnectionPath）数据质量治理：状态推导、端口冲突、端口名归一。

背景（现网 /topology/connection_relations 反馈的三大问题）：
1. 状态不准：link_status 实际由"本次 LLDP 扫描是否再见"决定（_mark_stale_lldp_links
   未再见即置 down），与接口真实 up/down 无关，导致端口 up/up 的链路显示"断开"。
   → derive_link_status() 按两端接口 admin/oper 状态推导，扫描可见性只降置信度。
2. 端口冲突：同一设备的同一端口出现在多条连接里（一个物理口两个对端）。
   → find_port_conflicts()/resolve_port_conflicts()，写入侧亦有护栏。
3. 端口名是 MAC：未识别设备被按 MAC 建接口，导致"端口"列显示 00:11:22:33:44:55。
   → looks_like_mac() + normalize_mac_ports()，MAC 归一为 'unknown' 并把原值写入 description。

约定：
- 所有变更函数默认 dry-run（execute=False），返回计划，落库需显式 execute=True。
- 状态取值沿用页面口径：active / down / unknown。
"""
import re
from datetime import datetime, timezone

_MAC_RE = re.compile(r'^(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}$', re.IGNORECASE)
_UNKNOWN_PORTS = {'', 'unknown', 'n/a', 'na', 'none', '-', '?'}
_UP = {'up', '1'}
_DOWN = {'down', '2', 'notpresent', 'lowerlayerdown', 'testing'}


def looks_like_mac(value):
    """端口名是否其实是 MAC（未识别设备的占位接口名）。"""
    v = (value or '').strip()
    return bool(v) and bool(_MAC_RE.match(v))


def is_unknown_port(value):
    v = (value or '').strip().lower()
    return v in _UNKNOWN_PORTS or looks_like_mac(v)


def _iface_state(iface):
    """单个接口的通电状态：True=up / False=down / None=未知（无采集数据）。"""
    if iface is None:
        return None
    admin = (getattr(iface, 'admin_status', '') or '').strip().lower()
    oper = (getattr(iface, 'oper_status', '') or '').strip().lower()
    if admin in _DOWN:
        return False
    if oper in _DOWN:
        return False
    if oper in _UP:
        return True
    # 只有 admin=up 但没有 oper → 未采集到真实状态
    if admin in _UP and oper not in _DOWN:
        return None
    return None


def derive_link_status(source_iface, target_iface):
    """按两端接口状态推导链路状态。

    任一端明确 down → down；两端都 up → active；
    仅一端有数据且为 up → active（另一端未采集，保守按在网处理）；
    两端都无数据 → unknown。
    """
    s = _iface_state(source_iface)
    t = _iface_state(target_iface)
    if s is False or t is False:
        return 'down'
    if s is True and t is True:
        return 'active'
    if s is True or t is True:
        return 'active'
    return 'unknown'


# ---------------------------------------------------------------- 状态刷新
def refresh_link_status(execute=False):
    """按接口实际状态重算全部连接状态。返回变更计划（或已应用）。"""
    from models.models import ConnectionPath, Interface
    from extensions import db

    ifaces = {i.id: i for i in Interface.query.all()}
    changes = []
    for c in ConnectionPath.query.all():
        new_status = derive_link_status(ifaces.get(c.source_interface_id),
                                        ifaces.get(c.target_interface_id))
        if new_status != (c.link_status or 'unknown'):
            changes.append({
                'id': c.id,
                'old': c.link_status,
                'new': new_status,
                'desc': f'{c.source_port} ↔ {c.target_port}',
            })
            if execute:
                c.link_status = new_status
                c.updated_at = datetime.now(timezone.utc)
    if execute and changes:
        db.session.commit()
    return changes


# ---------------------------------------------------------------- 端口冲突
def find_port_conflicts():
    """返回 [(device_id, port, [connection_id, ...]), ...]：同一端口被多条连接占用。"""
    from models.models import ConnectionPath

    usage = {}
    for c in ConnectionPath.query.all():
        for dev_id, port in ((c.source_device_id, c.source_port),
                             (c.target_device_id, c.target_port)):
            if dev_id and port:
                usage.setdefault((dev_id, port), []).append(c)
    return [(dev_id, port, conns) for (dev_id, port), conns in usage.items()
            if len(conns) > 1]


def _score(conn, ifaces):
    """冲突仲裁打分：两端都 up 最高，其次最新发现，其次 id 大。"""
    up_cnt = sum(1 for iid in (conn.source_interface_id, conn.target_interface_id)
                 if _iface_state(ifaces.get(iid)) is True)
    down = any(_iface_state(ifaces.get(iid)) is False
               for iid in (conn.source_interface_id, conn.target_interface_id))
    ts = conn.discovery_time or conn.created_at or datetime.min
    return (0 if down else 1, up_cnt, ts, conn.id)


def resolve_port_conflicts(execute=False):
    """端口冲突仲裁：保留最优一条，其余标记陈旧（down + 降置信度 + 备注）。"""
    from models.models import Interface
    from extensions import db

    ifaces = {i.id: i for i in Interface.query.all()}
    plans = []
    for dev_id, port, conns in find_port_conflicts():
        ranked = sorted(conns, key=lambda c: _score(c, ifaces), reverse=True)
        winner = ranked[0]
        for loser in ranked[1:]:
            plans.append({
                'conn_id': loser.id,
                'device_id': dev_id,
                'port': port,
                'winner_id': winner.id,
                'peers': f'{loser.source_port} ↔ {loser.target_port}',
            })
            if execute:
                note = f"端口冲突：与连接 #{winner.id} 争用同一端口，判定为陈旧记录"
                loser.link_status = 'down'
                loser.confidence = min(loser.confidence or 0, 40)
                loser.description = ((loser.description or '') + ' ' + note).strip()
                loser.updated_at = datetime.now(timezone.utc)
    if execute and plans:
        db.session.commit()
    return plans


# ---------------------------------------------------------------- 端口名归一
def normalize_mac_ports(execute=False):
    """把 MAC 形状的端口名归一为 unknown，原值写入 description。"""
    from models.models import ConnectionPath
    from extensions import db

    changes = []
    for c in ConnectionPath.query.all():
        for attr in ('source_port', 'target_port'):
            val = getattr(c, attr)
            if looks_like_mac(val):
                changes.append({'id': c.id, 'field': attr, 'old': val})
                if execute:
                    note = f"{'源' if attr == 'source_port' else '目标'}端口未识别(原值 {val})"
                    c.description = ((c.description or '') + ' ' + note).strip()
                    setattr(c, attr, 'unknown')
                    c.confidence = min(c.confidence or 0, 70)
                    c.updated_at = datetime.now(timezone.utc)
    if execute and changes:
        db.session.commit()
    return changes
