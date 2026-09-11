from pathlib import Path
p=Path('forms.py')
s=p.read_text(encoding='utf-8').replace('\r\n','\n')
old = """    def __init__(self, *args, **kwargs):\n        super().__init__(*args, **kwargs)\n        self.affected_devices_ids.choices = [\n            (d.id, f"{d.name} ({d.ip_address or '-'})")\n            for d in Device.query.order_by(Device.name).all()\n        ]\n\n\n"""
new = """    def __init__(self, *args, **kwargs):\n        super().__init__(*args, **kwargs)\n        self.affected_devices_ids.choices = [\n            (d.id, f"{d.name} ({d.ip_address or '-'})")\n            for d in Device.query.order_by(Device.name).all()\n        ]\n        self.implementer_id.choices = [(0, '-- 请选择实施人 --')] + [\n            (u.id, u.username) for u in User.query.filter_by(is_active=True).order_by(User.username).all()\n        ]\n\n\n"""
if old not in s: raise SystemExit('change form init block missing')
s=s.replace(old,new,1)
p.write_text(s.replace('\n','\r\n'), encoding='utf-8')
print('forms updated')
