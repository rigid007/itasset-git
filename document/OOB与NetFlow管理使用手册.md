# 带外管理（OOB）与 NetFlow 流量采集 —— 使用手册

> 适用范围：IT 资产与运维管理平台（D:\asset）
> 相关模块：`blueprints/oob.py`、`services/oob_manager.py`、`tasks/oob_poll.py`、`blueprints/netflow.py`、`services/netflow_service.py`、`tasks/netflow_collect.py`
> 导航入口：顶部导航栏「带外管理」「NetFlow 流量」两个下拉菜单

---

## 一、总体概览

平台新增了两大「数据中心带外/流量」能力，二者互不依赖、可独立启用：

| 模块 | 定位 | 核心能力 | 权限 |
|------|------|----------|------|
| **带外管理（OOB）** | 不依赖主机操作系统，直接管理服务器 BMC | 电源控制、传感器/温度/功耗采集、BIOS 读取、SEL 日志持久化与告警联动 | 仅需登录（`@login_required`） |
| **NetFlow 流量** | 采集交换机/路由器上报的流记录，做流量分析 | NetFlow v5/v9、sFlow v5、NetStream 采集；Top 分析；AS/区域/DSCP 报表；对外会话 | `netflow:view` / `netflow:edit` |

---

## 二、带外管理（OOB）

### 2.1 架构与协议

- **首选 Redfish（RESTful HTTPS）**，失败时回退 **IPMI**（依赖 `pyghmi`）。
- 支持厂商：**Dell iDRAC、HPE iLO、华为 iBMC、联想 XCC、浪潮**，以及任何符合 Redfish 规范的 BMC。
- 凭据复用现有「凭据管理」模块（`/config/credential-management`），密码经 `CredentialEncryptor` 加密存储，调用时解密。

**数据模型**（`models/oob_models.py`）：

| 表 | 说明 |
|----|------|
| `bmc_controllers` | 每台物理服务器一条 BMC 控制器记录（IP/MAC/厂商/固件/BIOS/电源状态/凭据） |
| `bmc_sensors` | 传感器读数快照（温度/风扇/电压/功耗），带上下限阈值与状态 |
| `bmc_power_logs` | 电源操作审计日志（谁、何时、执行了什么动作、结果） |
| `bmc_event_logs` | 持久化的 BMC 事件日志（SEL / Lifecycle），带 `alerted` 标记用于告警联动 |

### 2.2 功能清单

| 功能 | 接口/入口 | 说明 |
|------|-----------|------|
| 控制器列表 | `GET /oob/` | 页面展示所有 BMC 控制器 |
| 控制器增删改查 | `GET/POST/PUT/DELETE /oob/api/controllers` | 绑定 `device_id`、`bmc_ip`、`vendor`、`credential_id` 等 |
| 单台立即轮询 | `GET /oob/api/controllers/<id>/refresh` | 手动触发一次采集 |
| 传感器读数 | `GET /oob/api/controllers/<id>/sensors` | 温度/风扇/电压/功耗历史 |
| 电源操作 | `POST /oob/api/controllers/<id>/power` | `power_on` / `power_off` / `graceful_off` / `reset` / `graceful_reset` / `nmi` |
| 电源审计日志 | `GET /oob/api/controllers/<id>/logs` | 操作记录 |
| 健康状态 | `GET /oob/api/controllers/<id>/health` | Redfish 聚合健康 + 功耗瓦数 |
| 网卡清单 | `GET /oob/api/controllers/<id>/network` | 主机 NIC 的 MAC/速率/状态 |
| BIOS 属性 | `GET /oob/api/controllers/<id>/bios` | 当前 + 待生效 BIOS 属性（`get_bios_attributes`） |
| 事件日志（实时） | `GET /oob/api/controllers/<id>/sel`（LogServices） | 实时 SEL / Lifecycle；注意 `/logs` 已被电源审计日志占用 |
| SEL 告警 | `GET /alert/list?metric_type=bmc_sel` | 跳转到告警页查看带外 SEL 告警 |

### 2.3 电源操作（ResetType 映射）

`services/oob_manager.py` 中 `RESET_TYPES`：

