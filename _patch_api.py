from pathlib import Path
p=Path('blueprints/maintenance_api.py')
s=p.read_text(encoding='utf-8').replace('\r\n','\n')
insert_after = "def _user_name(user_id):\n    if not user_id:\n        return None\n    user = User.query.get(user_id)\n    return user.username if user else None\n"
if insert_after not in s: raise SystemExit('user_name helper missing')
s = s.replace(insert_after, insert_after + "\n\ndef _int_or_none(value):\n    try:\n        return int(value)\n    except (TypeError, ValueError):\n        return None\n", 1)
old = """        'current_stock': 0,\n        'min_stock_level': 0,\n        'max_stock_level': 0,\n        'location': part.warehouse_location,\n        'supplier_id': None,\n        'supplier': {'name': part.manufacturer or '-'},\n"""
new = """        'current_stock': int(part.current_stock or 0),\n        'min_stock_level': int(part.min_stock_level or 0),\n        'max_stock_level': int(part.max_stock_level or 0),\n        'location': part.warehouse_location,\n        'supplier_id': part.supplier_id,\n        'supplier': {'id': part.supplier.id if part.supplier else None, 'name': part.supplier.name if part.supplier else (part.manufacturer or '-')},\n"""
if old not in s: raise SystemExit('spare dict block missing')
s=s.replace(old,new,1)
old = """        warehouse_location=data.get('location'),\n        notes=data.get('description'),\n        unit_price=data.get('unit_price'),\n        installed_device_id=data.get('installed_device_id') or None,\n        status='in_stock',\n    )"""
new = """        warehouse_location=data.get('location'),\n        notes=data.get('description'),\n        unit_price=data.get('unit_price'),\n        current_stock=_int_or_none(data.get('current_stock')) or 0,\n        min_stock_level=_int_or_none(data.get('min_stock_level')) or 0,\n        max_stock_level=_int_or_none(data.get('max_stock_level')) or 0,\n        supplier_id=_int_or_none(data.get('supplier_id')),\n        installed_device_id=data.get('installed_device_id') or None,\n        status='in_stock',\n    )"""
if old not in s: raise SystemExit('spare create block missing')
s=s.replace(old,new,1)
old = """    if data.get('unit_price') not in (None, ''):\n        part.unit_price = data.get('unit_price')\n    if data.get('installed_device_id') not in (None, ''):\n        part.installed_device_id = data.get('installed_device_id')"""
new = """    if data.get('unit_price') not in (None, ''):\n        part.unit_price = data.get('unit_price')\n    if data.get('current_stock') not in (None, ''):\n        part.current_stock = _int_or_none(data.get('current_stock'))\n    if data.get('min_stock_level') not in (None, ''):\n        part.min_stock_level = _int_or_none(data.get('min_stock_level'))\n    if data.get('max_stock_level') not in (None, ''):\n        part.max_stock_level = _int_or_none(data.get('max_stock_level'))\n    if data.get('supplier_id') not in (None, ''):\n        part.supplier_id = _int_or_none(data.get('supplier_id'))\n    if data.get('installed_device_id') not in (None, ''):\n        part.installed_device_id = data.get('installed_device_id')"""
if old not in s: raise SystemExit('spare update block missing')
s=s.replace(old,new,1)
# Replace stock function by slicing from def to next section comment
start=s.find('def api_update_spare_part_stock(part_id):')
end=s.find('# ----------', start)
if start==-1 or end==-1: raise SystemExit('stock function bounds missing')
newfunc = """def api_update_spare_part_stock(part_id):\n    part = SparePart.query.get_or_404(part_id)\n    data = _parse_json()\n    delta = int(data.get('delta', 0))\n    if delta:\n        part.current_stock = max(0, int(part.current_stock or 0) + delta)\n        db.session.commit()\n    log_audit('update', 'spare_part', part.id,\n              f"Stock adjustment: {part.part_name} delta={delta} current={part.current_stock}",\n              user_id=current_user.id)\n    return jsonify({'success': True, 'message': 'Stock adjustment persisted', 'part': _spare_part_dict(part)})\n\n\n"""
s = s[:start] + newfunc + s[end:]
p.write_text(s.replace('\n','\r\n'), encoding='utf-8')
print('api updated')
