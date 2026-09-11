from pathlib import Path
p=Path('blueprints/maintenance_api.py')
s=p.read_text(encoding='utf-8').replace('\r\n','\n')
for needle in ['def _spare_part_dict(part):', 'def api_create_spare_part():', 'def api_update_spare_part(part_id):', 'def api_update_spare_part_stock(part_id):']:
    i=s.find(needle)
    print('---',needle,i)
    print(s[i:i+1400])
