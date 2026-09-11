# -*- coding: utf-8 -*-
"""端到端：ENTITY-MIB 采集回填型号后，device_type 应同步判定（本次 bug 的真实路径）。

场景：H3C S7506E 的 sysDescr = "H3C Comware Platform Software..."（不含类型关键词），
旧逻辑拿到型号后仍把 device_type 留在 unknown。本用例验证 utils/entity_mib.apply_entity_info
在回填 chassis model 后会按型号补判类型，并对无线控制器型号置 is_wireless_controller。
"""
import sys
import time

sys.path.insert(0, 'D:/asset')

from app import app
from extensions import db
from models import Device
from utils.entity_mib import apply_entity_info

ts = int(time.time())


def _info(model_name, mfg_name):
    return {
        'supported': True,
        'chassis': {'physical_index': 1, 'entity_class': 'chassis', 'name': 'Chassis',
                    'description': 'Chassis', 'serial_number': f'SN-{ts}',
                    'mfg_name': mfg_name, 'model_name': model_name,
                    'hardware_rev': '', 'firmware_rev': '', 'software_rev': '', 'is_fru': False},
        'components': [],
    }


with app.app_context():
    cases = [
        ('S7506E', 'H3C', 'switch', False),
        ('MSR3620', 'H3C', 'router', False),
        ('WX2540H', 'H3C', 'other', True),
        ('CE6865-48S6CQ', 'Huawei', 'switch', False),
    ]
    failed = []
    for i, (model, mfg, want_type, want_ac) in enumerate(cases):
        dev = Device(name=f'zz_type_test_{ts}_{i}', management_ip=None,
                     device_type='unknown', model='', brand='')
        db.session.add(dev)
        db.session.commit()
        res = apply_entity_info(dev.id, _info(model, mfg))
        db.session.refresh(dev)
        got_type, got_ac = dev.device_type, bool(dev.is_wireless_controller)
        ok = (got_type == want_type and got_ac == want_ac)
        print(f'{"OK " if ok else "FAIL"} model={model:<16} -> type={got_type:<8} ac={got_ac}  '
              f'msg={str(res.get("message"))[:60]}')
        if not ok:
            failed.append(f'{model}: 期望 {want_type}/ac={want_ac}, 实得 {got_type}/ac={got_ac}')
        # 清理
        db.session.delete(dev)
        db.session.commit()

    if failed:
        print('\n失败:', failed)
        raise SystemExit(1)
    print('\n===== ENTITY-MIB 类型联动 ALL PASSED =====')
