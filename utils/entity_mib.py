# -*- coding: utf-8 -*-
"""ENTITY-MIB 硬件资产采集（P0-3）。

对标 iMC/U-Center 的板卡资产管理：走 entPhysicalTable 采集机箱序列号、
板卡/电源/风扇明细，实现"设备自动添加"的资产信息闭环。

设计严格遵循项目的 3 阶段 DB 上下文分离铁律：
  阶段1（短读）  读取设备的 ip/community/version → db.session.remove()
  阶段2（外联）  纯 SNMP 采集，零 DB 连接（collect_entity_info）
  阶段3（短写）  结果一次性写入 Device/DeviceComponent → db.session.remove()

对外入口：
  sync_device_hardware(device_id)  单设备同步（3 阶段编排）
  collect_entity_info(ip, ...)     纯采集（无 DB，可独立测试/复用）
  apply_entity_info(device_id, ..) 纯写入（要求调用方已持 app context）
"""

import logging
from datetime import datetime

from extensions import db
from models import Device, DeviceComponent
from utils.snmp_oids import ENTITY, ENTITY_CLASS
from utils.snmp_utils import snmp_walk
from utils.model_type_map import infer_from_model

logger = logging.getLogger(__name__)

# 需要采集的 entPhysicalTable 列（一次 walk 一列，net-snmp 进程模型下开销可控）
_ENTITY_COLUMNS = (
    ('descr', ENTITY['descr'], str),
    ('contained_in', ENTITY['contained_in'], int),
    ('entity_class', ENTITY['class'], int),
    ('name', ENTITY['name'], str),
    ('serial_num', ENTITY['serial_num'], str),
    ('mfg_name', ENTITY['mfg_name'], str),
    ('model_name', ENTITY['model_name'], str),
    ('hardware_rev', ENTITY['hardware_rev'], str),
    ('firmware_rev', ENTITY['firmware_rev'], str),
    ('software_rev', ENTITY['software_rev'], str),
    ('is_fru', ENTITY['is_fru'], int),
)

# 落库的部件类别：端口数量大且无资产价值，默认跳过（可开）
_STORED_CLASSES = {'chassis', 'backplane', 'container', 'powerSupply',
                   'fan', 'sensor', 'module', 'stack', 'cpu'}


def _clean(value, conv=str):
    """清洗 SNMP 值：去引号/空白，空串归 None；int 转换失败归 None。"""
    if value is None:
        return None
    s = str(value).strip().strip('"').strip()
    if not s or s.lower() in ('n/a', 'na', 'null', 'none', 'unknown', '0x', '(null)'):
        return None
    if conv is int:
        try:
            # snmpwalk 输出 INTEGER 可能带枚举文本，如 'chassis(3)' —— 取括号内数字
            if '(' in s:
                inner = s.split('(', 1)[1].split(')', 1)[0]
                if inner.strip().lstrip('-').isdigit():
                    s = inner.strip()
            return int(s)
        except (ValueError, TypeError):
            return None
    return s[:250] if conv is str else s


