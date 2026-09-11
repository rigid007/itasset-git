# services/netflow_service.py
"""NetFlow v5 / v9 UDP collector service.

Design notes (mapped from the DCOS platform's netflow module):
  * The remote platform runs a Java NetflowServer.jar that binds UDP 2055
    (NetFlow v5), 6343 (sFlow) and 9020 (NetStream), persists to MySQL
    (oobsdata) and time-series to InfluxDB. It ships three dictionary tables:
    netflow_app (port->app), netflow_v5_protocol (protocol#->name) and
    netflow_dscp (DSCP->class).
  * We mirror that: one listener thread per NetFlowProbe row (v5/v9/both),
    normalized records persisted via the project central `db`, and the same
    three dictionaries seeded in the DB so reports can join port/protocol/dscp.

No third-party dependency is required: the parser uses only the Python
standard library (socket / struct / threading), and persistence reuses the
project's get_bg_session().
"""
import logging
import os
import socket
import struct
import threading
from datetime import datetime, timezone
from sqlalchemy import or_

from extensions import get_bg_session
from models.netflow_models import NetFlowProbe, NetFlowRecord

logger = logging.getLogger(__name__)

# NetFlow v9 field type -> field name (for debugging / future use).
V9_FIELD_NAMES = {
    1: 'IN_BYTES', 2: 'IN_PKTS', 3: 'FLOWS', 4: 'PROTOCOL', 5: 'SRC_TOS',
    6: 'TCP_FLAGS', 7: 'L4_SRC_PORT', 8: 'IPV4_SRC_ADDR', 9: 'SRC_MASK',
    10: 'INPUT_SNMP', 11: 'L4_DST_PORT', 12: 'IPV4_DST_ADDR', 13: 'DST_MASK',
    14: 'OUTPUT_SNMP', 15: 'IPV4_NEXT_HOP', 16: 'SRC_AS', 17: 'DST_AS',
    21: 'LAST_SWITCHED', 22: 'FIRST_SWITCHED', 27: 'IPV6_SRC_ADDR',
    28: 'IPV6_DST_ADDR', 32: 'ICMP_TYPE', 38: 'ENGINE_TYPE', 39: 'ENGINE_ID',
    40: 'FLOW_SAMPLER_ID', 46: 'IPV6_NEXT_HOP',
    148: 'FLOW_START_SECONDS', 149: 'FLOW_END_SECONDS',
    150: 'FLOW_START_MICROSECONDS', 151: 'FLOW_END_MICROSECONDS',
}

# IANA protocol numbers -> names (mirrors the remote netflow_v5_protocol table).
# Common operator / cloud ASN dictionary (mirrors remote netflow_app spirit).
ASN_DICTIONARY = {
    4134: ('CHINANET-BACKBONE', '中国电信'),
    4837: ('CHINA169-BACKBONE', '中国联通'),
    9808: ('CMNET', '中国移动'),
    9929: ('CN2', '中国联通CN2'),
    4538: ('CERNET', '教育网'),
    45090: ('Tencent', '腾讯云'),
    37963: ('HUAWEI-CLOUD', '华为云'),
    45102: ('Alibaba-US', '阿里云'),
    45009: ('CT-Fujian', '电信-福建'),
    13335: ('Cloudflare', 'Cloudflare'),
    15169: ('Google', 'Google'),
    16509: ('Amazon', 'AWS'),
}


def dscp_name(tos):
    """Map a ToS byte to a DSCP class name (6 high bits)."""
    if tos is None:
        return None
    try:
        tos = int(tos) & 0xFF
    except (TypeError, ValueError):
        return None
    dscp = (tos >> 2) & 0x3F
    names = {
        0: 'Default/BE', 8: 'CS1', 10: 'AF11', 12: 'AF12', 14: 'AF13',
        16: 'CS2', 18: 'AF21', 20: 'AF22', 22: 'AF23', 24: 'CS3',
        26: 'AF31', 28: 'AF32', 30: 'AF33', 32: 'CS4', 34: 'AF41',
        36: 'AF42', 38: 'AF43', 40: 'CS5', 46: 'EF', 48: 'CS6', 56: 'CS7',
    }
    if dscp in names:
        return names[dscp]
    # some exporters write the raw DSCP value into the whole ToS byte
    if tos in names:
        return names[tos]
    return 'DSCP-%d' % dscp