| 动作名 | Redfish ResetType |
|--------|-------------------|
| `power_on` | `On` |
| `power_off` | `ForceOff` |
| `graceful_off` | `GracefulShutdown` |
| `reset` | `ForceRestart` |
| `graceful_reset` | `GracefulRestart` |
| `nmi` | `Nmi` |

### 2.4 SEL 日志持久化 + 告警联动（核心）

轮询流程（`tasks/oob_poll.py::_poll_one`）：

1. **系统/电源**：Redfish `get_system()`，失败回退 IPMI；回写 `power_state`、`bios_version`、`model`、`serial_number` 及 Device 的 `power_status`。
2. **传感器**：逐条写 `BmcSensor`，并回写 Device 的 `temperature` / `power_consumption`；`warning`/`critical` 触发传感器告警。
3. **事件日志**：`get_logs(log_type='sel')` 读取 SEL/Lifecycle，按 `(message_id, log_time)` 去重后持久化到 `bmc_event_logs`；对 `critical/warning/emergency/alert/error` 级别生成 `AlertEvent(metric_type='bmc_sel')`。

告警联动（`_raise_log_alert`）：
- 关联启用的 `AlertRule(metric_type='bmc_sel')`；
- 进入**事件关联规则引擎**（`process_alert_correlation`：抑制/合并/升级/工单）；
- 未命中规则时做 24 小时去重合并；
- 新告警按 `NotificationConfig` 配置派发通知（模板支持 `{device} {ip} {severity} {message_id} {sensor_type} {event_id} {log_time} {entry_type} {description}` 等占位符）。

### 2.5 告警升级联动

- 入口：`/oob/escalations`（页面）+ `/oob/api/escalations`（JSON CRUD）。
- 复用 `AlertEscalation` 策略：未确认超时自动升级、加频推送、`auto_create_work_order` 自动建工单（见上一轮「升级日志/自动工单」）。

### 2.6 定时任务与配置

| 配置项 | 默认 | 说明 |
|--------|------|------|
| `OOB_ENABLED` | `1` | 是否启用带外轮询 |
| `OOB_POLL_INTERVAL_SEC` | `300` | BMC 轮询间隔（秒） |
| `OOB_TIMEOUT` | `10` | Redfish HTTP 超时（秒） |
| `OOB_VERIFY_SSL` | `0` | 是否校验证书（自签证书环境保持 0） |

调度（`scheduler.py`）：`poll_all_bmc` 每 300 秒执行一次。

### 2.7 使用步骤（带外管理）

1. **配置凭据**：进入「系统配置 → 凭据管理」，新增 iDRAC/iLO 的账号（用户名 + 密码，协议选 `https`）。
2. **添加控制器（页面操作）**：进入「带外管理 → BMC 控制器」，点击右上角 **「添加控制器」**，在弹窗中填写：
   - **绑定设备**：从资产设备下拉选择对应物理服务器（每台服务器仅可绑定一个 BMC，重复绑定会报错）；
   - **BMC 管理 IP**：BMC 独立管理网口的 IP（必填）；
   - **BMC MAC / 厂商 / 协议**：厂商选 `dell/hpe/huawei/lenovo/inspur/other`，协议默认 `redfish`（失败自动回退 IPMI）；
   - **凭据**：选择第 1 步创建的凭据（不填则轮询会跳过该控制器）；
   - **启用**：默认勾选，参与每 5 分钟定时轮询。
   保存后列表即出现该控制器；也可点击「编辑」修改、「删除」移除（级联删除其传感器与 SEL 日志）。
   > 等价 API：`POST /oob/api/controllers`（`device_id` / `bmc_ip` / `vendor` / `protocol` / `credential_id` / `enabled`）；下拉设备来源 `GET /oob/api/devices`，凭据来源 `GET /config/api/credentials`。
3. **等待/手动轮询**：调度器每 5 分钟轮询，或点击行内「轮询」按钮立即 `refresh` 单台。
4. **查看传感器/健康**：点击「传感器」展开温度、风扇、电压、功耗读数；健康/网卡/BIOS 通过对应 API 实时获取。
5. **电源操作**：点击「开/关/重启」按钮（会写 `bmc_power_logs` 审计）。
6. **查看 SEL 告警**：点击「带外 SEL 告警」跳转告警页，或「告警升级联动」配置升级策略。

