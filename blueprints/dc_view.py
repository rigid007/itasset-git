"""机房 3D 可视化蓝图 (data center visualization)

提供:
  /dc                              -> 重定向到 /dc/babylon (Babylon.js 3D 机房可视化)
  /dc/babylon                      -> 3D 机房可视化单页(Babylon.js, 推荐, 离线可用)
  /api/dc/locations                -> 机房(位置)列表
  /api/dc/<location_id>            -> 某机房机柜/设备布局 JSON
  /api/dc/cabinet/<cabinet_id>     -> 单机柜详情(含 U 位占用)
  /api/dc/device/<device_id>       -> 单设备详情

所有数据复用现有模型: Location -> Cabinet(pos_x/pos_y/width/depth/height_u)
-> Device(position_u/height_u/status)。

注意: 原 Three.js 原型(/dc 旧实现)已移除, 全系统统一采用 Babylon.js(Apache-2.0,
本地托管于 static/js/, 完全离线可用, 无 CDN 依赖)。
"""
from flask import Blueprint, request, jsonify, render_template, redirect, url_for, abort
from flask_login import login_required
from extensions import db
from utils.permission import permission_required
from models.models import Location, Cabinet, Device

dc_view_bp = Blueprint('dc_view', __name__)

# 设备状态 -> 展示颜色(与前端一致)。离线/故障统一为红色系, 突出告警。
STATUS_COLORS = {
    'online': '#2ecc71', 'active': '#2ecc71',
    'offline': '#e74c3c', 'down': '#c0392b',
    'warning': '#f39c12', 'maintenance': '#3498db',
    'alert': '#c0392b', 'error': '#c0392b', 'critical': '#922b21',
    'unknown': '#bdc3c7',
}


def _device_json(d):
    return {
        'id': d.id,
        'name': d.name,
        'device_type': d.device_type or 'server',
        'brand': d.brand or '',
        'model': d.model or '',
        'position_u': d.position_u,
        'height_u': d.height_u or 1,
        'status': (d.status or 'unknown'),
        'ip_address': d.ip_address or '',
        'management_ip': getattr(d, 'management_ip', None) or '',
        'cpu_usage': d.cpu_usage,
        'memory_usage': d.memory_usage,
        'temperature': d.temperature,
        'power_consumption': getattr(d, 'power_consumption', None),
        'cabinet_id': d.cabinet_id,
    }


def _cabinet_json(c):
    ua = c.get_u_availability()
    return {
        'id': c.id,
        'name': c.name,
        'pos_x': c.pos_x,
        'pos_y': c.pos_y,
        'width': c.width,
        'depth': c.depth,
        'height_u': c.height_u or 42,
        'color': c.color or '#007bff',
        'u_total': ua['total'],
        'u_used': ua['used'],
        'u_usage': ua['usage_percentage'],
        'device_count': c.device_count,
        'devices': [_device_json(d) for d in c.devices],
    }


@dc_view_bp.route('/dc')
@login_required
def dc_index():
    """旧 Three.js 入口, 重定向到 Babylon.js 视图(避免历史书签失效)。"""
    return redirect(url_for('dc_view.dc_babylon'))


@dc_view_bp.route('/dc/babylon')
@login_required
def dc_babylon():
    """3D 机房可视化页面 (Babylon.js 引擎)

    复用全部现有 JSON 接口。Babylon.js 为 Apache-2.0 开源引擎, 库文件
    已本地托管于 static/js/(babylon.js + babylon.gui.min.js), 完全离线
    可用, 且内置 ArcRotateCamera 漫游/指针拾取/GUI 标签, 交互体验优,
    适合内网机房可视化。全系统唯一的 3D 机房引擎。
    """
    return render_template('dc/dc_view_babylon.html')


@dc_view_bp.route('/api/dc/locations')
@login_required
def api_locations():
    locs = Location.query.order_by(Location.name).all()
    return jsonify([
        {'id': l.id, 'name': l.name, 'cabinet_count': l.cabinet_count()}
        for l in locs
    ])


@dc_view_bp.route('/api/dc/<int:location_id>')
@login_required
def api_dc_view(location_id):
    loc = Location.query.get_or_404(location_id)
    cabinets = [_cabinet_json(c) for c in loc.cabinets]
    return jsonify({
        'id': loc.id,
        'name': loc.name,
        'description': loc.description,
        'cabinet_count': len(cabinets),
        'device_count': sum(c['device_count'] for c in cabinets),
        'cabinets': cabinets,
    })


@dc_view_bp.route('/api/dc/cabinet/<int:cabinet_id>')
@login_required
def api_cabinet(cabinet_id):
    c = Cabinet.query.get_or_404(cabinet_id)
    ua = c.get_u_availability()
    return jsonify({
        'id': c.id,
        'name': c.name,
        'location_id': c.location_id,
        'height_u': c.height_u,
        'u_total': ua['total'],
        'u_used': ua['used'],
        'u_remaining': ua['remaining'],
        'u_usage': ua['usage_percentage'],
        'devices': [_device_json(d) for d in c.devices],
    })


@dc_view_bp.route('/api/dc/device/<int:device_id>')
@login_required
def api_device(device_id):
    d = Device.query.get_or_404(device_id)
    data = _device_json(d)
    data['cabinet_name'] = d.cabinet.name if d.cabinet else None
    data['location_id'] = d.location_id
    data['description'] = d.description or ''
    return jsonify(data)


@dc_view_bp.route('/api/dc/layout', methods=['POST'])
@login_required
@permission_required('cabinet:edit')
def api_save_layout():
    """保存机柜自定义排列: 接收 [{id, pos_x, pos_y}] 写回 Cabinet.pos_x/pos_y(百分比 0-100)。"""
    payload = request.get_json(silent=True) or {}
    rows = payload.get('cabinets') or []
    updated = 0
    for r in rows:
        cid = r.get('id')
        if cid is None:
            continue
        c = Cabinet.query.get(int(cid))
        if not c:
            continue
        px = r.get('pos_x')
        py = r.get('pos_y')
        if px is not None:
            c.pos_x = max(0.0, min(100.0, float(px)))
        if py is not None:
            c.pos_y = max(0.0, min(100.0, float(py)))
        updated += 1
    db.session.commit()
    return jsonify({'ok': True, 'updated': updated})
