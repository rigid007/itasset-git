# -*- coding: utf-8 -*-
"""
backup_bmc_web.py
=================
通过浏览器自动化（Selenium + Edge/Chromium）对**未开放 Redfish API**的老旧
BMC / 管理控制台做配置备份（Web 控制台「导出配置」），结果写入与 Redfish
快照同表的 `bmc_config_backups`，保证 CMDB 里配置备份视角统一。

适用场景（OobManager.Redfish 无法覆盖时兜底）：
  - 早期 HPE iLO 3/4（Web 导出，无完整 Redfish 配置导出）
  - 部分国产 BMC / 白牌管理页
  - 某些交换机、存储的管理 Web 控制台

设计原则（遵守本项目铁律）：
  - 读设备快照：短 app context 内完成 -> 立即退出
  - 浏览器操作（网络 I/O）：在 context 之外进行，零 DB 连接占用
  - 仅写库时再开 context，写完 db.session.remove()
  - 不修改任何现有模型 / 蓝图，纯增量脚本

用法：
  # 备份全部启用且 vendor 已知的老设备
  python backup_bmc_web.py

  # 仅备份指定 controller id（逗号分隔）
  python backup_bmc_web.py --ids 12,15,33

  # 指定 Edge driver 路径（默认从环境变量 EDGE_DRIVER 或脚本同目录探测）
  python backup_bmc_web.py --driver /path/to/msedgedriver.exe

  # 试跑（不写库，仅打印会处理哪些设备）
  python backup_bmc_web.py --dry-run

依赖：selenium==4.41.0（已在 requirement.txt），msedgedriver.exe（项目已含）
"""
import argparse
import hashlib
import json
import logging
import os
import sys
import time
from datetime import datetime

# ---- 让脚本能 import 项目模块 ----
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
)
logger = logging.getLogger('backup_bmc_web')

# 默认 msedgedriver 位置（项目自带，Windows 64 位）
DEFAULT_DRIVER = os.path.join(ROOT, 'msedgedriver', 'win64', '151.0.4129.78', 'msedgedriver.exe')


# ======================================================================
# 阶段 1：读取待处理设备（短 context，读完即释放）
# ======================================================================
def load_targets(ids=None):
    """返回 [(controller_id, bmc_ip, vendor, username, password), ...]"""
    from models.oob_models import BmcController
    from models.config_models import Credential

    # 优先复用调度器传入的 app，否则回退到 import
    app = _APP_REF
    if app is None:
        from app import app

    targets = []
    with app.app_context():
        q = BmcController.query.filter_by(enabled=True)
        if ids:
            q = q.filter(BmcController.id.in_(ids))
        for c in q.all():
            cred = Credential.query.get(c.credential_id) if c.credential_id else None
            pw = cred.get_password() if cred else ''
            user = cred.username if cred else ''
            # 只处理确实没有 Redfish 能力、或明确靠 Web 导出的设备
            targets.append({
                'controller_id': c.id,
                'bmc_ip': c.bmc_ip,
                'vendor': (c.vendor or '').lower(),
                'username': user,
                'password': pw,
            })
    return targets


# ======================================================================
# 阶段 2：浏览器自动化（context 之外，纯网络 I/O）
# ======================================================================
def build_driver(driver_path, download_dir):
    """构建 Edge(Chromium) 无头驱动，并将下载定向到 download_dir。

    download_dir 用于捕获 BMC Web 控制台「导出配置」生成的文件
    （iDRAC/iLO/iBMC 导出为 XML/JSON 下载，而非页面内展示）。
    """
    from selenium import webdriver
    from selenium.webdriver.edge.options import Options
    from selenium.webdriver.edge.service import Service

    opts = Options()
    opts.add_argument('--headless=new')
    opts.add_argument('--no-sandbox')
    opts.add_argument('--disable-dev-shm-usage')
    opts.add_argument('--disable-gpu')
    opts.add_argument('--ignore-certificate-errors')   # BMC 多为自签证书
    opts.add_argument('--window-size=1920,1080')

    # Edge/Chromium 下载偏好：禁用弹窗、固定目录、不询问
    prefs = {
        'download.default_directory': download_dir,
        'download.prompt_for_download': False,
        'download.directory_upgrade': True,
        'safebrowsing.enabled': False,
        'profile.default_content_settings.popups': 0,
    }
    opts.add_experimental_option('prefs', prefs)

    if driver_path and os.path.exists(driver_path):
        service = Service(executable_path=driver_path)
        return webdriver.Edge(service=service, options=opts)
    # 否则依赖 PATH / Selenium Manager 自动定位
    return webdriver.Edge(options=opts)


