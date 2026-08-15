"""诊断脚本：检查应用实际连接的数据库中，无线控制器相关列与已标记设备。

运行方式（请在「启动本系统的同一环境/同一 DATABASE_URL」下执行）：
    python check_ac.py
或指定真实库：
    DATABASE_URL=mysql+pymysql://user:pw@host:3306/realdb python check_ac.py

它会打印：
    1) 应用解析到的数据库连接地址（URI 前缀，隐藏密码）
    2) devices 表是否存在 is_wireless_controller / controller_vendor 列
    3) 被标记为无线控制器的设备清单
"""
import re
import os
import sys

# 使脚本可从任意目录运行（scripts/ops -> 项目根）
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from app import app as flask_app
from extensions import db
from sqlalchemy import inspect, text


def mask(uri: str) -> str:
    # 隐藏密码，避免泄露
    return re.sub(r'(://[^:/]+:)[^@]+(@)', r'\1****\2', uri)


with flask_app.app_context():
    uri = flask_app.config.get('SQLALCHEMY_DATABASE_URI', '')
    print("==> 应用解析到的数据库 URI:")
    print("    ", mask(uri))

    inspector = inspect(db.engine)
    if not inspector.has_table('devices'):
        print("!! devices 表不存在，请先初始化数据库。")
        raise SystemExit(1)

    cols = {c['name'] for c in inspector.get_columns('devices')}
    need = ['is_wireless_controller', 'controller_vendor']
    print("==> devices 表中相关列:")
    for c in need:
        print(f"    {c}: {'存在' if c in cols else '缺失 !!'}")

    if 'is_wireless_controller' in cols:
        try:
            rows = db.session.execute(
                text("SELECT id, name, is_wireless_controller, controller_vendor "
                     "FROM devices WHERE is_wireless_controller = 1")
            ).fetchall()
            print(f"==> 已标记为无线控制器的设备数: {len(rows)}")
            for r in rows:
                print("    ", dict(zip(['id', 'name', 'is_ac', 'vendor'], r)))
        except Exception as e:
            print("!! 查询已标记设备失败:", e)

    total = db.session.execute(text("SELECT COUNT(*) FROM devices")).scalar()
    print(f"==> devices 总条数: {total}")
