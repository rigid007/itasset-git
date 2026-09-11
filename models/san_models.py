# models/san_models.py
"""存储光纤 (SAN / Fiber Channel) 拓扑模型。

用 G6 渲染的分区(Zone)拓扑：FC 交换机、存储阵列、服务器 HBA、以及它们之间的
链路。数据可由 FC 交换机 SNMP/zoning 导入或手动录入。
"""
from extensions import db
from models._base import utcnow


class SanNode(db.Model):
    __tablename__ = 'san_nodes'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    node_type = db.Column(db.String(32), nullable=False, default='switch')
    # switch / array / server / hba / other
    wwpn = db.Column(db.String(64), nullable=True)          # 光纤 WWPN
    vendor = db.Column(db.String(64), nullable=True)
    model = db.Column(db.String(64), nullable=True)
    mgmt_ip = db.Column(db.String(64), nullable=True)
    zone = db.Column(db.String(64), nullable=True)          # 所属分区(Zone)
    status = db.Column(db.String(16), nullable=False, default='unknown')
    # online / offline / unknown
    linked_device_id = db.Column(db.Integer, db.ForeignKey('devices.id'),
                                 nullable=True)              # 可关联 CMDB 设备
    note = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'node_type': self.node_type,
            'wwpn': self.wwpn,
            'vendor': self.vendor,
            'model': self.model,
            'mgmt_ip': self.mgmt_ip,
            'zone': self.zone,
            'status': self.status,
            'linked_device_id': self.linked_device_id,
            'note': self.note,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class SanLink(db.Model):
    __tablename__ = 'san_links'

    id = db.Column(db.Integer, primary_key=True)
    source_id = db.Column(db.Integer, db.ForeignKey('san_nodes.id'),
                          nullable=False)
    target_id = db.Column(db.Integer, db.ForeignKey('san_nodes.id'),
                          nullable=False)
    link_type = db.Column(db.String(32), nullable=False, default='fc')
    # fc / isl / ethernet
    port_source = db.Column(db.String(32), nullable=True)
    port_target = db.Column(db.String(32), nullable=True)
    speed = db.Column(db.String(16), nullable=True)         # 8G / 16G / 32G ...
    status = db.Column(db.String(16), nullable=False, default='up')
    # up / down / unknown
    note = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'source_id': self.source_id,
            'target_id': self.target_id,
            'link_type': self.link_type,
            'port_source': self.port_source,
            'port_target': self.port_target,
            'speed': self.speed,
            'status': self.status,
            'note': self.note,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
