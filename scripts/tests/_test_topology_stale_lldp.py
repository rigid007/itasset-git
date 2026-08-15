#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""LLDP 拓扑发现：过期链路自动标记 down 的轻量回归测试。

用临时 SQLite 库 + 打桩数据验证 _mark_stale_lldp_links：
    - 本次扫描未再发现的 LLDP 链路 -> down；
    - 本次仍可见的 LLDP 链路 -> 保持 active；
    - 非 LLDP 链路、未扫描设备上的 LLDP 链路 -> 不受影响。
不连生产库、不发 SNMP。
运行：python scripts/tests/_test_topology_stale_lldp.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))


def main():
    from flask import Flask
    from extensions import db
    from models.models import Device, ConnectionPath

    db_path = os.path.join(tempfile.gettempdir(), 'topo_prune_stale_lldp_test.db')
    if os.path.exists(db_path):
        os.remove(db_path)
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + db_path
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)

    with app.app_context():
        db.create_all()
        d34 = Device(id=34, name='h3c-F7', device_type='switch', management_ip='192.168.5.71')
        d105 = Device(id=105, name='GAM-13楼', device_type='switch', management_ip='10.1.0.61')
        d36 = Device(id=36, name='mz5-7F', device_type='switch', management_ip='192.168.5.66')
        d999 = Device(id=999, name='not-scanned', device_type='switch', management_ip='10.99.0.1')
        db.session.add_all([d34, d105, d36, d999])
        db.session.flush()

        seen = ConnectionPath(source_device_id=34, source_port='GigabitEthernet1/0/45',
                              target_device_id=36, target_port='GigabitEthernet1/0/22',
                              discovered_by='lldp', discovery_protocol='lldp',
                              link_status='active')
        stale = ConnectionPath(source_device_id=34, source_port='GigabitEthernet1/0/23',
                               target_device_id=105, target_port='GigabitEthernet2/0/45',
                               discovered_by='lldp', discovery_protocol='lldp',
                               link_status='active')
        non_lldp = ConnectionPath(source_device_id=34, source_port='GigabitEthernet1/0/1',
                                  target_device_id=105, target_port='unknown',
                                  discovered_by='snmp_mac', discovery_protocol='snmp_mac',
                                  link_status='active')
        untouched_other = ConnectionPath(source_device_id=999, source_port='GE1/0/1',
                                         target_device_id=105, target_port='GE1/0/2',
                                         discovered_by='lldp', discovery_protocol='lldp',
                                         link_status='active')
        db.session.add_all([seen, stale, non_lldp, untouched_other])
        db.session.commit()

        from blueprints.topology import _mark_stale_lldp_links
        pruned = _mark_stale_lldp_links({'192.168.5.71'}, {seen})
        db.session.commit()
        db.session.expire_all()
        for row in (seen, stale, non_lldp, untouched_other):
            db.session.refresh(row)

        assert pruned == 1, f'应标记 1 条为 down，实际 {pruned}'
        assert stale.link_status == 'down', stale.link_status
        assert seen.link_status == 'active', seen.link_status
        assert non_lldp.link_status == 'active', non_lldp.link_status
        assert untouched_other.link_status == 'active', untouched_other.link_status

        # 未传 lldp_seen_ips 时不做任何处理
        pruned2 = _mark_stale_lldp_links(set(), set())
        assert pruned2 == 0
        print('[OK] _mark_stale_lldp_links：过期 LLDP 链路标记 down，其余不受影响')


if __name__ == '__main__':
    main()
