from pathlib import Path
s=Path('blueprints/asset.py').read_text(encoding='utf-8').replace('\r\n','\n')
for needle in ['def spare_parts_inventory():','def spare_parts_requests():','def spare_parts_request_create():','form.spare_part_id.choices']:
    i=s.find(needle)
    print('---', needle, i)
    print(repr(s[i:i+900]))
