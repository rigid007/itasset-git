"""
services/event_monitor.py — 事件驱动监控接入层

传统监控依赖"轮询"（默认 5 分钟一次），设备离线的最坏发现延迟即一个轮询周期。
本模块通过 UDP 监听以下事件源，实现设备离线 / 在线的**秒级感知**：

1. SNMP Trap（端口 trap_port，默认 9162）：使用 pysnmp 解码真实 Trap，
   linkDown(.1.3.6.1.6.3.1.1.5.3) -> 离线，linkUp(.4) / coldStart(.1) -> 在线。
   若环境未安装 pysnmp，则降级为普通 UDP 监听（尽力按文本/IP 解析）。
2. Syslog（端口 syslog_port，默认 9514）：解析 RFC3164/5424 文本，
   命中 down/offline/unreachable 等关键字 -> 离线，up/online/recovered -> 在线。
3. JSON 心跳（与 Syslog 共用端口，以首字符 '{' 区分）：
   {"ip": "10.0.0.1", "status": "offline", "source": "zabbix", "message": "..."}
   这是最可靠的集成/测试方式，也可由外部系统主动推送状态。

收到事件后即时更新 Device.status 并写入 DeviceMonitorLog（monitor_type 标记来源），
供 SLA 与仪表盘使用。状态未变化时不写日志，避免 SLA 噪声。
"""
import json
import logging
import re
import socket
import threading
from datetime import datetime, timezone

from tasks.sla_calculator import DEVICE_STATUS_MONITOR_TYPES

logger = logging.getLogger(__name__)


