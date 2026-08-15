# ITIL 合规评估报告（IT 资产与运维管理平台）

> 评估日期：2026-08-11
> 评估对象：`D:\asset`（Flask 资产管理/运维平台）
> 评估基准：ITIL 4 实践（Practices）与 ITSM 通用能力
> 验证方式：代码审查 + `compileall` 全量语法检查 + `smoke_test_itsm.py` 冒烟测试（15/15 通过）

---

## 一、总体结论

**结论：项目已具备 ITIL 4 服务管理的主要骨架，属于“中高成熟度”的 ITSM 平台，但尚未达到“完整合规”。**

- 事件/工单、问题、变更、服务目录、SLA、知识库/KEDB、CSI、CSAT、可用性、CMDB、资产全生命周期、供应商、监控事件关联、合规审计等 14 项核心实践中，**9 项已闭环、4 项基本可用、3 项缺失或薄弱**。
- 代码层面没有阻断性语法错误，冒烟测试 15/15 通过；但存在若干结构性缺陷（重复定义、死代码、循环内提交、双迁移目录等），属于“能跑但需重构”状态。

| 维度 | 评分（满分 5） | 说明 |
| --- | --- | --- |
| ITIL 流程覆盖 | 4.0 | 事件/问题/变更/SLA/知识/CSI 主流程齐全 |
| 数据模型完整性 | 4.2 | CMDB 与资产管理模型丰富，关联关系清晰 |
| 代码质量 | 2.8 | 存在重复定义、死代码、巨型文件、循环内提交 |
| 工程化/可维护性 | 2.5 | 无双迁移目录、无测试目录、脚本散落根目录、无版本库 |
| 安全合规 | 3.8 | RBAC/CSRF/审计日志/富文本过滤齐全，但默认密码与注册策略需加固 |

---

## 二、ITIL 4 实践映射矩阵

### 1. 事件管理（Incident Management）—— 已实现 ⭐

- `WorkOrder`（work_order_type=incident）承载事件工单，含优先级/影响/紧急度矩阵、指派、挂起/恢复、解决/关闭/重开全生命周期。
- 告警系统（`AlertEvent`）可自动生成工单，事件关联引擎（`EventCorrelationRule`）支持去重/抑制/归一化/升级。
- SLA 策略自动匹配（`apply_sla_policy()`），`sla_monitor` 每 15 分钟检测违约。
- **差距**：无“重大事件（Major Incident）”标记与专项流程；事件→问题一键升级入口弱。

### 2. 问题管理（Problem Management）—— 已实现 ⭐

- `ProblemRecord` 含根因/解决方案/临时方案/严重度，支持关联工单与变更。
- 问题→已知错误（KEDB）→知识库文章三级联动已闭环（`mark-known-error`、`link-kb`）。
- **差距**：根因分析（RCA）报告模板化输出缺失。

### 3. 变更管理（Change Management）—— 已实现 ⭐

- `ChangeRequest` 支持 standard/normal/emergency 三类变更，含实施/回滚/测试计划。
- CAB 审批链（`CABConfig` 多阶段 any/all 审批模式）、冲突检测（`/change/<id>/conflicts`）、影响分析（`simulate_change_impact`）、变更日历。
- **差距**：变更“实施完成/回滚”状态流转与验证记录较粗；无发布（Release）管理承接。

### 4. 服务资产与配置管理（SACM / CMDB）—— 已实现 ⭐

- 设备/机柜/位置/接口/连接路径（`ConnectionPath`）建模完整，LLDP 自动发现 + 手工管理双通道。
- 3D 机房可视化、拓扑视图、资产与设备双轨关联。
- **差距**：配置项（CI）关系类型（依赖/冗余/备用）语义化不足。

### 5. 服务级别管理（SLA Management）—— 部分实现 ◐

- `SLAPolicy` 模型 + 工单 SLA 匹配 + SLA 报表 + 在线率/可用率计算已具备。
- **差距（本次已修复）**：SLA 策略**无管理界面**（只能随服务目录间接选择），无法新建/编辑/启停策略。

### 6. 知识管理（Knowledge Management）—— 已实现 ⭐

- `KnowledgeArticle`（草稿/发布/归档、浏览量/有用数、标签）+ KEDB 联动。
- **差距**：文章与工单/问题解决过程的自动沉淀入口弱。

### 7. 持续改进（Continual Improvement）—— 已实现 ⭐

- `CSIImprovement` 登记册（来源 problem/change/incident/audit/survey，基线→目标→实际值，MTTR/可用率度量）。
- 服务满意度（CSAT）调查、可用性仪表盘。

### 8. 监控与事件管理（Monitoring & Event Management）—— 已实现 ⭐

- 定时采集（设备状态/接口/性能指标/链路）、SNMP Trap / Syslog / 心跳事件驱动监控、阈值告警、升级策略、维护窗口、自动化修复（`AutomatedRemediation`）。

### 9. 资产管理（IT Asset Management）—— 已实现 ⭐

- 资产台账/折旧/总账（`AssetLedger`）/盘点（`AssetAudit`）/合同/软件许可/备件全生命周期。

### 10. 服务请求管理（Service Request Management）—— 部分实现 ◐

- 服务目录（`ServiceCatalog`）+ 工单类型 request 已存在，但**终端用户自助服务台门户缺失**（无面向普通用户的提单入口与工单跟踪页）。

### 11. 可用性管理（Availability Management）—— 已实现 ⭐

- 真实可用率采集（`collect_availability`）、`AvailabilityRecord`、可用性报表。