---

### 2.8 对标 DCOS 带外「总览/备份/日志下载」的增强功能

参考 192.168.1.211（DCOS，`/data/dcos`）的带外管理能力，asset 在原有控制器/传感器/电源/SEL 基础上补充以下对等能力：

| 能力 | asset 入口 | 对标 DCOS | 说明 |
|------|-----------|-----------|------|
| **概览看板** | `/oob/overview`（导航「带外管理 → 概览看板」） | 带外总览页 | 机群卡片（总数/开机/总功耗/最高温度/待处理 SEL 严重）+ 电源状态分布、厂商分布、传感器状态三张 ECharts 图；底部内置「批量电源」面板。数据来自 `GET /oob/api/overview`（聚合 `bmc_controllers` + 每台最新 `bmc_sensors` 读数 + 未确认 SEL）。 |
| **配置备份 / 恢复** | `/oob/backup`（导航「带外管理 → 配置备份」） | 服务器备份 | 对单台控制器实时采集 Redfish 快照（系统信息 + BIOS 属性 + 网卡清单），存 `bmc_config_backups` 表（含 SHA256）。支持 JSON 下载、一键「恢复」（best-effort PATCH BIOS Settings，结果标注 applied/failed）。端点：`POST /oob/api/controllers/<id>/backup`、`GET /oob/api/backups`、`GET /oob/api/backups/<id>/download`、`POST /oob/api/backups/<id>/restore`。 |
| **SEL 日志导出** | `GET /oob/api/controllers/<id>/events/export?format=csv\|json` | 日志下载 | 将持久化 SEL 事件按 CSV/JSON 导出归档（支持 severity/limit 过滤）。 |
| **批量电源操作** | 概览看板底部面板 | 批量任务 | `POST /oob/api/controllers/batch-power` 入参 `{ids:[...], action}`，逐台执行 Redfish 电源动作并写 `bmc_power_logs`，返回每台成功/失败明细（无凭据或不可达均优雅失败，不抛 500）。 |

> DCOS 带外还包含 RAID 配置、巡检模板、临时账号、审批流、连线检查（lineCheck/LLDP）、节能模板等重生命周期能力；这些依赖具体厂商 Redfish 实现与更高权限，asset 暂未纳入，可在后续迭代按需在 `services/oob_manager.py` 扩展对应方法后接入。

### 2.9 固件升级（对标 DCOS「固件」）

导航「带外管理 → 固件升级」。基于 Redfish `UpdateService` 提供：

- **固件清单**：逐台读取 `UpdateService/FirmwareInventory`，列出组件名/版本/状态（`GET /oob/api/controllers/<id>/firmware`）。
- **批量升级**：勾选多台控制器提交固件包（URL 或本地上传），`POST /oob/api/controllers/<id>/firmware/upgrade` 触发 SimpleUpdate，任务记入 `bmc_firmware_jobs` 审计表（状态 pending/running/success/failed，可轮询）。
- **任务审计**：`GET /oob/api/firmware/jobs` 列出全部升级任务及结果。后台每 30 秒轮询 Redfish Task 自动回写状态（submitted→running→success/failed），也可 `POST /oob/api/firmware/jobs/<id>/refresh` 单台立即刷新。

> 注：实际刷写依赖目标 BMC 的 `UpdateService` 是否支持 SimpleUpdate（多为 Dell iDRAC/HPE iLO 支持）；不支持的厂商会返回明确错误而非静默失败。

### 2.10 BIOS 模板批量下发（对标 DCOS「BIOS 模板/批量下发」）

导航「带外管理 → BIOS 模板」。把一组 BIOS 属性固化成模板，一次下发到多台同型号服务器：

