"""设备分组自动归类服务"""
from __future__ import annotations
import re
from datetime import datetime, timezone
from extensions import db
from models.device_group_models import DeviceGroup, device_group_members
from models.models import Device


def classify_single_device(device_id, group_id):
    """将单个设备加入分组（去重）"""
    exists = db.session.query(device_group_members).filter_by(
        device_id=device_id, group_id=group_id
    ).first()
    if exists:
        return False
    stmt = device_group_members.insert().values(
        device_id=device_id,
        group_id=group_id,
        assigned_at=datetime.now(timezone.utc)
    )
    db.session.execute(stmt)
    db.session.commit()
    return True


def remove_device_from_group(device_id, group_id):
    """从分组中移除设备"""
    stmt = device_group_members.delete().where(
        device_group_members.c.device_id == device_id,
        device_group_members.c.group_id == group_id
    )
    db.session.execute(stmt)
    db.session.commit()


def auto_classify_by_ip_subnet():
    """按IP网段自动归类：提取所有设备 management_ip 的前三段，自动创建分组并归类"""
    devices = Device.query.filter(Device.management_ip.isnot(None),
                                   Device.management_ip != '').all()
    result = {'created': 0, 'assigned': 0, 'groups': []}

    for device in devices:
        ip = device.management_ip.strip()
        parts = ip.split('.')
        if len(parts) < 3:
            continue
        subnet = '.'.join(parts[:3]) + '.'
        group_name = subnet + '0/24'

        # 查找或创建分组
        group = DeviceGroup.query.filter_by(
            auto_rule_type='ip_subnet', auto_rule_value=subnet
        ).first()
        if not group:
            group = DeviceGroup(
                name=group_name,
                description=f'IP网段 {subnet}0/24 自动归类',
                color='#28a745',
                icon='fa-network-wired',
                auto_rule_type='ip_subnet',
                auto_rule_value=subnet,
            )
            db.session.add(group)
            db.session.flush()
            result['created'] += 1
            result['groups'].append(group_name)

        # 归类设备
        if classify_single_device(device.id, group.id):
            result['assigned'] += 1

    return result


def auto_classify_by_name_pattern():
    """按设备名称模式自动归类：遍历所有设置了 name_pattern 规则的分组，匹配设备名称"""
    groups = DeviceGroup.query.filter_by(auto_rule_type='name_pattern').all()
    result = {'matched_groups': 0, 'assigned': 0}

    for group in groups:
        if not group.auto_rule_value:
            continue
        pattern = group.auto_rule_value.replace('%', '.*').replace('_', '.')
        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error:
            continue

        devices = Device.query.all()
        matched = 0
        for device in devices:
            if regex.search(device.name):
                if classify_single_device(device.id, group.id):
                    matched += 1

        if matched > 0:
            result['matched_groups'] += 1
            result['assigned'] += matched

    return result


def get_group_tree(groups=None, parent_id=None):
    """获取分组树形结构（用于前端展示）"""
    if groups is None:
        groups = DeviceGroup.query.order_by(DeviceGroup.sort_order, DeviceGroup.name).all()

    tree = []
    for g in groups:
        if g.parent_id == parent_id:
            children = get_group_tree(groups, g.id)
            node = g.to_dict()
            node['children'] = children
            tree.append(node)
    return tree


def get_all_groups_flat():
    """获取扁平的全部分组列表（用于下拉选择）"""
    return DeviceGroup.query.order_by(DeviceGroup.sort_order, DeviceGroup.name).all()
