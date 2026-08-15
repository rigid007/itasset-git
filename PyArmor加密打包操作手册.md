# PyArmor 代码加密打包操作手册（本项目：IT 资产与运维管理平台）

> 生成日期：2026-07-31
> 适用：Flask + APScheduler + SQLAlchemy + Redis + 前端静态资源（Babylon.js / ECharts）项目
> 验证环境：PyArmor 9.2.6（trial），Windows x86_64，Python 3.13

## 一、PoC 验证结论（已实测）

| 验证项 | 结果 | 说明 |
|--------|------|------|
| 自包含模块加密 + 运行 | ✅ | `demo.py` 加密后配合 `pyarmor_runtime_*.pyd`（编译型 C 扩展）正常输出，`fib(10)=55` |
| 真实子目录 `utils/` 递归加密 | ✅ | 22 个 `.py`（含较大的 `snmp_utils.py`）全部加密产出，结构完整 |
| 入口模式 `pyarmor gen app.py` | ⚠️ 仅加密了 `app.py` | 因本项目大量**延迟/动态导入**，静态依赖分析抓不全蓝图、models、tasks 等 |
| **推荐模式：递归整目录加密** | ✅（命令见第三节） | 覆盖全部 `.py`，含动态导入模块 |

**核心结论**：
1. PyArmor 对本项目**可行**，加密产物运行依赖编译型 `pyarmor_runtime`（逆向成本高）。
2. 必须用**递归整目录加密**（`-r` + 排除非源码），不能只给入口 `app.py`。
3. 加密只处理 `.py`；**前端 JS / HTML 模板 / 配置文件需另行拷贝或单独混淆**。

## 二、环境准备（隔离，不污染系统）

```bash
# 用 managed python 建独立 venv 并安装（推荐）
C:/Users/lenovo/.workbuddy/binaries/python/versions/3.13.12/python.exe -m venv C:/Users/lenovo/.workbuddy/binaries/python/envs/default
C:/Users/lenovo/.workbuddy/binaries/python/envs/default/Scripts/pip.exe install pyarmor

# 或直接在目标部署机：pip install pyarmor
```

> **trial 限制（实测）**：trial/non-profits 版有 "Can't obfuscate big script and mix str" 限制、无 RFT/BCC/CI 模式、运行时目录带 `000000` watermark。**生产闭源交付必须购买正式 PyArmor 授权**，否则大文件会加密失败且无法做 license 绑定。

## 三、推荐加密命令（递归整目录）

```bash
pyarmor gen -O dist_enc -r ^
  --exclude "templates" --exclude "static" --exclude "uploads" ^
  --exclude "logs" --exclude "document" --exclude "manual_build" ^
  --exclude "dist" --exclude ".pyarmor_poc" --exclude "__pycache__" ^
  --exclude ".git" --exclude "venv" --exclude "node_modules" ^
  E:/asset
```

- `-r`：递归处理目录下所有 `.py`（含 blueprints / models / utils / tasks / services）。
- `--exclude`：排除非源码与不该加密的内容（静态资源、日志、文档、依赖、版本库）。
- 加密后的 `.py` 与 `pyarmor_runtime_xxxxxx/` 会写入 `dist_enc/`。

## 四、本项目特殊处理清单（务必逐项确认）

1. **动态 / 延迟导入**
   - APScheduler 的 `configure_scheduler()`、`create_app()` 中的蓝图注册都是运行时 import。递归整目录模式已把它们全部加密，无需额外配置。
   - 若改用入口模式（`gen app.py`）则**会漏加密**，切勿使用。

2. **Alembic 数据库迁移**
   - `migrations/`、`alembic/`、`alembic.ini` 均为 `.py`/配置，递归加密会包含迁移脚本。
   - 首次部署在 `dist_enc` 内执行：`flask db upgrade`（加密版迁移脚本可正常运行）。

3. **前端静态资源（不加密！）**
   - `static/js/babylon.js`、`echarts.min.js`、所有模板内的 JS 是明文，PyArmor 不处理。
   - 加密后需手动把 `templates/`、`static/`、`uploads/` 拷贝到 `dist_enc/`（见 `encrypt_build.bat`）。
   - 若要保护前端逻辑，需额外做 JS 混淆/压缩（如 terser / javascript-obfuscator），与本流程独立。

4. **运行依赖**
   - SQLite / Redis / SQLAlchemy 是运行时连接，加密不影响；部署机仍需 `pip install -r requirement.txt`。

5. **配置文件**
   - `config.py` 含密钥/数据库 URI，会被加密（好）；但 `requirement.txt`、`alembic.ini` 需拷贝到 `dist_enc`。

## 五、运行加密产物

```bash
cd dist_enc
pip install -r requirement.txt
python app.py          # pyarmor_runtime 必须在同目录，自动加载
```

- 启动后表现与明文版一致；日志仍按已配置的 5MB 轮转 + 180 天保留输出到 `logs/app.log`。
- 调试只能靠日志与运行时报错（源码已不可读），故务必保留明文源码在 Git。

## 六、给客户做 license 绑定（防扩散 / 到期）

> 需**正式 PyArmor 授权**（trial 不支持）。

```bash
# 生成绑定机器指纹 + 30 天到期的 license
pyarmor licenses --expired 2026-12-31 --bind-disk "100304PBN20801" customerA
# 把生成的 licenses/customerA/pyarmor_runtime_xxxxxx/ 覆盖到交付包的 runtime 目录
```

这样客户机器不符 / 到期即无法运行。

## 七、CI / 一键加密脚本

已生成 `encrypt_build.bat`（Windows，纯 ASCII 注释避免乱码），双击或命令行执行即完成"递归加密 + 拷贝静态资源 + 拷贝配置"。

CI 示例（GitHub Actions）：
```yaml
- run: pip install pyarmor
- run: pyarmor gen -O dist_enc -r --exclude "..." .
- run: xcopy templates dist_enc\templates /E /I /Y
```

## 八、回滚与风险

- **回滚**：加密产物与源码解耦，出问题时直接用 Git 中的明文重新部署即可；加密包不入库。
- **风险**：
  - 加密后无法断点调试源码，问题定位依赖日志（已具备轮转+180天）。
  - trial 版 watermark / 限制；生产必须正式授权。
  - 本项目若未来引入更多运行时 `importlib.import_module` 动态加载，递归整目录模式已覆盖，无需特殊处理；若改为"按需从远程加载模块"则需额外 `--assert-call` 配置。
  - 多进程（gunicorn 多 worker）下 `pyarmor_runtime` 各进程独立加载，无冲突。

## 九、何时考虑替代方案

| 场景 | 方案 |
|------|------|
| 需最强保护、可接受编译慢 + 踩坑 | **Nuitka**：`python -m nuitka --standalone --onefile app.py`，需 `--include-package=flask,apscheduler,sqlalchemy,redis` 并验证 SQLite/静态路径 |
| 只护核心算法 | **Cython**：核心模块 `setup.py` 编译为 `.so`，主体仍 `.py` |
| 仅分发、不要求加密 | PyInstaller（代码可被解包，不推荐用于闭源） |