- **模板管理**：`GET/POST/DELETE /oob/api/bios/templates`，模板存 `bios_templates`（`attributes` 为 JSON 键值对，如 `{"BootMode":"Uefi","ProcVirtualization":"Enabled"}`）。
- **批量下发**：`POST /oob/api/bios/templates/<id>/apply` 入参 `{controller_ids:[...]}`，对每台控制器读取当前 BIOS（`GET /redfish/.../Bios`）后 best-effort PATCH 待改属性，返回每台 `{success, changed, failed}` 明细。
- **单台查看**：`GET /oob/api/controllers/<id>/bios` 读取当前 BIOS 属性与 Pending 值。

### 2.11 SAN / 光纤拓扑（对标 DCOS「存储光纤拓扑」，AntV G6 渲染）

导航「拓扑管理 → SAN / 光纤拓扑」。用与网络拓扑一致的 AntV G6 引擎渲染存储域：

- **数据模型**：`san_nodes`（FC 交换机/存储阵列/主机 HBA/网关，含 WWPN、厂商、分区 Zone）与 `san_links`（源/目的端口、速率、类型 fc/iscsi/fcoe、状态）。
- **G6 视图**：节点按类型着色、分区自动 `combos` 分组；链路按状态（up/down/degraded）着色、速率决定线宽；支持力导/环形/网格/径向四种布局、缩放/拖拽/适应、节点高亮邻居、详情模态、导出 PNG。
- **手动维护 + 示例**：`GET/POST /topology/api/san/nodes`、`GET/POST /topology/api/san/links`、`DELETE` 增删；`POST /topology/api/san/seed` 一键写入一组示例（含两分区 + ISL 互联），便于首体验。
- 等价网络拓扑（LLDP）见 2.7 节与「拓扑视图 (G6)」。

---

## 三、NetFlow 流量采集

### 3.1 架构与协议

- 每个启用的探针（`NetFlowProbe`）启动一个 **UDP 监听线程**（`NetFlowCollector`），常驻接收流量。
- 支持协议版本：**NetFlow v5、v9、sFlow v5、华为 NetStream**（NetStream 在 9020 端口使用 v5/v9 二进制编码，自动识别）。
- 数据批量缓冲（默认 10 秒 flush），持久化到 `netflow_records`。

**数据模型**（`models/netflow_models.py`）：

| 表 | 说明 |
|----|------|
| `netflow_probes` | 采集器配置（监听 IP/端口/版本/是否启用/收包计数） |
| `netflow_records` | 归一化流记录（源/目的 IP/端口、协议、TOS/DSCP、AS、TCP flags、包数、字节数、时间） |
| `netflow_apps` | 知名端口 → 应用名字典（种子数据） |
| `netflow_protocols` | IP 协议号 → 名称字典 |
| `netflow_dscps` | DSCP → 类名字典（AF/EF/CS 等 QoS 类） |
| `netflow_ases` | ASN → 名称/区域字典（常见运营商/云厂商） |

### 3.2 功能清单

| 功能 | 接口/入口 | 说明 |
|------|-----------|------|
| 流量分析首页 | `GET /netflow/` | 总流量/总包数/流记录/运行采集器卡片 + 趋势图 + Top 分析 |
| 探针增删改查 | `GET/POST/PUT/DELETE /netflow/api/probes` | 新建采集器后自动 `sync_probe` 拉起监听 |
| 探针重启 | `POST /netflow/api/probes/<id>/restart` | 重启单个监听线程 |
| 运行状态 | `GET /netflow/api/status` | 各采集器 running/packets/flows/last_error |
| 实时统计 | `GET /netflow/api/stats?minutes=15` | Top 源/目的/协议/端口 + 分钟趋势 |
| 流记录查询 | `GET /netflow/api/records` | 分页 + 按 src/dst/protocol/probe 过滤 |
| 应用/协议字典 | `GET /netflow/api/apps`、`/api/protocols` | 端口/协议号 → 名称 |
| 对外网段会话 | `GET /netflow/api/sessions` | Top 跨网段会话，`external` 标记对外 |
| AS/区域/TOS 报表 | `GET /netflow/report` + `/api/report?group=as|region|asregion|dscp` | 按 ASN/网段/区域/DSCP 聚合 |

### 3.3 协议解析细节

