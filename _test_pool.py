"""连接泄漏回归测试：验证后台任务在网络 I/O 期间不再持有 DB 连接。"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath('.')))
from unittest.mock import patch

from flask import Flask
from config import Config
from extensions import db
app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)


def checkedout():
    try:
        return db.engine.pool.checkedout()
    except Exception:
        return -1


with app.app_context():
    from models.models import Device
    devs = Device.query.filter_by(is_decommissioned=False).limit(5).all()
    print('sample devices:', len(devs))
    assert devs, 'need at least 1 device'
    # 解析 engine（需在 context 内），之后可在 context 外用 engine.pool 计数
    engine = db.engine

def checkedout():
    try:
        return engine.pool.checkedout()
    except Exception as e:
        return 'ERR:%s' % e

# ---- mock 网络 I/O，使其瞬时返回，避免真实探测 ----
mock_snap = {'ip': '127.0.0.1', 'community': 'public', 'version': '2c', 'name': 'mock'}

import utils.tasks as ut
import utils.utils as uu
import tasks.monitor as tm

with patch.object(ut, 'snmp_get_with_timeout', return_value=None), \
     patch.object(ut, 'ping_device', return_value=False), \
     patch.object(ut, 'snmp_walk', return_value=[]), \
     patch.object(ut, 'sync_device_interfaces', return_value=None), \
     patch.object(ut, 'update_connection_status', return_value=None), \
     patch.object(uu, 'ping_device', return_value=(False, 0.0)), \
     patch.object(uu, 'snmp_get', return_value=None), \
     patch.object(uu, 'get_device_snmp_data', return_value={}):

    # 1) check_device_status：逐个调用，每调用后连接应归还
    baseline = checkedout()
    print('baseline checkedout =', baseline)
    for d in devs:
        snap = dict(mock_snap, ip=d.management_ip or '127.0.0.1', name=d.name)
        ut.check_device_status(app, d.id, snap)
        co = checkedout()
        assert co == baseline, f'check_device_status 泄漏连接: {co} != {baseline}'
    print('[PASS] check_device_status 每调用后连接均归还 (checkedout=%s)' % checkedout())

    # 2) check_all_devices_status：整体结束后连接应归还
    before = checkedout()
    ut.check_all_devices_status(app)
    after = checkedout()
    assert after == before, f'check_all_devices_status 泄漏连接: {after} != {before}'
    print('[PASS] check_all_devices_status 结束后连接归还 (checkedout=%s)' % after)

    # 3) collect_device_metrics：整体结束后连接应归还
    before = checkedout()
    tm.collect_device_metrics(app)
    after = checkedout()
    assert after == before, f'collect_device_metrics 泄漏连接: {after} != {before}'
    print('[PASS] collect_device_metrics 结束后连接归还 (checkedout=%s)' % after)

print('ALL POOL LEAK TESTS PASSED')