def _wait_download(download_dir, timeout=30, prefix=None):
    """等待下载目录出现新文件（非 .crdownload 临时态），返回最新文件路径。"""
    import glob
    deadline = time.time() + timeout
    seen = set(glob.glob(os.path.join(download_dir, '*')))
    while time.time() < deadline:
        cur = set(glob.glob(os.path.join(download_dir, '*')))
        new = cur - seen
        # 过滤掉 Chromium 正在写入的临时文件
        done = [f for f in new
                if not f.endswith('.crdownload') and os.path.isfile(f)
                and (prefix is None or os.path.basename(f).startswith(prefix))]
        if done:
            # 取最新修改的一个
            return max(done, key=os.path.getmtime)
        time.sleep(1)
    raise TimeoutError('导出文件下载超时')


def _read_exported_file(path):
    """读取 BMC 导出的配置文件，尽量解析为结构化 dict；解析失败则保留原文。"""
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as fh:
            raw = fh.read()
    except Exception as e:
        return {'raw_error': str(e)}
    # 尝试 JSON
    try:
        return {'format': 'json', 'data': json.loads(raw)}
    except (ValueError, TypeError):
        pass
    # 尝试 XML -> 保留原文 + 标记
    if raw.lstrip().startswith('<'):
        return {'format': 'xml', 'raw': raw}
    return {'format': 'text', 'raw': raw}


def _wait(drv, by, value, timeout=20):
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    return WebDriverWait(drv, timeout).until(EC.presence_of_element_located((by, value)))


def _login_generic(drv, base, user, pw):
    """通用登录：覆盖大多数 BMC Web 控制台。"""
    from selenium.webdriver.common.by import By
    drv.get(base)
    time.sleep(2)
    # 用户名
    for sel in ['id=userid', 'id=userName', 'name=userName', 'id=username',
                'input[type=text]', 'input[name=username]']:
        try:
            el = drv.find_element(By.CSS_SELECTOR, sel)
            el.clear(); el.send_keys(user)
            break
        except Exception:
            continue
    # 密码
    for sel in ['id=password', 'name=password', 'input[type=password]']:
        try:
            el = drv.find_element(By.CSS_SELECTOR, sel)
            el.clear(); el.send_keys(pw)
            break
        except Exception:
            continue
    # 提交
    for sel in ['id=btnOK', 'id=submit', 'button[type=submit]', '#loginButton']:
        try:
            el = drv.find_element(By.CSS_SELECTOR, sel)
            el.click()
            break
        except Exception:
            continue
    time.sleep(3)


def backup_dell_idrac(drv, base, user, pw, download_dir):
    """iDRAC9：Configuration -> Export -> 导出整配置为 JSON/XML 文件（下载）。"""
    from selenium.webdriver.common.by import By
    _login_generic(drv, base, user, pw)
    drv.get(base.rstrip('/') + '/exportImport.html')
    time.sleep(3)
    # 选择「导出全部配置」
    for sel in ['#exportAll', '#exportServer', 'input[value=ExportAll]']:
        try:
            drv.find_element(By.CSS_SELECTOR, sel).click()
            break
        except Exception:
            continue
    # 点击导出按钮
    for sel in ['#exportBtn', '#export', 'button[name=export]']:
        try:
            drv.find_element(By.CSS_SELECTOR, sel).click()
            break
        except Exception:
            continue
    path = _wait_download(download_dir, timeout=40)
    cfg = _read_exported_file(path)
    cfg.update({'method': 'idrac_web_export', 'exported_at': datetime.now().isoformat()})
    return cfg