PROTOCOL_NAMES = {
    0: 'HOPOPT', 1: 'ICMP', 2: 'IGMP', 4: 'IP', 6: 'TCP', 8: 'EGP',
    9: 'IGP', 17: 'UDP', 41: 'IPv6', 47: 'GRE', 50: 'ESP', 51: 'AH',
    58: 'ICMPv6', 89: 'OSPF', 112: 'VRRP', 115: 'L2TP', 132: 'SCTP',
    136: 'UDPLite',
}


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _netflow_enabled():
    """Return False when NETFLOW_ENABLED config/env is explicitly disabled."""
    try:
        from flask import current_app
        return bool(current_app.config.get('NETFLOW_ENABLED', True))
    except RuntimeError:
        return os.environ.get('NETFLOW_ENABLED', '1') == '1'


def resolve_device_for_ip(session, ip):
    """Map an IP to a Device (device.ip_address / management_ip / bmc_ip / interface.ip_address)."""
    if not ip:
        return None
    from models.models import Device, Interface
    dev = (session.query(Device)
           .filter(or_(Device.ip_address == ip,
                       Device.management_ip == ip,
                       Device.bmc_ip == ip))
           .first())
    if dev:
        return dev
    iface = session.query(Interface).filter(Interface.ip_address == ip).first()
    if iface:
        return session.get(Device, iface.device_id)
    return None


def get_app_map(session=None):
    """Return {(port, protocol): app_name} from the seeded NetFlowApp dictionary."""
    from models.netflow_models import NetFlowApp
    close = session is None
    if session is None:
        session = get_bg_session()
    try:
        rows = session.query(NetFlowApp).all()
        return {(r.port, (r.protocol or 'TCP').upper()): r.app_name for r in rows}
    finally:
        if close:
            session.close()


def app_name_for(port, protocol, app_map=None):
    """Resolve a well-known port/protocol to an application name."""
    if not port:
        return None
    if app_map is None:
        app_map = get_app_map()
    proto = 'UDP' if protocol == 17 else 'TCP' if protocol == 6 else None
    if proto is None:
        return None
    return app_map.get((int(port), proto))


def load_ip_device_map(session=None):
    """Return {ip: (device_id, device_name)} from assets + interface IPs."""
    from models.models import Device, Interface
    close = session is None
    if session is None:
        session = get_bg_session()
    try:
        m = {}
        def _put(ip, dev):
            if not ip:
                return
            m[ip] = (dev.id, dev.name)
            if ':' not in ip:
                parts = ip.split('.')
                m['.'.join(parts[:3]) + '.0/24'] = (dev.id, dev.name)

        for dev in session.query(Device).all():
            for ip in (dev.ip_address, dev.management_ip, dev.bmc_ip):
                _put(ip, dev)
        for iface in session.query(Interface).all():
            if iface.ip_address and iface.ip_address not in m:
                dev = session.get(Device, iface.device_id)
                if dev:
                    _put(iface.ip_address, dev)
        return m
    finally:
        if close:
            session.close()


def _ip4_int(v):
    try:
        return socket.inet_ntop(socket.AF_INET, struct.pack('>I', v))
    except OSError:
        return None


def _ip_from_bytes(b):
    if not b:
        return None
    try:
        if len(b) == 4:
            return socket.inet_ntop(socket.AF_INET, b)
        if len(b) == 16:
            return socket.inet_ntop(socket.AF_INET6, b)
    except OSError:
        return None
    return b.hex()