def collect_entity_info(ip, community='public', version='2c', timeout=5,
                        include_ports=False):
    """纯 SNMP 采集 entPhysicalTable，返回结构化硬件信息（零 DB 访问）。

    返回:
        {
          'supported': bool,          # 设备是否实现了 ENTITY-MIB
          'chassis': {...} | None,    # 机箱（含序列号/型号）
          'components': [ {...}, ...],# 板卡/电源/风扇等部件列表
          'component_count': int,
        }
    """
    raw = {}  # {physical_index: {field: value}}
    for field, oid, conv in _ENTITY_COLUMNS:
        try:
            rows = snmp_walk(ip, oid, community, version, timeout)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"ENTITY-MIB walk 失败 {ip} {field}: {e}")
            continue
        for oid_str, val in rows:
            try:
                idx = int(oid_str.split('.')[-1])
            except (ValueError, TypeError):
                continue
            v = _clean(val, conv)
            if v is not None:
                raw.setdefault(idx, {})[field] = v

    if not raw:
        return {'supported': False, 'chassis': None, 'components': [],
                'component_count': 0}

    components, chassis = [], None
    for idx in sorted(raw):
        row = raw[idx]
        cls_code = row.get('entity_class')
        cls_name = ENTITY_CLASS.get(cls_code, 'unknown' if cls_code is None else str(cls_code))
        entry = {
            'physical_index': idx,
            'parent_index': row.get('contained_in'),
            'entity_class': cls_name,
            'name': row.get('name'),
            'description': row.get('descr'),
            'serial_number': row.get('serial_num'),
            'mfg_name': row.get('mfg_name'),
            'model_name': row.get('model_name'),
            'hardware_rev': row.get('hardware_rev'),
            'firmware_rev': row.get('firmware_rev'),
            'software_rev': row.get('software_rev'),
            'is_fru': bool(row.get('is_fru') == 1),
        }
        # 机箱：取第一个 chassis 实体（堆叠多机箱时后续的也存 components）
        if cls_name == 'chassis' and chassis is None:
            chassis = dict(entry)
            continue
        if cls_name in _STORED_CLASSES or (include_ports and cls_name == 'port'):
            # 过滤无信息量的条目：无序列号/型号/描述全空的 sensor 等
            if (entry['serial_number'] or entry['model_name']
                    or entry['description'] or entry['name']):
                components.append(entry)

    return {
        'supported': True,
        'chassis': chassis,
        'components': components,
        'component_count': len(components) + (1 if chassis else 0),
    }


def apply_entity_info(device_id, info):
    """将采集结果写入数据库（短写阶段，要求调用方持有 app context）。

    - 机箱序列号回填 Device.serial_number（唯一约束冲突时跳过并返回警告）；
    - 部件按 (device_id, physical_index) upsert 到 DeviceComponent；
    - 已消失的部件行删除（同步 entPhysicalTable 现状）。

    返回: {'success': bool, 'serial_applied': bool, 'component_count': int,
           'message': str}
    """
    device = Device.query.get(device_id)
    if not device:
        db.session.rollback()
        return {'success': False, 'serial_applied': False,
                'component_count': 0, 'message': f'设备 {device_id} 不存在'}

    now = datetime.utcnow()
    message_parts = []
    serial_applied = False

    # ---- 机箱序列号回填 ----
    chassis = info.get('chassis') or {}
    chassis_serial = (chassis.get('serial_number') or '').strip()
    if chassis_serial and device.serial_number != chassis_serial:
        conflict = Device.query.filter(
            Device.serial_number == chassis_serial, Device.id != device.id
        ).first()
        if conflict:
            message_parts.append(
                f'序列号 {chassis_serial} 已被设备 {conflict.id}({conflict.name}) 占用，未回填')
        else:
            device.serial_number = chassis_serial
            serial_applied = True
            message_parts.append(f'回填序列号 {chassis_serial}')
    # 机箱型号补充（设备 model 为空时）
    chassis_model = (chassis.get('model_name') or '').strip()
    if chassis_model and not (device.model or '').strip():
        device.model = chassis_model[:64]
    # 板卡厂商补充（设备 brand 为空时）
    mfg = (chassis.get('mfg_name') or '').strip()
    if mfg and not (device.brand or '').strip():
        device.brand = mfg[:64]

    # 型号回填后重判设备类型：sysDescr 往往不含类型关键词（如 H3C S7506E），
    # 仅靠 model/brand 即可定类型，避免"型号已识别、类型仍 unknown"。
    _cur_model = (device.model or '').strip()
    if _cur_model and (device.device_type or 'unknown') in ('unknown', 'other', ''):
        mt = infer_from_model(_cur_model, device.brand or '')
        if mt:
            device.device_type = mt['device_type']
            message_parts.append(f"按型号 {_cur_model} 判定类型 {mt['device_type']}")
            if mt['is_wireless_controller']:
                device.is_wireless_controller = True

    # ---- 部件 upsert ----
    existing = {c.physical_index: c
                for c in DeviceComponent.query.filter_by(device_id=device_id).all()}
    seen_idx = set()
    if chassis:
        seen_idx.add(chassis['physical_index'])
    comp_count = 0
    for entry in info.get('components', []):
        idx = entry['physical_index']
        seen_idx.add(idx)
        row = existing.get(idx)
        if row is None:
            row = DeviceComponent(device_id=device_id, physical_index=idx,
                                  created_at=now)
            db.session.add(row)
        row.parent_index = entry.get('parent_index')
        row.entity_class = entry.get('entity_class')
        row.name = entry.get('name')
        row.description = entry.get('description')
        row.serial_number = entry.get('serial_number')
        row.mfg_name = entry.get('mfg_name')
        row.model_name = entry.get('model_name')
        row.hardware_rev = entry.get('hardware_rev')
        row.firmware_rev = entry.get('firmware_rev')
        row.software_rev = entry.get('software_rev')
        row.is_fru = bool(entry.get('is_fru'))
        row.last_seen = now
        comp_count += 1
    # 机箱本身也作为一行部件保留（含序列号，便于板卡清单完整展示）
    if chassis:
        idx = chassis['physical_index']
        row = existing.get(idx)
        if row is None:
            row = DeviceComponent(device_id=device_id, physical_index=idx,
                                  created_at=now)
            db.session.add(row)
        row.parent_index = chassis.get('parent_index')
        row.entity_class = 'chassis'
        row.name = chassis.get('name')
        row.description = chassis.get('description')
        row.serial_number = chassis.get('serial_number')
        row.mfg_name = chassis.get('mfg_name')
        row.model_name = chassis.get('model_name')
        row.hardware_rev = chassis.get('hardware_rev')
        row.firmware_rev = chassis.get('firmware_rev')
        row.software_rev = chassis.get('software_rev')
        row.is_fru = bool(chassis.get('is_fru'))
        row.last_seen = now

    # ---- 删除已消失的部件行 ----
    stale = [c for idx, c in existing.items() if idx not in seen_idx]
    for c in stale:
        db.session.delete(c)
    if stale:
        message_parts.append(f'移除 {len(stale)} 个已消失部件')

    try:
        db.session.commit()
    except Exception as e:  # noqa: BLE001
        db.session.rollback()
        logger.error(f'ENTITY 资产写入失败 device={device_id}: {e}')
        return {'success': False, 'serial_applied': False,
                'component_count': 0, 'message': f'数据库写入失败: {e}'}

    if not message_parts:
        message_parts.append('硬件信息无变化')
    return {
        'success': True,
        'serial_applied': serial_applied,
        'component_count': comp_count,
        'message': '；'.join(message_parts),
    }


