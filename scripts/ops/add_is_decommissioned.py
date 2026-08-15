"""
一次性脚本：为 devices 表添加 is_decommissioned 列。
运行方式：在工作目录 E:\asset 下执行
    python add_is_decommissioned.py
"""
import pymysql
import sys

DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': 'tcst2026',
    'database': 'asset',
    'charset': 'utf8mb4',
}

SQL = (
    "ALTER TABLE devices ADD COLUMN is_decommissioned TINYINT(1) "
    "NOT NULL DEFAULT 0, ADD INDEX ix_devices_is_decommissioned (is_decommissioned);"
)

try:
    conn = pymysql.connect(**DB_CONFIG)
    with conn.cursor() as cur:
        cur.execute(SQL)
    conn.commit()
    conn.close()
    print("[OK] is_decommissioned 列添加成功")
except pymysql.err.OperationalError as e:
    if "Duplicate column name" in str(e):
        print("[SKIP] 列已存在，无需重复添加")
    elif "Can't connect" in str(e):
        print("[ERROR] 无法连接 MySQL，请检查数据库是否运行")
        print(f"  详情: {e}")
    else:
        print(f"[ERROR] {e}")
        sys.exit(1)
except Exception as e:
    print(f"[ERROR] {e}")
    sys.exit(1)
