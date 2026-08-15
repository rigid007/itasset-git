import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask
from config import Config
from extensions import db as ext_db
app = Flask(__name__)
app.config.from_object(Config)
ext_db.init_app(app)

print('TEST extensions.db id =', id(ext_db))
import sys as _sys
print('sys.modules[extensions] id =', id(_sys.modules['extensions'].db))

with app.app_context():
    from models import Device  # 包导入（与 app 一致）
    ip = Device.query.filter(Device.management_ip.isnot(None), Device.management_ip != '').first().management_ip
    print('TEST ip =', repr(ip))
    d0 = Device.query.filter((Device.management_ip == ip) | (Device.ip_address == ip)).first()
    print('outer found id =', d0.id, 'status =', d0.status)

    from services.event_monitor import event_monitor
    event_monitor.app = app  # 必须绑定 app
    print('event_monitor module file =', event_monitor.__module__)
    print('em uses extensions.db? id =', id(_sys.modules['extensions'].db))

    before = d0.status
    r = event_monitor.apply_device_event(ip, 'offline', 'event', 'smoke')
    print('apply returned:', r, 'in-memory status=', r.status if r else None)
    print('d0.status after apply =', d0.status)

# 用独立 pymysql 连接读取真实落库值
import re
m = re.match(r'mysql\+pymysql://([^:]+):([^@]*)@([^/]+)/([^?]+)', Config.SQLALCHEMY_DATABASE_URI)
user, pw, host, dbname = m.groups()
import pymysql
conn = pymysql.connect(host=host, user=user, password=pw, database=dbname, charset='utf8mb4')
cur = conn.cursor()
cur.execute('SELECT status FROM devices WHERE management_ip=%s', (ip,))
row = cur.fetchone()
print('DB ACTUAL status after apply =', row[0])
# 还原
with app.app_context():
    dd = Device.query.get(d0.id)
    dd.status = before
    ext_db.session.commit()
cur.execute('SELECT status FROM devices WHERE management_ip=%s', (ip,))
print('DB ACTUAL status after restore =', cur.fetchone()[0])
conn.close()
print('DONE')