def sync_device_hardware(device_id):
    """单设备硬件同步（3 阶段 DB 上下文分离编排，需在 app context 内调用）。

    阶段1 短读：取 ip/community/version → remove()
    阶段2 外联：collect_entity_info 纯 SNMP，零 DB
    阶段3 短写：apply_entity_info → remove()
    """
    # ---- 阶段1：短读 ----
    device = Device.query.get(device_id)
    if not device:
        db.session.remove()
        return {'success': False, 'message': f'设备 {device_id} 不存在'}
    ip = device.management_ip or device.ip_address
    community = device.snmp_community or 'public'
    version = str(device.snmp_version or '2c')
    if version not in ('1', '2c'):
        version = '2c'
    db.session.remove()  # 铁律：外联前清空 DB 上下文

    if not ip:
        return {'success': False, 'message': '设备无管理 IP'}

    # ---- 阶段2：外部 I/O（零 DB 连接） ----
    try:
        info = collect_entity_info(ip, community, version, timeout=5)
    except Exception as e:  # noqa: BLE001
        logger.error(f'ENTITY-MIB 采集异常 {ip}: {e}')
        return {'success': False, 'message': f'采集异常: {e}'}

    if not info.get('supported'):
        return {'success': False, 'message': f'{ip} 不支持 ENTITY-MIB（无 entPhysicalTable）'}

    # ---- 阶段3：短写 ----
    try:
        result = apply_entity_info(device_id, info)
    finally:
        db.session.remove()
    if result.get('success'):
        result['component_count'] = info.get('component_count', result.get('component_count', 0))
        result['message'] = (f"采集 {result['component_count']} 个硬件部件："
                             + result.get('message', ''))
    return result
