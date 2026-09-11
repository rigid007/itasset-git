# IT 资产与运维管理平台

一个基于 **Flask + SQLAlchemy + APScheduler + Socket.IO** 的 IT 资产、网络设备与运维管理平台。适用于企业内部数据中心、机房、网络与服务器资产的台账管理、监控告警、拓扑发现、运维工单和报表分析等场景。


## 主要能力

| 模块 | 说明 |
| --- | --- |
| 资产/CMDB | 设备、服务器、网络设备、备件、机柜、位置、设备组、IP/接口关系、资产导入导出 |
| 监控告警 | Ping/SNMP 状态检测、接口监控、链路监控、告警规则与通知 |
| 拓扑发现 | LLDP 拓扑、数据中心视图、服务器与交换机连接关系发现 |
| 事件监控 | SNMP Trap / Syslog / JSON 心跳事件接收与告警 |
| NetFlow | 流量采集、Top 会话、阈值告警、留存管理 |
| 带外管理 OOB | iDRAC / iLO / iBMC / XCC 轮询、传感器告警、恢复通知 |
| ITSM/运维 | 维护工单、CAB 审批链、SLA、自动化任务、变更/维护记录 |
| 报表 | 维护报表、监控报表、日志与活动记录 |
| 权限安全 | Flask-Login、RBAC 权限、CSRF 防护、审计日志、HTML 过滤 |
| 实时交互 | WebSSH/实时终端、Socket.IO 实时刷新 |

---

## 技术栈

- Python 3
- Flask / Flask-Login / Flask-SQLAlchemy / Flask-Migrate / Flask-WTF / Flask-SocketIO
- SQLAlchemy / MySQL 或 SQLite
- APScheduler
- Waitress（Windows 生产部署）/ Gunicorn（Linux 生产部署）
- Paramiko / Netmiko / pysnmp / ncclient / pyghmi / NetFlow 相关库

---

## 快速开始

### 1. 克隆仓库

```powershell
git clone https://github.com/rigid007/itasset-git.git
cd itasset-git
```