def backup_hpe_ilo(drv, base, user, pw, download_dir):
    """HPE iLO：Administration -> Configuration -> 导出/下载配置文件。"""
    from selenium.webdriver.common.by import By
    _login_generic(drv, base, user, pw)
    drv.get(base.rstrip('/') + '/html/administration.html')
    time.sleep(3)
    # 点击导出（不同 iLO 版本文案差异大，按通用按钮文本兜底）
    clicked = False
    for txt in ['Export', 'Download', '导出', '下载']:
        try:
            btn = drv.find_element(By.XPATH, f"//button[contains(.,'{txt}')]")
            btn.click()
            clicked = True
            break
        except Exception:
            continue
    if not clicked:
        raise RuntimeError('iLO 未找到导出按钮')
    path = _wait_download(download_dir, timeout=40)
    cfg = _read_exported_file(path)
    cfg.update({'method': 'ilo_web_export', 'exported_at': datetime.now().isoformat()})
    return cfg


def backup_huawei_ibmc(drv, base, user, pw, download_dir):
    """华为 iBMC：配置 -> 备份与恢复 -> 导出配置文件。"""
    from selenium.webdriver.common.by import By
    _login_generic(drv, base, user, pw)
    drv.get(base.rstrip('/') + '/#/config/backup')
    time.sleep(3)
    try:
        drv.find_element(By.XPATH, "//button[contains(.,'导出')]").click()
    except Exception:
        raise RuntimeError('iBMC 未找到导出按钮')
    path = _wait_download(download_dir, timeout=40)
    cfg = _read_exported_file(path)
    cfg.update({'method': 'ibmc_web_export', 'exported_at': datetime.now().isoformat()})
    return cfg


VENDOR_DISPATCH = {
    'dell': backup_dell_idrac,
    'hp': backup_hpe_ilo,
    'hpe': backup_hpe_ilo,
    'huawei': backup_huawei_ibmc,
}


def run_browser_backup(target, driver_path, workdir=None):
    """对单台设备执行浏览器备份，返回 config dict；失败抛异常。

    workdir: 临时下载目录（默认系统临时目录下的 bmc_web_backup/<cid>）。
    备份完成后该目录会被清理，避免磁盘堆积。
    """
    import shutil
    import tempfile

    base = 'https://' + (target['bmc_ip'] or '')
    vendor = target['vendor']
    handler = VENDOR_DISPATCH.get(vendor)
    if not handler:
        raise ValueError(f"vendor={vendor!r} 暂不支持 Web 备份，请走 Redfish 路径")

    # 下载目录：每台设备独立，避免并发/串扰
    if workdir:
        download_dir = workdir
    else:
        download_dir = os.path.join(
            tempfile.gettempdir(), 'bmc_web_backup', str(target['controller_id']))
    os.makedirs(download_dir, exist_ok=True)

    drv = build_driver(driver_path, download_dir)
    try:
        cfg = handler(drv, base, target['username'], target['password'], download_dir)
        # 补充设备维度信息，形成完整快照
        cfg['bmc_ip'] = target['bmc_ip']
        cfg['vendor'] = vendor
        cfg['source'] = 'web_console'
        cfg['exported_file'] = os.path.basename(
            [f for f in os.listdir(download_dir) if not f.endswith('.crdownload')][-1]) \
            if any(f.endswith(('.json', '.xml', '.cfg', '.txt')) for f in os.listdir(download_dir)) else None
        return cfg
    finally:
        try:
            drv.quit()
        except Exception:
            pass
        # 清理下载目录（保留至多一个最新文件已并入 cfg，原始文件可删）
        try:
            shutil.rmtree(download_dir, ignore_errors=True)
        except Exception:
            pass
        except Exception:
            pass


