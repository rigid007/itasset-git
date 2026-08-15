# patch_schema.py
# 幂等 schema 修补脚本：为 ITSM 增强（G-N 轮）在已有表上补充新增列。
# 仅对「缺失」的列执行 ALTER TABLE ADD COLUMN，已存在则跳过；新建表由 db.create_all() 兜底。
# 用法（在已配置 DB_* 环境变量的终端中）：
#   python patch_schema.py
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

# 导入 app 会触发 init_extensions -> db.create_all()，自动创建缺失的新表
# 注意：app.py 内部 Flask 实例变量也叫 app，故用 `from app import app` 取到真正的 Flask 实例，
# 避免 `import app` 把 app 绑定成模块本身导致 `app.app_context` 报 AttributeError。
from app import app as flask_app  # noqa: E402
from extensions import db  # noqa: E402
from sqlalchemy import inspect, text  # noqa: E402

# (表, 列, MySQL DDL 类型)  —— 与模型定义保持一致（均为可空）
COLUMN_PATCHES = [
    ('service_catalogs', 'sla_policy_id', 'INTEGER'),
    ('work_orders', 'service_catalog_id', 'INTEGER'),
    ('work_orders', 'correlation_group', 'VARCHAR(50)'),
    ('work_orders', 'auto_created', 'BOOLEAN DEFAULT 0'),
    ('work_orders', 'is_major', 'BOOLEAN DEFAULT 0'),
    ('known_errors', 'knowledge_article_id', 'INTEGER'),
    ('alert_events', 'suppressed', 'BOOLEAN DEFAULT 0'),
    ('alert_events', 'correlation_group', 'VARCHAR(50)'),
    # ---- 连接老化与 AP 字段（迁移 i5e6f7g8h9a0）----
    ('connection_paths', 'last_seen', 'DATETIME'),
    ('connection_paths', 'auto_discovered', 'BOOLEAN'),
    ('connection_paths', 'neighbor_managed', 'BOOLEAN'),
    ('connection_paths', 'link_role', 'VARCHAR(20)'),
    # ---- 无线控制器字段（迁移 j6f7g8h9a0b1）----
    ('devices', 'is_wireless_controller', 'BOOLEAN'),
    ('devices', 'controller_vendor', 'VARCHAR(20)'),
]


def add_column_if_missing(table, column, ddl_type):
    insp = inspect(db.engine)
    existing = {c['name'] for c in insp.get_columns(table)}
    if column in existing:
        print(f'[skip] {table}.{column} 已存在')
        return
    with db.engine.begin() as conn:
        conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {column} {ddl_type}'))
    print(f'[add]  {table}.{column}')


# (表, 索引名, 索引列表达式)  —— 幂等创建索引，已存在则跳过
INDEX_PATCHES = [
    # 设备状态高频过滤（/monitoring/api/status_summary, device_status 列表）
    ('devices', 'idx_devices_status', 'status'),
    # 链路状态高频过滤（/api/links/stats, /api/links/status）
    ('connection_paths', 'idx_connection_paths_link_status', 'link_status'),
    # DeviceMonitorLog 按 monitor_type + device_id 查询（SLA计算、链路历史）
    ('device_monitor_logs', 'idx_dml_monitor_type', 'monitor_type'),
    ('device_monitor_logs', 'idx_dml_device_type', 'device_id, monitor_type'),
    # 设备是否下线高频过滤（列表页、报表）
    ('devices', 'idx_devices_is_decommissioned', 'is_decommissioned'),
]


def add_index_if_missing(table, index_name, columns_expr):
    """幂等创建索引：检查索引是否已存在，不存在则 CREATE INDEX"""
    insp = inspect(db.engine)
    existing_indexes = {idx['name'] for idx in insp.get_indexes(table)}
    if index_name in existing_indexes:
        print(f'[skip] 索引 {index_name} 已存在')
        return
    with db.engine.begin() as conn:
        conn.execute(text(f'CREATE INDEX {index_name} ON {table} ({columns_expr})'))
    print(f'[add]  索引 {index_name} ON {table}({columns_expr})')


if __name__ == '__main__':
    with flask_app.app_context():
        # 打印即将修补的数据库地址（隐藏密码），避免加错库
        _uri = flask_app.config.get('SQLALCHEMY_DATABASE_URI', '')
        _masked = __import__('re').sub(r'(://[^:/]+:)[^@]+(@)', r'\1****\2', _uri)
        print(f'[info] 即将修补数据库: {_masked}')

        for tbl, col, ddl in COLUMN_PATCHES:
            try:
                add_column_if_missing(tbl, col, ddl)
            except Exception as e:  # 单列表失败不影响其余
                print(f'[ERR]  {tbl}.{col}: {e}')

        # 创建性能索引
        for tbl, idx_name, cols in INDEX_PATCHES:
            try:
                add_index_if_missing(tbl, idx_name, cols)
            except Exception as e:
                print(f'[ERR]  索引 {idx_name}: {e}')

        # 兜底：确保 4 张新表存在（availability_records/csat_surveys/
        # change_impact_analyses/service_catalog_devices）
        db.create_all()
    print('SCHEMA_PATCH_DONE')
    sys.exit(0)
