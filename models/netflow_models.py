# models/netflow_models.py
"""NetFlow / sFlow collector models.

Two kinds of tables:

1. Reference tables (seeded, read-mostly) - borrowed from the DCOS platform's
   netflow_app / netflow_v5_protocol / netflow_dscp dictionaries:
     - NetFlowApp      : well-known port -> application name
     - NetFlowProtocol : IP protocol number -> name
     - NetFlowDscp     : DSCP bits -> class name (AF11/EF/CSx...)

2. Runtime tables:
     - NetFlowProbe  : one UDP collector instance (v5/v9/both), config row
     - NetFlowRecord : individual flow records (aggregatable by SQL views)

All runtime persistence goes through the project's central `db` object so
db.create_all() / alembic discover the tables, and the scheduler/blueprint
registration follows the same conventions as the existing oob subsystem.
"""
from extensions import db
from models._base import utcnow


class NetFlowProbe(db.Model):
    """A NetFlow collector endpoint. Each row owns one UDP listener thread."""
    __tablename__ = 'netflow_probes'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    listen_ip = db.Column(db.String(45), default='0.0.0.0')
    port = db.Column(db.Integer, nullable=False, default=2055)
    version = db.Column(db.String(16), default='both')   # v5 / v9 / both
    description = db.Column(db.Text)
    enabled = db.Column(db.Boolean, default=True, index=True)

    packets_received = db.Column(db.BigInteger, default=0)
    flows_received = db.Column(db.BigInteger, default=0)
    last_packet_at = db.Column(db.DateTime)
    last_error = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'listen_ip': self.listen_ip,
            'port': self.port,
            'version': self.version,
            'description': self.description,
            'enabled': self.enabled,
            'packets_received': self.packets_received or 0,
            'flows_received': self.flows_received or 0,
            'last_packet_at': self.last_packet_at.isoformat() if self.last_packet_at else None,
            'last_error': self.last_error,
        }


class NetFlowRecord(db.Model):
    """A single normalized flow record (NetFlow v5 or v9)."""
    __tablename__ = 'netflow_records'
    __table_args__ = (
        db.Index('idx_netflow_record_time', 'flow_end'),
        db.Index('idx_netflow_record_recv', 'received_at'),
        db.Index('idx_netflow_record_src', 'src_ip'),
        db.Index('idx_netflow_record_dst', 'dst_ip'),
        db.Index('idx_netflow_record_proto', 'protocol'),
        db.Index('idx_netflow_record_probe_time', 'probe_id', 'received_at'),
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    probe_id = db.Column(db.Integer, db.ForeignKey('netflow_probes.id'), index=True)
    version = db.Column(db.String(8))                # v5 / v9
    src_ip = db.Column(db.String(45))
    dst_ip = db.Column(db.String(45))
    next_hop = db.Column(db.String(45))
    src_port = db.Column(db.Integer)
    dst_port = db.Column(db.Integer)
    protocol = db.Column(db.Integer)
    protocol_name = db.Column(db.String(32))
    tos = db.Column(db.Integer)
    tcp_flags = db.Column(db.Integer)
    src_as = db.Column(db.Integer)
    dst_as = db.Column(db.Integer)
    input_snmp = db.Column(db.Integer)
    output_snmp = db.Column(db.Integer)
    src_mask = db.Column(db.Integer)
    dst_mask = db.Column(db.Integer)
    packets = db.Column(db.BigInteger, default=0)
    octets = db.Column(db.BigInteger, default=0)
    flow_start = db.Column(db.DateTime)
    flow_end = db.Column(db.DateTime)
    received_at = db.Column(db.DateTime, default=utcnow)

    probe = db.relationship('NetFlowProbe', backref='records', lazy='select')

    def to_dict(self):
        return {
            'id': self.id,
            'probe_id': self.probe_id,
            'version': self.version,
            'src_ip': self.src_ip,
            'dst_ip': self.dst_ip,
            'next_hop': self.next_hop,
            'src_port': self.src_port,
            'dst_port': self.dst_port,
            'protocol': self.protocol,
            'protocol_name': self.protocol_name,
            'tos': self.tos,
            'tcp_flags': self.tcp_flags,
            'src_as': self.src_as,
            'dst_as': self.dst_as,
            'packets': self.packets,
            'octets': self.octets,
            'flow_start': self.flow_start.isoformat() if self.flow_start else None,
            'flow_end': self.flow_end.isoformat() if self.flow_end else None,
            'received_at': self.received_at.isoformat() if self.received_at else None,
        }


class NetFlowApp(db.Model):
    """Well-known port -> application dictionary (seeded)."""
    __tablename__ = 'netflow_apps'

    id = db.Column(db.Integer, primary_key=True)
    app_name = db.Column(db.String(100), nullable=False)
    port = db.Column(db.Integer, nullable=False, index=True)
    protocol = db.Column(db.String(16), default='TCP')
    ip_address = db.Column(db.String(50))

    def to_dict(self):
        return {'id': self.id, 'app_name': self.app_name,
                'port': self.port, 'protocol': self.protocol,
                'ip_address': self.ip_address}


class NetFlowProtocol(db.Model):
    """IP protocol number -> name dictionary (seeded)."""
    __tablename__ = 'netflow_protocols'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), nullable=False)

    def to_dict(self):
        return {'id': self.id, 'name': self.name}