# ======================================================================
# 阶段 3：写库（重新进入 context，写完释放）
# ======================================================================
def save_backup(controller_id, config, operator='automation'):
    from models.oob_models import BmcConfigBackup
    from extensions import db

    # 优先复用调度器传入的 app
    app = _APP_REF
    if app is None:
        from app import app

    payload = json.dumps(config, ensure_ascii=False, indent=2)
    checksum = hashlib.sha256(payload.encode('utf-8')).hexdigest()
    with app.app_context():
        rec = BmcConfigBackup(
            controller_id=controller_id,
            name=f"web_backup_{datetime.now():%Y%m%d_%H%M%S}",
            config_json=payload,
            checksum=checksum,
            operator=operator,
        )
        db.session.add(rec)
        db.session.commit()
        db.session.remove()
        return rec.id


# ======================================================================
# 主流程
# ======================================================================
def main():
    ap = argparse.ArgumentParser(description='BMC Web 控制台配置浏览器备份')
    ap.add_argument('--ids', help='指定 controller id，逗号分隔')
    ap.add_argument('--driver', default=os.getenv('EDGE_DRIVER', DEFAULT_DRIVER))
    ap.add_argument('--dry-run', action='store_true', help='只打印待处理设备，不操作')
    ap.add_argument('--operator', default='automation')
    args = ap.parse_args()

    ids = None
    if args.ids:
        ids = [int(x) for x in args.ids.split(',') if x.strip()]

    targets = load_targets(ids)
    if not targets:
        logger.warning('没有符合条件的 BMC 设备需要处理')
        return

    logger.info('待处理设备数: %d', len(targets))
    for t in targets:
        logger.info('  - id=%s vendor=%s ip=%s', t['controller_id'], t['vendor'], t['bmc_ip'])

    if args.dry_run:
        logger.info('--dry-run 模式，未执行任何操作')
        return

    ok, fail = 0, 0
    for t in targets:
        try:
            logger.info('开始浏览器备份 id=%s (%s)', t['controller_id'], t['bmc_ip'])
            cfg = run_browser_backup(t, args.driver)
            rid = save_backup(t['controller_id'], cfg, args.operator)
            logger.info('  成功，备份记录 id=%s', rid)
            ok += 1
        except Exception as e:
            logger.error('  失败 id=%s: %s', t['controller_id'], e)
            fail += 1

    logger.info('完成：成功 %d，失败 %d', ok, fail)


# ======================================================================
# 调度集成入口（供 APScheduler 调用，签名与本项目其他 task 一致）
# ======================================================================
def backup_all_bmc_web(app, driver_path=None, operator='scheduler'):
    """APScheduler 任务入口：签名 (app,) 与项目其他 task 一致。

    注意：本函数内部自行管理 app context（读/写分离），
    不依赖调用方是否已 push context，符合「网络 I/O 期间不持有 DB 连接」铁律。
    """
    global _APP_REF
    _APP_REF = app
    ids = None
    drv = driver_path or os.getenv('EDGE_DRIVER', DEFAULT_DRIVER)

    targets = load_targets(ids)
    if not targets:
        logger.info('[scheduler] 无启用的 BMC 设备需要处理')
        return 0

    ok = fail = 0
    for t in targets:
        try:
            cfg = run_browser_backup(t, drv)
            save_backup(t['controller_id'], cfg, operator)
            ok += 1
        except Exception as e:
            logger.error('[scheduler] 备份失败 id=%s: %s', t['controller_id'], e)
            fail += 1
    logger.info('[scheduler] BMC Web 备份完成：成功 %d，失败 %d', ok, fail)
    return ok


# 让 backup_all_bmc_web 内部复用已传入的 app，避免重复 import 导致上下文不一致
_APP_REF = None


if __name__ == '__main__':
    main()