### 2. 创建虚拟环境并安装依赖

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirement.txt
```

### 3. 配置环境变量

复制 `.env.example` 为 `.env`：

```powershell
Copy-Item .env.example .env
```

至少需要设置：

```dotenv
SECRET_KEY=replace-with-a-long-random-secret
DATABASE_URL=mysql+pymysql://USER:PASSWORD@HOST:3306/asset
ALLOW_PUBLIC_REGISTRATION=false
FLASK_DEBUG=0
HOST=0.0.0.0
PORT=8000
```

生成随机 `SECRET_KEY`：

```powershell
python -c "import secrets;print(secrets.token_hex(32))"
```

如果不配置 `DATABASE_URL`，系统默认使用 SQLite：

```
instance/asset.db
```

### 4. 初始化并启动

本地开发/验证：

```powershell
python app.py
```

Windows 生产部署推荐：

```powershell
python wsgi.py
```

或直接使用 waitress：

```powershell
waitress-serve --host=0.0.0.0 --port=8000 --threads=16 wsgi:application
```

启动后访问：

```
http://127.0.0.1:8000
```

---

## 默认账号

首次启动会自动创建管理员账号：

| 用户名 | 密码 | 说明 |
| --- | --- | --- |
| `admin` | `admin123` | 首次登录后请立即修改密码 |

> 如果系统已存在 `admin` 用户，初始化脚本不会覆盖已有账号密码。

---

## 常用环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `SECRET_KEY` | 随机生成 | Flask session/CSRF 密钥，生产环境必须固定 |
| `DATABASE_URL` | 空 | 完整数据库连接地址；优先于 `DB_*` 配置 |
| `DB_USER` / `DB_PASSWORD` / `DB_HOST` / `DB_PORT` / `DB_NAME` | `root` / 空 / `localhost` / `3306` / `asset` | MySQL 连接信息，未设置 `DATABASE_URL` 时使用 |
| `ALLOW_PUBLIC_REGISTRATION` | `true` | 是否允许公开注册，内部系统建议 `false` |
| `HOST` | `127.0.0.1` | 监听地址 |
| `PORT` | `5000`（app.py）/ `8000`（wsgi.py） | 监听端口 |
| `FLASK_DEBUG` | `0` | 生产环境必须保持 `0` |
| `ENABLE_SCHEDULER` | `1` | 是否启动 APScheduler 定时任务 |
| `ENABLE_LINK_MONITOR` | `1` | 是否初始化链路监控 |
| `EVENT_MONITOR_ENABLED` | `1` | 是否启用 SNMP Trap / Syslog / JSON 事件监控 |
| `EVENT_MONITOR_TRAP_PORT` | `9162` | Trap 监听端口 |
| `EVENT_MONITOR_SYSLOG_PORT` | `9514` | Syslog 监听端口 |
| `OOB_ENABLED` | `1` | 是否启用带外管理轮询 |
| `OOB_POLL_INTERVAL_SEC` | `300` | OOB 轮询间隔 |
| `NETFLOW_ENABLED` | `1` | 是否启用 NetFlow 采集 |
| `NETFLOW_ALERT_THRESHOLD_MBPS` | `0` | NetFlow 流量告警阈值，0 表示关闭 |

更多配置项见 `config.py`。

---

## 目录结构

```text
.
├── app.py                  # Flask 应用入口与开发启动
├── app_init.py             # 建表、默认管理员、默认配置初始化
├── wsgi.py                 # 生产 WSGI 入口，补齐数据库/调度器/链路监控初始化
├── run_app.py              # PyInstaller 打包入口
├── config.py               # 统一配置解析
├── extensions.py           # Flask 扩展初始化
├── models/                 # 数据模型
├── blueprints/             # 各业务模块路由
├── services/               # 业务服务、通知、OOB、NetFlow 等服务
├── tasks/                  # 调度任务与监控任务
├── templates/              # Jinja2 模板
├── static/                 # 静态资源
├── scripts/                # 运维、迁移、测试脚本
├── alembic/                # 数据库迁移配置
├── uploads/                # 上传文件目录
├── logs/                   # 日志目录
├── document/               # 项目说明、问题记录、使用手册
└── requirement.txt         # Python 依赖
```

---

## 部署注意事项

### 不要用 Flask 开发服务器做生产

生产环境请使用：

```powershell
waitress-serve --host=0.0.0.0 --port=8000 --threads=16 wsgi:application
```

或 Linux 下使用 Gunicorn。

### 多进程部署避免重复调度

APScheduler 是进程内调度器。如果使用 `gunicorn -w 4`，每个 worker 都会启动一套调度器，可能重复执行任务。

推荐方案：

1. 使用 `waitress` 单进程多线程部署；
2. 或只保留一个进程启用调度器，其他 worker 设置 `ENABLE_SCHEDULER=0`。

### 安全建议

- 不要提交 `.env`、`.env-gam`、`instance/asset.db`、`logs/`、`uploads/` 中的敏感数据；
- 生产环境必须设置固定的 `SECRET_KEY`；
- 关闭 `FLASK_DEBUG`；
- 关闭公开注册：`ALLOW_PUBLIC_REGISTRATION=false`；
- 首次启动后立即修改默认管理员密码；
- 通过 HTTPS、反向代理或内网防火墙保护 Web 服务。

---

## 运维脚本

部分常用脚本见 `scripts/README.md`：

```powershell
python scripts\migrate\sync_permissions.py --execute
python scripts\migrate\patch_schema.py
python scripts\tests\smoke_test_itsm.py
python scripts\ops\dedup_connections.py --dry-run
```

---

## 常见问题

### 数据库版本不一致

优先检查是否需要在目标环境执行 Alembic 迁移或 `scripts/migrate/` 中的结构修复脚本。更多排查记录见：

- `document/数据库版本不一致 的问题.md`
- `document/调度优化后报表.md`
- `document/OOB与NetFlow管理使用手册.md`

### 内网交换机 LLDP 发现不完整

需要确认交换机已开启 LLDP，并检查链路发现相关配置。参见：

- `document/华为交换机LLDP 开启给网管.txt`
- `document/LLDP 问题解决1.md`
- `document/服务器与交换机连接发现.md`

---

## License

本项目采用 [MIT License](LICENSE)。

Copyright (c) 2026 rigid007