class NetFlowDscp(db.Model):
    """DSCP bits -> class dictionary (seeded, used for QoS reporting)."""
    __tablename__ = 'netflow_dscps'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(32), nullable=False)
    value = db.Column(db.String(8))          # binary bits, e.g. '001010'

    def to_dict(self):
        return {'id': self.id, 'name': self.name, 'value': self.value}



class NetFlowAs(db.Model):
    """ASN -> name/region dictionary (seeded with common operator ASNs)."""
    __tablename__ = 'netflow_ases'

    asn = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128))
    region = db.Column(db.String(64))          # 区域/国家归属

    def to_dict(self):
        return {'asn': self.asn, 'name': self.name, 'region': self.region}


class NetFlowAgg(db.Model):
    """Pre-aggregated NetFlow stats (currently 5-minute buckets).

    Computed by tasks.netflow_collect.netflow_aggregate from raw
    netflow_records. Each row is one (probe, 5m bucket, 5-tuple + app) combo.
    Used by top-apps / alerting / faster report paths.
    """
    __tablename__ = 'netflow_agg'
    __table_args__ = (
        db.UniqueConstraint(
            'probe_id', 'period', 'bucket', 'src_ip', 'dst_ip',
            'src_port', 'dst_port', 'protocol',
            name='uq_netflow_agg_key',
        ),
        db.Index('idx_netflow_agg_period_bucket', 'period', 'bucket'),
        db.Index('idx_netflow_agg_src_device', 'src_device_id'),
        db.Index('idx_netflow_agg_dst_device', 'dst_device_id'),
        db.Index('idx_netflow_agg_app', 'app_name'),
    )

    id = db.Column(db.Integer, primary_key=True)
    probe_id = db.Column(db.Integer, db.ForeignKey('netflow_probes.id'), index=True)
    period = db.Column(db.String(8), nullable=False, default='5m', index=True)
    bucket = db.Column(db.DateTime, nullable=False, index=True)
    src_ip = db.Column(db.String(45), index=True)
    dst_ip = db.Column(db.String(45), index=True)
    src_port = db.Column(db.Integer)
    dst_port = db.Column(db.Integer)
    protocol = db.Column(db.Integer)
    app_name = db.Column(db.String(100), index=True)
    src_device_id = db.Column(db.Integer, db.ForeignKey('devices.id'), index=True)
    dst_device_id = db.Column(db.Integer, db.ForeignKey('devices.id'), index=True)
    octets = db.Column(db.BigInteger, default=0)
    packets = db.Column(db.BigInteger, default=0)
    flows = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'probe_id': self.probe_id,
            'period': self.period,
            'bucket': self.bucket.isoformat() if self.bucket else None,
            'src_ip': self.src_ip,
            'dst_ip': self.dst_ip,
            'src_port': self.src_port,
            'dst_port': self.dst_port,
            'protocol': self.protocol,
            'app_name': self.app_name,
            'src_device_id': self.src_device_id,
            'dst_device_id': self.dst_device_id,
            'octets': self.octets or 0,
            'packets': self.packets or 0,
            'flows': self.flows or 0,
        }


class NetFlowAlert(db.Model):
    """NetFlow anomaly alert (bandwidth thresholds / top talkers)."""
    __tablename__ = 'netflow_alerts'

    id = db.Column(db.Integer, primary_key=True)
    probe_id = db.Column(db.Integer, db.ForeignKey('netflow_probes.id'), index=True)
    device_id = db.Column(db.Integer, db.ForeignKey('devices.id'), index=True)
    src_ip = db.Column(db.String(45), index=True)
    dst_ip = db.Column(db.String(45), index=True)
    app_name = db.Column(db.String(100), index=True)
    metric_type = db.Column(db.String(32), default='netflow_bandwidth', index=True)
    metric_value = db.Column(db.Float)               # Mbps observed
    threshold = db.Column(db.Float)                  # Mbps threshold
    severity = db.Column(db.String(20), default='warning')
    status = db.Column(db.String(20), default='active', index=True)
    title = db.Column(db.String(200))
    message = db.Column(db.Text)
    first_occurred = db.Column(db.DateTime, default=utcnow, index=True)
    last_occurred = db.Column(db.DateTime, default=utcnow)
    occurrence_count = db.Column(db.Integer, default=1)
    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    __table_args__ = (
        db.Index('idx_netflow_alert_key', 'metric_type', 'status', 'src_ip', 'dst_ip'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'probe_id': self.probe_id,
            'device_id': self.device_id,
            'src_ip': self.src_ip,
            'dst_ip': self.dst_ip,
            'app_name': self.app_name,
            'metric_type': self.metric_type,
            'metric_value': self.metric_value,
            'threshold': self.threshold,
            'severity': self.severity,
            'status': self.status,
            'title': self.title,
            'message': self.message,
            'first_occurred': self.first_occurred.isoformat() if self.first_occurred else None,
            'last_occurred': self.last_occurred.isoformat() if self.last_occurred else None,
            'occurrence_count': self.occurrence_count or 1,
        }
