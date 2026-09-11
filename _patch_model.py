from pathlib import Path
p = Path('models/maintenance_models.py')
s = p.read_text(encoding='utf-8').replace('\r\n','\n')
# 1 SparePart stock/supplier columns before installed_device_id
old = "    unit_price = db.Column(db.Numeric(10, 2))  #"
i = s.find(old)
if i == -1: raise SystemExit('sparepart unit_price marker missing')
insert_before = s.find("\n    installed_device_id = db.Column(db.Integer, db.ForeignKey('devices.id'))", i)
if insert_before == -1: raise SystemExit('sparepart installed_device_id missing')
new_cols = "\n    current_stock = db.Column(db.Integer, default=0, nullable=False, comment='current stock quantity')\n    min_stock_level = db.Column(db.Integer, default=0, nullable=False, comment='minimum stock threshold')\n    max_stock_level = db.Column(db.Integer, default=0, nullable=False, comment='maximum stock threshold')\n    supplier_id = db.Column(db.Integer, db.ForeignKey('suppliers.id'), nullable=True, comment='primary supplier id')"
s = s[:insert_before] + new_cols + s[insert_before:]
# 2 supplier relationship after installed_device relationship
old = "    installed_device = db.relationship('Device', back_populates='spare_parts')\n    installed_date = db.Column(db.Date)"
new = "    installed_device = db.relationship('Device', back_populates='spare_parts')\n    supplier = db.relationship('Supplier', backref='spare_parts')\n    installed_date = db.Column(db.Date)"
if old not in s: raise SystemExit('sparepart relationship block missing')
s = s.replace(old, new, 1)
# 3 to_dict add stock fields before installed_device_id
old = "            'warehouse_location': self.warehouse_location,\n            'purchase_date': self.purchase_date.isoformat() if self.purchase_date else None,\n            'installed_device_id': self.installed_device_id,"
new = "            'warehouse_location': self.warehouse_location,\n            'purchase_date': self.purchase_date.isoformat() if self.purchase_date else None,\n            'current_stock': self.current_stock,\n            'min_stock_level': self.min_stock_level,\n            'max_stock_level': self.max_stock_level,\n            'supplier_id': self.supplier_id,\n            'installed_device_id': self.installed_device_id,"
if old not in s: raise SystemExit('sparepart to_dict block missing')
s = s.replace(old, new, 1)
# 4 KnowledgeArticle author relationship
old = "    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)\n    \n    def to_dict(self):"
new = "    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)\n    author = db.relationship('User', foreign_keys=[author_id], backref='knowledge_articles')\n    \n    def to_dict(self):"
if old not in s: raise SystemExit('kb author block missing')
s = s.replace(old, new, 1)
# 5 Problem creator relationship
old = "    assignee = db.relationship('User', foreign_keys=[assigned_to], backref='assigned_problems')\n    device = db.relationship('Device', backref='problem_records')"
new = "    assignee = db.relationship('User', foreign_keys=[assigned_to], backref='assigned_problems')\n    creator = db.relationship('User', foreign_keys=[created_by], backref='created_problem_records')\n    device = db.relationship('Device', backref='problem_records')"
if old not in s: raise SystemExit('problem creator block missing')
s = s.replace(old, new, 1)
# 6 generate_change_number TEMP handling
old = """    def generate_change_number(self):
        \"\"\"Generate change number (date+time+uuid suffix to avoid concurrency conflicts).\"\"\"
        if not self.change_number:
            date_str = datetime.now().strftime('%Y%m%d%H%M%S')
            suffix = uuid.uuid4().hex[:6].upper()
            self.change_number = f'CR{date_str}{suffix}'
        return self.change_number
"""
new = """    def generate_change_number(self):
        \"\"\"Generate final change number (date+time+uuid suffix).\"\"\"
        if not self.change_number or str(self.change_number or '').startswith('TEMP-'):
            date_str = datetime.now().strftime('%Y%m%d%H%M%S')
            suffix = uuid.uuid4().hex[:6].upper()
            self.change_number = f'CR{date_str}{suffix}'
        return self.change_number
"""
if old not in s: raise SystemExit('generate number block missing')
s = s.replace(old, new, 1)
# 7 approval_chain dynamic
old = "    change = db.relationship('ChangeRequest', backref=db.backref('approval_chain', cascade='all, delete-orphan'))\n"
new = "    change = db.relationship('ChangeRequest', backref=db.backref('approval_chain', cascade='all, delete-orphan', lazy='dynamic'))\n"
if old not in s: raise SystemExit('approval chain block missing')
s = s.replace(old, new, 1)
p.write_text(s.replace('\n','\r\n'), encoding='utf-8')
print('model updated')
