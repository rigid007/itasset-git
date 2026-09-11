from pathlib import Path
p=Path('models/maintenance_models.py')
s=p.read_text(encoding='utf-8').replace('\r\n','\n')
for needle in ['warehouse_location = db.Column', 'installed_device_id = db.Column', 'def generate_change_number', "backref('approval_chain'", 'assignee = db.relationship', 'is_featured = db.Column']:
    i=s.find(needle)
    print('---', needle, i)
    print(repr(s[i:i+400]))