- **v5**：固定 48 字节记录，含 `src/dst AS`、`input/output SNMP`、`src/dst mask`、`tos`、`tcp_flags`、时间戳（boot uptime 换算 UTC）。
- **v9**：模板 + 数据流（template flowset / data flowset），字段类型映射见 `V9_FIELD_NAMES`（1~46、148~151）。
- **sFlow v5**：flow sample → IPv4/IPv6/raw-header 记录解析。
- **DSCP 映射**：`dscp_name()` 将 ToS 字节高 6 位映射到 AF11/EF/CSx 等类名。

### 3.4 权限 / 审计接入

- 所有接口用 `@permission_required('netflow:view')`（查询）或 `netflow:edit`（增删改，配合 `log_audit` 审计）。
- 权限已纳入角色体系：`admin` 全部、`operator/user/viewer` 含 `netflow:view`，`operator` 额外含 `netflow:edit`。

### 3.5 定时任务与配置

| 配置项 | 默认 | 说明 |
|--------|------|------|
| `NETFLOW_ENABLED` | `1` | 是否启用采集 |
| `NETFLOW_RETENTION_DAYS` | `30` | 流记录保留天数 |
| `NETFLOW_BUFFER_FLUSH_SEC` | `10` | 缓冲 flush 间隔（秒） |
| `NETFLOW_INTERNAL_SUBNETS` | `10.0.0.0/8,172.16.0.0/12,192.168.0.0/16` | 内网网段（用于「对外」判定） |

调度（`scheduler.py`）：
- 应用启动时立即 `start_netflow_collectors()` 拉起监听；
- 每日 00:05 cron 同步一次采集器；
- 每日 03:40 `netflow_cleanup()` 清理超期记录。

### 3.6 使用步骤（NetFlow）

1. **设备侧开启 NetFlow/sFlow 上报**：在交换机/路由器上配置导出器，指向本平台采集机 IP 和端口（默认 UDP 2055；sFlow 常见 6343）。
2. **添加采集器**：NetFlow 页面点「新增采集器」，填名称、监听 IP（`0.0.0.0` 表示监听所有网卡）、端口、版本（`v5`/`v9`/`both`/`sflow`/`netstream`）。
3. **确认运行**：采集器列表状态显示「运行中」，包数/流数持续增长即代表收到数据。
4. **查看分析**：首页查看总流量/趋势/Top 源/目的/协议/端口。
5. **钻取过滤**：URL 追加 `?probe=<id>` 按采集器下钻。
6. **报表**：进入「AS/区域/TOS 报表」，切换 `group` 参数查看按 ASN / 网段区域 / DSCP QoS 类聚合。

---

## 四、与 192.168.1.211 DCOS 平台的差异 / 可借鉴点

1. **NetFlow 字典表**（`netflow_apps`/`netflow_v5_protocol`/`netflow_dscp`）直接借鉴 DCOS 平台设计，作为只读种子数据。
2. **OOB 采用 Redfish 优先 + IPMI 回退**，兼容 Dell/HPE/华为/联想/浪潮多厂商，比单一 iDRAC 方案更通用。
3. **SEL 日志持久化到独立表**（`bmc_event_logs`）并接入现有告警规则引擎 + 通知 + 升级工单，形成闭环（DCOS 未必有此联动）。
4. **NetFlow 采集体积做成首页/看板卡片**、多时间窗切换，是 DCOS 的报表化增强。
5. 可继续借鉴 DCOS 的：**sFlow 计数器采样（counter sample）统计接口速率**、**AS 报表加国家地图/对外网段 Top 会话**（已有 `/api/sessions` 基础）。

---

## 五、常见问题（FAQ）

- **NetFlow 采集器启动报 `NameError: NetFlowProbe is not defined`**：已修复，`services/netflow_service.py` 第 25 行需导入 `NetFlowProbe`。
- **看不到带外/NetFlow 入口**：已补齐 `base.html` 顶部导航栏两个下拉菜单。
- **OOB 轮询报 `no credential configured`**：控制器未绑定 `credential_id`，先在凭据管理新增。
- **自签证书环境**：保持 `OOB_VERIFY_SSL=0`。
- **NetFlow 收不到数据**：确认设备导出器端口与探针 `port` 一致、防火墙放行 UDP、探针 `enabled=True`。

---

*文档生成时间：2026-08-22*
