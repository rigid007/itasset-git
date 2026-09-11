from pathlib import Path
# inventory template
p=Path('templates/asset/spare_parts_inventory.html')
s=p.read_text(encoding='utf-8').replace('\r\n','\n')
repls = {
    '{{ part.part_number }}': '{{ part.asset_number or part.part_number }}',
    '{{ part.name }}': '{{ part.part_name or part.model or part.asset_number }}',
    '{{ part.category }}': '{{ part.part_type or part.category }}',
    '{{ part.location or': '{{ part.warehouse_location or part.location or',
    '{{ part.vendor or': '{{ part.manufacturer or part.vendor or',
}
for k,v in repls.items():
    s=s.replace(k,v)
p.write_text(s.replace('\n','\r\n'), encoding='utf-8')
# requests template
p=Path('templates/asset/spare_parts_requests.html')
s=p.read_text(encoding='utf-8').replace('\r\n','\n')
s=s.replace('{{ req.spare_part.name if req.spare_part else', '{{ (req.spare_part.part_name or req.spare_part.model or req.spare_part.asset_number) if req.spare_part else')
p.write_text(s.replace('\n','\r\n'), encoding='utf-8')
print('asset templates patched')
