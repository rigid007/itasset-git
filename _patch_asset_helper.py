from pathlib import Path
p=Path('blueprints/asset.py')
s=p.read_text(encoding='utf-8').replace('\r\n','\n')
anchor = "asset_bp = Blueprint('asset', __name__, url_prefix='/asset')\n"
helper = """

def _part_view(part):
    \"\"\"Return legacy-template-friendly attribute view for a SparePart.\"\"\"
    return SimpleNamespace(
        id=part.id,
        part_number=part.asset_number or '',
        asset_number=part.asset_number,
        name=part.part_name or part.model or part.asset_number or '',
        part_name=part.part_name,
        category=part.part_type,
        part_type=part.part_type,
        vendor=part.manufacturer,
        manufacturer=part.manufacturer,
        model=part.model,
        description=part.notes,
        unit_price=float(part.unit_price or 0),
        current_stock=int(part.current_stock or 0),
        min_stock_level=int(part.min_stock_level or 0),
        max_stock_level=int(part.max_stock_level or 0),
        location=part.warehouse_location,
        warehouse_location=part.warehouse_location,
        supplier=part.supplier,
        supplier_id=part.supplier_id,
        is_active=bool(part.is_active),
    )
"""
if anchor not in s: raise SystemExit('asset bp anchor missing')
s=s.replace(anchor, anchor+helper,1)
# import SimpleNamespace
old="from io import BytesIO\n"
new="from io import BytesIO\nfrom types import SimpleNamespace\n"
if old not in s: raise SystemExit('io import missing')
s=s.replace(old,new,1)
p.write_text(s.replace('\n','\r\n'), encoding='utf-8')
print('asset helper added')