### 12. 容量与性能管理（Capacity & Performance Management）—— 基本可用 ◐

- 性能指标采集/阈值/预测/健康评分已具备；容量规划报表较弱。

### 13. 信息安全与合规（Security & Compliance）—— 基本可用 ◐

- RBAC（角色/权限/用户组）、审计日志、操作日志、合规框架与证据管理、富文本 XSS 过滤、CSRF 全局防护。
- **差距**：默认管理员密码 `admin123`、默认开放注册（`ALLOW_PUBLIC_REGISTRATION` 默认 true）风险较高。

### 14. 供应商与合同管理（Supplier & Contract）—— 已实现 ⭐

- `Supplier` 评级/交期/付款条款 + `Contract` + 软件许可。

### 未覆盖/薄弱实践（路线图）

| 实践 | 现状 | 建议 |
| --- | --- | --- |
| 发布与部署管理（Release Mgmt） | 无 | 在变更完成后增加发布记录/回滚验证 |
| 服务连续性管理（ITSCM） | 无 | 增加连续性计划/容灾演练记录表 |
| 财务管理（Financial Mgmt） | 资产成本有，无 IT 预算 | 增加服务成本归集与预算对比 |
| 服务台自助门户 | 弱 | 增加“我的工单”与自助提单页 |
| 重大事件管理 | 无 | 事件工单增加重大标记与专项状态（本次已补） |

---

## 三、代码质量审查结论

### 阻断性问题（无）

- 全量 `compileall` 通过，无语法错误。
- 冒烟测试 15/15 通过（事件关联、SLA 判定、KEDB 联动、CSI 状态机、可用率采集、影响模拟等）。

### 已发现并修复的缺陷

1. **`extensions.py` 重复定义 `db`**：文件前部定义 `db = SQLAlchemy(session_options={"expire_on_commit": False})`，文件尾部又执行 `db = SQLAlchemy()`，后者覆盖前者，导致 `expire_on_commit` 配置失效（commit 后属性被过期，触发懒加载）。
2. **`app.py` 与 `config.py` 配置逻辑重复**：SECRET_KEY / 数据库 URL 解析逻辑在两处各写一份，存在漂移风险；`app.py` 还残留双重 `if __name__ == '__main__'` 与未使用导入。
3. **`tasks/link_monitor.py` 老化链路清理循环内逐条 `commit`**：批量提交可降低 I/O 与锁竞争。
4. **死代码**：`task_scheduler.py`（旧调度器，一旦误启用会与 `scheduler.py` 形成双轮询）、`snmp_scanner.py`（引用未导入的 pysnmp 符号，运行必报 NameError）、`worker.py`（独立 Redis 消费者，未被应用引用）均已归档。
5. **双迁移目录**：根目录 `alembic/`（空 versions）与 `migrations/`（真实迁移）并存；实际加列走 `patch_schema.py` 幂等脚本，`flask db upgrade` 不用于全量迁移。
6. **根目录脚本泛滥**：20+ 一次性/运维脚本散落根目录，已归入 `scripts/`。

### 结构性优化建议（本轮已部分执行）

- 巨型蓝图文件（topology.py 5933 行、device.py 5008 行、config.py 4696 行）建议按“路由分组”拆分（如 topology: 发现/连接/可视化 三文件），属中长周期工作。
- `utils/utils.py` 与 `utils/snmp_utils.py` 职责重叠，建议统一 SNMP 封装入口。
- 引入 `ruff` 配置与 CI 检查（requirement.txt 已含 ruff，未配置）。
- 补充 `tests/` 目录，把冒烟测试迁入并纳入 pytest。

---

## 四、目录结构优化（本轮已执行）

```
asset/
├── app.py / wsgi.py / config.py / extensions.py     # 应用入口与核心
├── blueprints/   # 路由（30 蓝图）
├── models/       # 数据模型（按域拆分）
├── services/     # 业务服务（通知/事件监控/设备服务）
├── tasks/        # 定时任务（监控/链路/SLA/保留清理）
├── utils/        # 工具库（含 init_config_data.py 归入）
├── templates/ static/
├── scripts/      # 运维与一次性脚本（新增，替代根目录散落）
│   ├── ops/          # 数据清洗/诊断（dedup_connections 等）
│   ├── migrate/      # schema 修补/权限同步（patch_schema/sync_permissions）
│   ├── tests/        # 冒烟与专项测试
│   └── legacy/       # 死代码存档（task_scheduler/snmp_scanner/worker）
├── document/     # 文档（无扩展名文件已规范为 .md/.txt）
├── migrations/   # Alembic 迁移（真实迁移版本）
└── archive/      # 本轮清理出的临时垃圾（可确认后删除）
```

---

## 五、功能补全（本轮已实现）

1. **SLA 策略管理**：`/itsm/sla-policies` 新增策略列表、创建、编辑、启停、删除（受服务目录/工单引用保护），并挂入导航菜单；新增权限 `itsm:sla:manage`。
2. **重大事件标记**：工单新增 `is_major` 标记（幂等 schema 补丁 + 表单勾选 + 列表徽标与筛选 + 详情页快速切换）。

## 六、后续路线图（建议优先级）

1. 服务台自助门户（我的工单/自助提单）—— 用户价值最高
2. 发布管理（变更→发布→回滚验证）
3. 服务连续性管理（DR 演练记录）
4. 配置项关系语义化（依赖/冗余）
5. 巨型蓝图拆分 + ruff 规范化
6. 默认密码强制修改与注册策略收紧
