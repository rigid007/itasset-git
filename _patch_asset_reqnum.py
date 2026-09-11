from pathlib import Path
p=Path('blueprints/asset.py')
s=p.read_text(encoding='utf-8').replace('\r\n','\n')
needle = "        req = SparePartRequest(\n            spare_part_id=spare_part_id,"
if needle not in s: raise SystemExit('req creation marker missing')
new = "        req = SparePartRequest(\n            request_number=f\"SPR{datetime.now().strftime('%Y%m%d%H%M%S')}\",\n            spare_part_id=spare_part_id,"
s=s.replace(needle,new,1)
p.write_text(s.replace('\n','\r\n'), encoding='utf-8')
print('request number inserted')
