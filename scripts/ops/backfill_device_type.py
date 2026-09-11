# -*- coding: utf-8 -*-
"""存量设备 device_type 回填（依据型号/名称反推），默认 DRY-RUN。

背景：型号(model)已能采集，但旧推断逻辑只认 sysDescr 关键字，导致"型号已识别、
类型仍 unknown"（如 H3C S7506E / sysDescr = "H3C Comware Platform Software..."）。

规则只作用于 device_type 为 unknown/空的设备，**不覆盖已有判定**。

用法：
    python scripts/ops/backfill_device_type.py            # 预览
    python scripts/ops/backfill_device_type.py --execute  # 落库
"""
import argparse
import sys

sys.path.insert(0, 'D:/asset')

from app import app
from extensions import db
from models import Device
from utils.model_type_map import infer_from_model, infer_from_name

UNKNOWN = ('unknown', 'other', '', None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--execute', action='store_true', help='真正写入数据库（默认仅预览）')
    args = ap.parse_args()

    with app.app_context():
        targets = Device.query.filter(
            db.or_(Device.device_type.is_(None),
                   Device.device_type == '',
                   Device.device_type.in_(('unknown', 'other')))
        ).order_by(Device.id).all()

        plan, skipped = [], 0
        for d in targets:
            res = infer_from_model(d.model or '', d.brand or '') or infer_from_name(d.name or '')
            if not res:
                skipped += 1
                continue
            plan.append((d, res['device_type'], res['is_wireless_controller']))

        print(f'待处理设备 {len(targets)} 台：可判定 {len(plan)} 台，无法判定 {skipped} 台')
        print('-' * 78)
        for d, dtype, is_ac in plan:
            src = '型号' if infer_from_model(d.model or '', d.brand or '') else '名称'
            print(f'id={d.id:<5} {str(d.name)[:28]:<28} model={str(d.model or "-")[:18]:<18} '
                  f'brand={str(d.brand or "-")[:8]:<8} -> {dtype:<8} ac={is_ac}  (依据{src})')
        print('-' * 78)

        if not args.execute:
            print('[DRY-RUN] 未写入，确认无误后加 --execute')
            return

        for d, dtype, is_ac in plan:
            d.device_type = dtype
            if is_ac:
                d.is_wireless_controller = True
        db.session.commit()
        print(f'[EXECUTED] 已更新 {len(plan)} 台设备的 device_type')


if __name__ == '__main__':
    main()