def _flow_time(first_last_ms, unix_secs, sys_uptime_ms):
    """Convert a v5 First/Last (ms since device boot) to wall-clock UTC."""
    try:
        uptime_s = sys_uptime_ms / 1000.0
        rel_s = first_last_ms / 1000.0
        return datetime.fromtimestamp(unix_secs - uptime_s + rel_s,
                                      tz=timezone.utc).replace(tzinfo=None)
    except (OverflowError, OSError, ValueError):
        return None


class NetFlowCollector:
    """A single UDP listener + parser, one instance per enabled NetFlowProbe."""

    def __init__(self, probe_id, name, listen_ip, port, version='both',
                 buffer_flush_sec=10):
        self.probe_id = probe_id
        self.name = name
        self.listen_ip = listen_ip
        self.port = port
        self.version = version
        self.buffer_flush_sec = buffer_flush_sec

        self._templates = {}          # {source_id: {template_id: [(type, len), ...]}}
        self._buffer = []             # pending NetFlowRecord objects
        self._buffer_lock = threading.Lock()
        self._sock = None
        self._running = False
        self._thread = None
        self._flush_thread = None
        self.packets = 0
        self.flows = 0
        self.last_packet = None
        self.last_error = None
        self.sample_types = {}        # sFlow sample_type -> count (diagnostics)
        self.rec_types = {}           # sFlow record_type -> count (diagnostics)
        self._warned_no_flow = False
        self.dropped = 0

    # ---------------------------------------------------------------- lifecycle
    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._serve, daemon=True,
                                        name='netflow-udp-%s' % self.port)
        self._flush_thread = threading.Thread(target=self._flush_loop, daemon=True,
                                              name='netflow-flush-%s' % self.port)
        self._thread.start()
        self._flush_thread.start()
        logger.info('NetFlow collector started: %s (udp %s:%s, %s)',
                    self.name, self.listen_ip, self.port, self.version)

    def stop(self):
        self._running = False
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
        self._flush()

    # ---------------------------------------------------------------- UDP loop
    def _serve(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self._sock.bind((self.listen_ip, self.port))
        except OSError as e:
            self.last_error = str(e)
            logger.error('NetFlow bind failed on %s:%s: %s',
                         self.listen_ip, self.port, e)
            self._running = False
            return
        self._sock.settimeout(0.5)
        while self._running:
            try:
                data, _addr = self._sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                if self._running:
                    continue
                break
            self.packets += 1
            self.last_packet = _now()
            try:
                self._dispatch(data)
            except Exception as e:
                self.last_error = str(e)
                logger.exception('NetFlow parse error on %s:%s', self.port, e)

    def _dispatch(self, data):
        if len(data) < 4:
            return
        # sFlow v5 has a 4-byte version field: 00 00 00 05
        if data[0:4] == b'\x00\x00\x00\x05' and self.version in ('sflow', 'all'):
            self._parse_sflow(data)
            return
        if len(data) < 2:
            return
        version = struct.unpack_from('>H', data, 0)[0]
        # NetStream from Huawei/中兴 is the same v5/v9 binary encoding on 9020
        if version == 5 and self.version in ('v5', 'both', 'netstream'):
            self._parse_v5(data)
        elif version == 9 and self.version in ('v9', 'both', 'netstream'):
            self._parse_v9(data)
        # else: ignore unsupported protocol/version

    # ---------------------------------------------------------------- sFlow v5
    def _parse_sflow(self, data):
        """Parse an sFlow v5 datagram (RFC 3176): flow samples -> records."""
        if len(data) < 28:
            return
        version = struct.unpack_from('>I', data, 0)[0]
        if version != 5:
            return
        agent_type = struct.unpack_from('>I', data, 4)[0]
        offset = 8 + (4 if agent_type == 1 else 16)
        # sub_agent_id(4) seq(4) uptime(4) num_samples(4)
        if offset + 16 > len(data):
            return
        sub_agent, seq, uptime, num_samples = struct.unpack_from('>IIII', data, offset)
        offset += 16
        for _ in range(num_samples):
            if offset + 8 > len(data):
                break
            sample_type, sample_len = struct.unpack_from('>II', data, offset)
            if sample_len < 0 or offset + 8 + sample_len > len(data):
                break
            body = data[offset + 8:offset + 8 + sample_len]
            self.sample_types[sample_type] = self.sample_types.get(sample_type, 0) + 1
            if sample_type == 1:      # flow sample
                self._parse_sflow_flow_sample(body)
            elif sample_type == 3:    # expanded flow sample (RFC 3176)
                self._parse_sflow_expanded_flow_sample(body)
            # types 2/4 = counter samples (ignored for flow accounting)
            offset += 8 + sample_len
        # One-time diagnostic: flow samples arrived but nothing was produced.
        # Tells the user whether the switch is sending samples the parser
        # ignores (see rec_types) vs. not sending flow samples at all.
        flow_samples = self.sample_types.get(1, 0) + self.sample_types.get(3, 0)
        if flow_samples and self.flows == 0 and not self._warned_no_flow:
            self._warned_no_flow = True
            logger.warning(
                'NetFlow %s: parsed %d sFlow flow sample(s) but produced 0 '
                'records. sample_types=%s rec_types=%s — check switch '
                '"sflow flow-sampling" export config.',
                self.name, flow_samples, self.sample_types, self.rec_types)

    def _parse_sflow_flow_sample(self, body):
        if len(body) < 32:
            return
        seq, source_id, sampling_rate, sample_pool, drops, in_if, out_if = \
            struct.unpack_from('>IIIIIII', body, 0)
        num_records = struct.unpack_from('>I', body, 28)[0]
        self._parse_sflow_records(body, 32, num_records)

    def _parse_sflow_expanded_flow_sample(self, body):
        """RFC 3176 expanded flow sample: 11 x 4-byte header, records at 44."""
        if len(body) < 44:
            return
        seq, src_type, src_index, sampling_rate, sample_pool, drops, \
            in_fmt, in_val, out_fmt, out_val, num_records = \
            struct.unpack_from('>IIIIIIIIIII', body, 0)
        self._parse_sflow_records(body, 44, num_records)

    def _parse_sflow_records(self, body, offset, num_records):
        for _ in range(num_records):
            if offset + 8 > len(body):
                break
            rec_type, rec_len = struct.unpack_from('>II', body, offset)
            if rec_len < 0 or offset + 8 + rec_len > len(body):
                break
            rec = body[offset + 8:offset + 8 + rec_len]
            offset += 8 + rec_len
            self.rec_types[rec_type] = self.rec_types.get(rec_type, 0) + 1
            if rec_type == 3:      # IPv4 data
                self._emit_sflow_ipv4(rec)
            elif rec_type == 4:    # IPv6 data
                self._emit_sflow_ipv6(rec)
            elif rec_type == 1:    # sampled header (raw packet)
                self._emit_sflow_header(rec)

    def _emit_sflow_ipv4(self, rec):
        if len(rec) < 32:
            return
        length, protocol = struct.unpack_from('>II', rec, 0)
        src = struct.unpack_from('>I', rec, 8)[0]
        dst = struct.unpack_from('>I', rec, 12)[0]
        sport, dport = struct.unpack_from('>II', rec, 16)
        tcp_flags = struct.unpack_from('>I', rec, 24)[0]
        tos = struct.unpack_from('>I', rec, 28)[0]
        self._enqueue_sflow(src, dst, protocol, sport, dport, tcp_flags,
                            tos, octets=length, packets=1)

    def _emit_sflow_ipv6(self, rec):
        if len(rec) < 48:
            return
        length, protocol = struct.unpack_from('>II', rec, 0)
        src = rec[8:24]
        dst = rec[24:40]
        sport, dport = struct.unpack_from('>II', rec, 40)
        tcp_flags = struct.unpack_from('>I', rec, 48)[0] if len(rec) >= 52 else 0
        self._enqueue_sflow(src, dst, protocol, sport, dport, tcp_flags,
                            0, octets=length, packets=1)

    def _emit_sflow_header(self, rec):
        """Parse a raw Ethernet+IPv4 header to extract flow fields."""
        if len(rec) < 14:
            return
        frame_length = struct.unpack_from('>I', rec, 4)[0]
        header_len = struct.unpack_from('>I', rec, 12)[0]
        header = rec[16:16 + header_len]
        if len(header) < 14:
            return
        ethertype = struct.unpack_from('>H', header, 12)[0]
        # 802.1Q VLAN tag shifts the payload ethertype by 4 bytes (trunk ports)
        if ethertype == 0x8100:
            ethertype = struct.unpack_from('>H', header, 16)[0]
            ip = header[18:]
        else:
            ip = header[14:]
        if ethertype != 0x0800:      # IPv4 only for now
            return
        if len(ip) < 20:
            return
        ihl = (ip[0] & 0x0F) * 4
        if ihl < 20 or len(ip) < ihl:
            return
        tos = ip[1]
        total_len = struct.unpack_from('>H', ip, 2)[0]
        protocol = ip[9]
        src = struct.unpack_from('>I', ip, 12)[0]
        dst = struct.unpack_from('>I', ip, 16)[0]
        sport = dport = tcp_flags = None
        if protocol in (6, 17) and len(ip) >= ihl + 4:
            sport, dport = struct.unpack_from('>HH', ip, ihl)
            tcp_flags = ip[ihl + 13] if protocol == 6 and len(ip) >= ihl + 14 else None
        self._enqueue_sflow(src, dst, protocol, sport, dport, tcp_flags,
                            tos, octets=total_len or frame_length, packets=1)

    def _enqueue_sflow(self, src, dst, protocol, sport, dport, tcp_flags,
                       tos, octets, packets):
        try:
            if isinstance(src, int):
                src_ip = _ip4_int(src)
            else:
                src_ip = _ip_from_bytes(src)
            if isinstance(dst, int):
                dst_ip = _ip4_int(dst)
            else:
                dst_ip = _ip_from_bytes(dst)
        except Exception:
            src_ip = dst_ip = None
        self._enqueue(NetFlowRecord(
            probe_id=self.probe_id, version='sflow',
            src_ip=src_ip, dst_ip=dst_ip,
            src_port=sport, dst_port=dport, protocol=protocol,
            protocol_name=PROTOCOL_NAMES.get(protocol),
            tcp_flags=tcp_flags, tos=tos,
            packets=packets, octets=octets,
            flow_start=None, flow_end=None, received_at=_now(),
        ))

    # ---------------------------------------------------------------- NetFlow v5
    def _parse_v5(self, data):
        if len(data) < 24:
            return
        (version, count, sys_uptime, unix_secs, unix_nsecs, flow_seq,
         engine_type, engine_id, sampling) = struct.unpack_from('>HHIIIIBBH', data, 0)
        offset = 24
        for _ in range(count):
            if offset + 48 > len(data):
                break
            rec = struct.unpack_from('>IIIHHIIIIHHBBBBHHBBH', data, offset)
            offset += 48
            src, dst, nhop, input_snmp, output_snmp = rec[0:5]
            dpkts, doctets, first, last = rec[5:9]
            srcport, dstport = rec[9], rec[10]
            pad1, tcp_flags, prot, tos = rec[11:15]
            src_as, dst_as = rec[15], rec[16]
            src_mask, dst_mask = rec[17], rec[18]
            self._enqueue(NetFlowRecord(
                probe_id=self.probe_id, version='v5',
                src_ip=_ip4_int(src), dst_ip=_ip4_int(dst),
                next_hop=_ip4_int(nhop) if nhop else None,
                src_port=srcport, dst_port=dstport, protocol=prot,
                protocol_name=PROTOCOL_NAMES.get(prot),
                tos=tos, tcp_flags=tcp_flags, src_as=src_as, dst_as=dst_as,
                input_snmp=input_snmp, output_snmp=output_snmp,
                src_mask=src_mask, dst_mask=dst_mask,
                packets=dpkts, octets=doctets,
                flow_start=_flow_time(first, unix_secs, sys_uptime),
                flow_end=_flow_time(last, unix_secs, sys_uptime),
                received_at=_now(),
            ))

    # ---------------------------------------------------------------- NetFlow v9
    def _parse_v9(self, data):
        if len(data) < 20:
            return
        (version, count, sys_uptime, unix_secs, sequence, source_id) = \
            struct.unpack_from('>HHIIII', data, 0)
        offset = 20
        for _ in range(max(count, 1)):
            if offset + 4 > len(data):
                break
            flowset_id, length = struct.unpack_from('>HH', data, offset)
            if length < 4 or offset + length > len(data):
                break
            body = data[offset + 4:offset + length]
            if flowset_id == 0:
                self._parse_v9_templates(source_id, body)
            elif flowset_id == 1:
                self._parse_v9_templates(source_id, body, options=True)
            else:
                self._parse_v9_data(source_id, flowset_id, body,
                                    unix_secs, sys_uptime)
            offset += length
    # -------------------------------------------------------- v9 templates
    def _parse_v9_templates(self, source_id, body, options=False):
        offset = 0
        while offset + 4 <= len(body):
            template_id, field_count = struct.unpack_from('>HH', body, offset)
            offset += 4
            fields = []
            for _ in range(field_count):
                if offset + 4 > len(body):
                    break
                ftype, flen = struct.unpack_from('>HH', body, offset)
                offset += 4
                fields.append((ftype, flen))
            self._templates.setdefault(source_id, {})[template_id] = fields
            if options:
                # An options template has scope fields then option fields; we
                # already captured them all generically, so nothing extra to do.
                pass

    def _parse_v9_data(self, source_id, template_id, body, unix_secs, sys_uptime):
        tpl = self._templates.get(source_id, {}).get(template_id)
        if not tpl:
            return  # template not seen yet; drop (normal during ramp-up)
        total = sum(flen for _ft, flen in tpl)
        if total == 0:
            return
        offset = 0
        while offset + total <= len(body):
            vals = {}
            inner = offset
            for ftype, flen in tpl:
                vals[ftype] = body[inner:inner + flen]
                inner += flen
            self._emit_v9_record(vals, unix_secs, sys_uptime)
            offset += total

    def _emit_v9_record(self, v, unix_secs, sys_uptime):
        def u8(t):
            b = v.get(t)
            return b[0] if b and len(b) == 1 else None

        def u16(t):
            b = v.get(t)
            return struct.unpack('>H', b)[0] if b and len(b) == 2 else None

        def u32(t):
            b = v.get(t)
            return struct.unpack('>I', b)[0] if b and len(b) == 4 else None
        src_ip = _ip_from_bytes(v.get(8)) or _ip_from_bytes(v.get(27))
        dst_ip = _ip_from_bytes(v.get(12)) or _ip_from_bytes(v.get(28))
        nhop = _ip_from_bytes(v.get(15)) or _ip_from_bytes(v.get(46))
        prot = u8(4)
        first_ms = u32(22) or u32(148)
        last_ms = u32(21) or u32(149)
        # FLOW_START_* / FLOW_END_* (148/149 are seconds since epoch)
        start = None
        end = None
        if 148 in v and u32(148):
            start = datetime.fromtimestamp(u32(148), tz=timezone.utc).replace(tzinfo=None)
        elif first_ms:
            start = _flow_time(first_ms, unix_secs, sys_uptime)
        if 149 in v and u32(149):
            end = datetime.fromtimestamp(u32(149), tz=timezone.utc).replace(tzinfo=None)
        elif last_ms:
            end = _flow_time(last_ms, unix_secs, sys_uptime)
        self._enqueue(NetFlowRecord(
            probe_id=self.probe_id, version='v9',
            src_ip=src_ip, dst_ip=dst_ip, next_hop=nhop,
            src_port=u16(7), dst_port=u16(11), protocol=prot,
            protocol_name=PROTOCOL_NAMES.get(prot),
            tos=u8(5), tcp_flags=u8(6), src_as=u16(16), dst_as=u16(17),
            input_snmp=u16(10), output_snmp=u16(14),
            src_mask=u8(9), dst_mask=u8(13),
            packets=u32(2), octets=u32(1),
            flow_start=start, flow_end=end, received_at=_now(),
        ))

    # ---------------------------------------------------------------- buffer/flush
    def _enqueue(self, record):
        with self._buffer_lock:
            self._buffer.append(record)
            self.flows += 1
            # avoid unbounded growth if DB is down
            if len(self._buffer) >= 5000:
                buf = self._buffer
                self._buffer = []
        if 'buf' in locals():
            self._persist(buf)

    def _flush_loop(self):
        while self._running:
            time.sleep(self.buffer_flush_sec)
            self._flush()

    def _flush(self):
        with self._buffer_lock:
            buf = self._buffer
            self._buffer = []
        if buf:
            self._persist(buf)

    def _persist(self, records):
        if not records:
            return
        session = get_bg_session()
        try:
            table = NetFlowRecord.__table__
            rows = [{
                'probe_id': r.probe_id,
                'version': r.version,
                'src_ip': r.src_ip,
                'dst_ip': r.dst_ip,
                'next_hop': r.next_hop,
                'src_port': r.src_port,
                'dst_port': r.dst_port,
                'protocol': r.protocol,
                'protocol_name': r.protocol_name,
                'tos': r.tos,
                'tcp_flags': r.tcp_flags,
                'src_as': r.src_as,
                'dst_as': r.dst_as,
                'input_snmp': r.input_snmp,
                'output_snmp': r.output_snmp,
                'src_mask': r.src_mask,
                'dst_mask': r.dst_mask,
                'packets': r.packets,
                'octets': r.octets,
                'flow_start': r.flow_start,
                'flow_end': r.flow_end,
                'received_at': r.received_at,
            } for r in records]
            session.execute(table.insert(), rows)
            session.commit()
        except Exception as e:
            self.dropped += len(records)
            self.last_error = 'persist: %s' % e
            logger.error('NetFlow persist failed (%d records): %s', len(records), e)
            session.rollback()
        finally:
            session.close()

    def status(self):
        return {
            'id': self.probe_id, 'name': self.name, 'port': self.port,
            'version': self.version, 'running': self._running,
            'packets': self.packets, 'flows': self.flows,
            'last_packet': self.last_packet.isoformat() if self.last_packet else None,
            'last_error': self.last_error,
            'buffer': len(self._buffer),
            'dropped': self.dropped,
            'last_packet_age_sec': (round((_now() - self.last_packet).total_seconds())
                                     if self.last_packet else None),
            'sample_types': {str(k): v for k, v in self.sample_types.items()},
            'rec_types': {str(k): v for k, v in self.rec_types.items()},
        }
# ------------------------------------------------------------------ registry
import time  # noqa: E402 (module-level for class methods)

_COLLECTORS = {}          # probe_id -> NetFlowCollector


def start_collector(probe):
    """Start (or restart) the collector for one probe row."""
    if not _netflow_enabled():
        stop_collector(probe.id)
        return None
    existing = _COLLECTORS.get(probe.id)
    if existing:
        existing.stop()
    if not probe.enabled:
        return None
    collector = NetFlowCollector(
        probe_id=probe.id, name=probe.name,
        listen_ip=probe.listen_ip, port=probe.port,
        version=probe.version or 'both',
    )
    _COLLECTORS[probe.id] = collector
    collector.start()
    return collector


def stop_collector(probe_id):
    c = _COLLECTORS.pop(probe_id, None)
    if c:
        c.stop()


def start_all_collectors(app=None):
    """Start collectors for every enabled NetFlowProbe (called by scheduler)."""
    if app is not None:
        with app.app_context():
            _start_all_impl()
    else:
        _start_all_impl()


def _start_all_impl():
    if not _netflow_enabled():
        stop_all_collectors()
        return
    session = get_bg_session()
    try:
        probes = session.query(NetFlowProbe).filter_by(enabled=True).all()
        for p in probes:
            start_collector(p)
        session.commit()
    finally:
        session.close()
    logger.info('NetFlow collectors synchronized (%d running)', len(_COLLECTORS))


def stop_all_collectors():
    for c in list(_COLLECTORS.values()):
        c.stop()
    _COLLECTORS.clear()


def get_status():
    return [c.status() for c in _COLLECTORS.values()]


def sync_probe(probe_id):
    """Called after a probe row is created/updated/deleted via the blueprint."""
    session = get_bg_session()
    try:
        probe = session.get(NetFlowProbe, probe_id)
        session.commit()
    finally:
        session.close()
    if probe is None:
        stop_collector(probe_id)
        return None
    return start_collector(probe)


def seed_dictionaries(session):
    """Seed the protocol / app / dscp reference dictionaries (idempotent)."""
    from models.netflow_models import NetFlowApp, NetFlowAs, NetFlowDscp, NetFlowProtocol

    if session.query(NetFlowAs).count() == 0:
        for asn, (name, region) in ASN_DICTIONARY.items():
            session.add(NetFlowAs(asn=asn, name=name, region=region))

    if session.query(NetFlowProtocol).count() == 0:
        session.add_all(NetFlowProtocol(id=k, name=v) for k, v in PROTOCOL_NAMES.items())
    if session.query(NetFlowDscp).count() == 0:
        dscp = [(16, 'Default', '000000'), (17, 'AF11', '001010'),
                (18, 'AF12', '001100'), (19, 'AF13', '001110'),
                (20, 'AF21', '010010'), (21, 'AF22', '010100'),
                (22, 'AF23', '010110'), (23, 'AF31', '011010'),
                (24, 'AF32', '011100'), (25, 'AF33', '011110'),
                (26, 'AF41', '100010'), (27, 'AF42', '100100'),
                (28, 'AF43', '100110'), (29, 'EF', '101110'),
                (30, 'CS6', '110000'), (31, 'CS7', '111000'),
                (32, 'CS1', '001000'), (33, 'CS2', '010000'),
                (34, 'CS3', '011000'), (35, 'CS4', '100000'),
                (36, 'CS5', '101000')]
        session.add_all(NetFlowDscp(id=i, name=n, value=v) for i, n, v in dscp)
    if session.query(NetFlowApp).count() == 0:
        apps = [('HTTP', 80, 'TCP'), ('HTTPS', 443, 'TCP'), ('SSH', 22, 'TCP'),
                ('TELNET', 23, 'TCP'), ('SMTP', 25, 'TCP'), ('DNS', 53, 'UDP'),
                ('DNS', 53, 'TCP'), ('POP3', 110, 'TCP'), ('IMAP', 143, 'TCP'),
                ('RDP', 3389, 'TCP'), ('MySQL', 3306, 'TCP'),
                ('PostgreSQL', 5432, 'TCP'), ('Redis', 6379, 'TCP'),
                ('Memcached', 11211, 'UDP'), ('HTTP-Alt', 8080, 'TCP'),
                ('HTTPS-Alt', 8443, 'TCP'), ('SNMP', 161, 'UDP'),
                ('NTP', 123, 'UDP'), ('Syslog', 514, 'UDP'),
                ('NetFlow', 2055, 'UDP'), ('sFlow', 6343, 'UDP')]
        for name, port, proto in apps:
            session.add(NetFlowApp(app_name=name, port=port, protocol=proto))
    session.commit()
