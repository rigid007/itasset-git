from pathlib import Path
p=Path('blueprints/asset.py')
s=p.read_text(encoding='utf-8').replace('\r\n','\n')
anchor = "def _part_view(part):\n"
# add _part_dict after function by finding end before first route? easier after anchor? Insert after function block at first "\n\n\n@asset_bp.route"
end=s.find("\n\n\n@asset_bp.route", s.find(anchor))
if end==-1: raise SystemExit('end helper missing')
helper = """

def _part_dict(part):
    return {
        'id': part.id,
        'part_number': part.asset_number or '',
        'asset_number': part.asset_number,
        'name': part.part_name or part.model or part.asset_number or '',
        'part_name': part.part_name,
        'category': part.part_type,
        'part_type': part.part_type,
        'vendor': part.manufacturer,
        'manufacturer': part.manufacturer,
        'model': part.model,
        'description': part.notes,
        'unit_price': float(part.unit_price or 0),
        'current_stock': int(part.current_stock or 0),
        'min_stock_level': int(part.min_stock_level or 0),
        'max_stock_level': int(part.max_stock_level or 0),
        'location': part.warehouse_location,
        'warehouse_location': part.warehouse_location,
        'supplier_id': part.supplier_id,
        'supplier': {'id': part.supplier.id if part.supplier else None, 'name': part.supplier.name if part.supplier else '-'},
        'installed_device_id': part.installed_device_id,
        'is_active': bool(part.is_active),
    }
"""
s=s[:end]+helper+s[end:]
p.write_text(s.replace('\n','\r\n'), encoding='utf-8')
print('part dict helper added')