class EventMonitor:
    def __init__(self, app=None, trap_port=9162, syslog_port=9514, enabled=True):
        self.app = app
        self.trap_port = trap_port
        self.syslog_port = syslog_port
        self.enabled = enabled
        self._threads = []
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self.received_count = 0
        self.last_event = None
        self.running = False
        self._pysnmp = False

    # ------------------------------------------------------------------ 控制
    def start(self):
        if self.running:
            return
        if not self.enabled:
            logger.info("事件监控未启用（enabled=False），跳过启动")
            return
        self._stop.clear()
        self.running = True

        # SNMP Trap 端口：优先用 pysnmp 真正解码；不可用则降级为普通 UDP 监听
        if self._try_start_pysnmp_trap():
            self._pysnmp = True
        else:
            t_trap = threading.Thread(
                target=self._udp_loop, args=('trap', self.trap_port), daemon=True)
            t_trap.start()
            self._threads.append(t_trap)

        # Syslog + JSON 心跳（共用端口，按内容区分）
        t_sys = threading.Thread(
            target=self._udp_loop, args=('syslog', self.syslog_port), daemon=True)
        t_sys.start()
        self._threads.append(t_sys)

        logger.info(
            "事件监控已启动: trap端口=%s(%s), syslog/heartbeat端口=%s",
            self.trap_port, 'pysnmp' if self._pysnmp else 'plain-udp', self.syslog_port)

    def stop(self):
        self._stop.set()
        self.running = False
        # 线程为 daemon 且 recv 有 1s 超时，会在下一轮退出；此处不强制 join
        self._threads = []
        logger.info("事件监控已停止")

    # ------------------------------------------------------------ pysnmp Trap
    def _try_start_pysnmp_trap(self):
        try:
            from pysnmp.entity import engine as snmp_engine_mod
            from pysnmp.entity import config as snmp_config
            from pysnmp.carrier.asyncore.dgram import udp
            from pysnmp.entity.rfc3413 import ntfrcv
        except Exception as e:
            logger.warning("未安装 pysnmp，SNMP Trap 降级为普通 UDP 监听: %s", e)
            return False

        try:
            snmp_engine = snmp_engine_mod.SnmpEngine()
            snmp_config.addTransport(
                snmp_engine, udp.domainName,
                udp.UdpTransport().openServerMode(('0.0.0.0', self.trap_port)))
            # 接收 v1/v2c 团体字（与设备侧一致即可；这里放通行配置）
            snmp_config.addV1System(snmp_engine, 'public', 'public')
            snmp_config.addV1System(snmp_engine, 'trap', 'trap')

            def _cb(state_reference, context_engine_id, context_name, var_binds, cb_ctx):
                try:
                    exec_ctx = snmp_engine.observer.getExecutionContext(
                        'rfc3412.receiveMessage')
                    src_ip = exec_ctx['transportAddress'][0]
                except Exception:
                    src_ip = None
                status = None
                detail = []
                for oid, val in var_binds:
                    o = str(oid)
                    v = str(val)
                    detail.append(f"{o}={v}")
                    # snmpTrapOID.0 指示 Trap 类型
                    if o == '1.3.6.1.6.3.1.1.4.1.0':
                        if v.endswith('.1.3.6.1.6.3.1.1.5.3') or v.endswith('5.3'):
                            status = 'offline'   # linkDown
                        elif v.endswith('.1.3.6.1.6.3.1.1.5.4') or v.endswith('5.4'):
                            status = 'online'    # linkUp
                        elif v.endswith('.1.3.6.1.6.3.1.1.5.1') or v.endswith('5.1'):
                            status = 'online'    # coldStart（设备重启后恢复）
                if status is None:
                    # 兜底：从可读内容里按关键字判定
                    blob = ' '.join(detail).lower()
                    if 'linkdown' in blob or 'down' in blob:
                        status = 'offline'
                    elif 'linkup' in blob or 'up' in blob:
                        status = 'online'
                if src_ip and status:
                    self.apply_device_event(src_ip, status, 'trap',
                                            '; '.join(detail[:6]))

            ntfrcv.NotificationReceiver(snmp_engine, _cb)
            snmp_engine.transportDispatcher.jobStarted(1)

            def _loop():
                try:
                    snmp_engine.transportDispatcher.runDispatcher()
                except Exception as e:
                    if not self._stop.is_set():
                        logger.error("pysnmp Trap 调度器异常退出: %s", e)

            t = threading.Thread(target=_loop, daemon=True)
            t.start()
            self._threads.append(t)
            return True
        except Exception as e:
            logger.error("启动 pysnmp Trap 接收失败，降级为普通 UDP: %s", e)
            return False

    # -------------------------------------------------------------- UDP 监听
    def _udp_loop(self, kind, port):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(('0.0.0.0', port))
        except Exception as e:
            logger.error("事件监控绑定 %s 端口 %s 失败: %s", kind, port, e)
            return
        sock.settimeout(1.0)
        while not self._stop.is_set():
            try:
                data, addr = sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                self._handle(kind, data, addr)
            except Exception as e:
                logger.warning("处理 %s 事件异常: %s", kind, e)
        try:
            sock.close()
        except Exception:
            pass

    # -------------------------------------------------------------- 事件解析
    def _handle(self, kind, data, addr):
        text = data.decode('utf-8', errors='replace').strip()
        ip = None
        status = None
        source = kind
        message = text

        # 1) JSON 心跳（首字符为 '{'）
        if text.startswith('{'):
            try:
                obj = json.loads(text)
                ip = obj.get('ip') or obj.get('device_ip')
                raw = str(obj.get('status', '')).lower()
                if raw in ('online', 'up', '1', 'true'):
                    status = 'online'
                elif raw in ('offline', 'down', '0', 'false'):
                    status = 'offline'
                source = obj.get('source', kind)
                message = obj.get('message', text)
            except json.JSONDecodeError:
                pass

        # 2) 文本 / syslog：提取 IP 与关键字
        if ip is None:
            ip = self._extract_ip(text) or (addr[0] if addr else None)
        if status is None:
            status = self._keyword_status(text)

        if not ip or status is None:
            logger.debug("忽略无法解析的 %s 事件: %s", kind, text[:120])
            return

        self.apply_device_event(ip, status, source, message)

    @staticmethod
    def _extract_ip(text):
        m = re.search(r'\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b', text)
        return m.group(1) if m else None

    @staticmethod
    def _keyword_status(text):
        low = text.lower()
        down_kw = ['link down', 'linkdown', ' is down', 'down', 'offline',
                   'unreachable', 'timeout', 'lost', '链路中断', '宕机', '离线']
        up_kw = ['link up', 'linkup', ' is up', 'up', 'online', 'reachable',
                 'recovered', 'restored', '链路恢复', '上线']
        for k in down_kw:
            if k in low:
                return 'offline'
        for k in up_kw:
            if k in low:
                return 'online'
        return None

    # -------------------------------------------------------------- 应用事件
    def apply_device_event(self, ip, status, source, message=None):
        """将一次设备状态事件落地：更新 Device.status 并写 DeviceMonitorLog。

        状态未变化时不写日志（仅刷新 last_checked），避免 SLA 噪声。
        返回命中的 Device 对象，未匹配到设备返回 None。
        """
        if self.app is None:
            logger.warning("事件监控未绑定 app，无法应用事件")
            return None
        from models.models import Device, DeviceMonitorLog
        from extensions import db

        with self.app.app_context():
            device = Device.query.filter(
                (Device.management_ip == ip) | (Device.ip_address == ip)
            ).first()
            if not device:
                logger.debug("事件来源 IP %s 未匹配到设备，忽略", ip)
                return None
            old = device.status
            new = status
            now = datetime.utcnow()
            changed = (old != new)
            if not changed:
                device.last_checked = now
                db.session.commit()
            else:
                device.status = new
                device.last_checked = now
                db.session.add(DeviceMonitorLog(
                    device_id=device.id,
                    device_ip=ip,
                    old_status=old,
                    new_status=new,
                    is_online=(new == 'online'),
                    monitor_type=source if source in DEVICE_STATUS_MONITOR_TYPES
                    else 'event',
                    error_message=message,
                ))
                # 设备状态改变：告警信息写入系统日志
                from models.config_models import SystemLog
                db.session.add(SystemLog(
                    timestamp=now,
                    level='warning' if new == 'offline' else 'info',
                    module='event_monitor',
                    source=f'device:{device.id}',
                    message=f'设备 {device.name} 状态变化: {old} -> {new} (来源: {source})',
                    details=json.dumps({
                        'event_source': source,
                        'event_message': message,
                        'alert_title': (
                            f'设备离线: {device.name}' if new == 'offline'
                            else f'设备恢复: {device.name}'
                        ),
                        'severity': 'critical' if new == 'offline' else 'info',
                        'ip': ip,
                    }, ensure_ascii=False),
                ))
                db.session.commit()
                logger.info("事件驱动更新设备 %s (%s) 状态: %s -> %s (来源:%s)",
                            device.name, ip, old, new, source)

            with self._lock:
                self.received_count += 1
                self.last_event = {
                    'ip': ip, 'status': status, 'source': source,
                    'device': device.name, 'changed': changed,
                    'at': now.isoformat(),
                }
            return device


# 全局单例
event_monitor = EventMonitor()


def start_event_monitor(app):
    """应用启动时调用：根据配置初始化并启动事件监控。"""
    from config import Config
    em = event_monitor
    em.app = app
    em.enabled = getattr(Config, 'EVENT_MONITOR_ENABLED', True)
    em.trap_port = getattr(Config, 'EVENT_MONITOR_TRAP_PORT', 9162)
    em.syslog_port = getattr(Config, 'EVENT_MONITOR_SYSLOG_PORT', 9514)
    try:
        em.start()
    except Exception as e:
        logger.error("启动事件监控失败: %s", e)
