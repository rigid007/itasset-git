# scripts/ — 运维与开发脚本

所有脚本均可从项目根目录直接运行（已内置 `sys.path` 引导）：

```powershell
python scripts\migrate\sync_permissions.py --execute
python scripts\migrate\patch_schema.py
python scripts\tests\smoke_test_itsm.py
python scripts\ops\dedup_connections.py --dry-run
```

## 目录说明

| 目录 | 用途 | 典型脚本 |
| --- | --- | --- |
| `migrate/` | schema 修补 / 权限同步 | `patch_schema.py`、`sync_permissions.py`、`add.py` |
| `ops/` | 数据清洗与诊断 | `dedup_connections.py`、`cleanup_lldp_placeholder_devices.py`、`check_ac.py` 等 |
| `tests/` | 冒烟与专项测试 | `smoke_test_itsm.py`、`_test_ac_discovery_*.py` |
| `legacy/` | 死代码存档（勿启用） | `task_scheduler.py`（旧调度器，启用会导致双轮询）、`snmp_scanner.py`（引用未导入符号）、`worker.py`（独立 Redis 消费者，未被应用引用） |

> 备注：`_test_event.py` / `_test_pool.py` / `_test_scan_graceful.py` / `_test_scan_timing.py`
> 因文件被占用暂时无法移动，仍位于项目根目录，可关闭占用进程后移入 `scripts/tests/`。
