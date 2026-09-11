from pathlib import Path
p=Path('blueprints/asset.py')
s=p.read_text(encoding='utf-8').replace('\r\n','\n')
start=s.find('def get_spare_part_request(id):')
end=s.find("@asset_bp.route('/spare_part_request/add'", start)
if start==-1 or end==-1: raise SystemExit('get req bounds missing')
new = """def get_spare_part_request(id):

    req = SparePartRequest.query.get(id)

    if not req:

        return jsonify(success=False, message='申请不存在'), 404

    part = req.spare_part

    return jsonify(success=True, request={

        'id': req.id,

        'request_number': req.request_number,

        'spare_part_id': req.spare_part_id,

        'spare_part': {

            'name': part.part_name if part else '-',

            'part_number': part.asset_number if part else '-',

            'model': part.model if part else '',

            'unit_price': float(part.unit_price or 0) if part else 0,

            'current_stock': int(part.current_stock or 0) if part else 0,

            'min_stock_level': int(part.min_stock_level or 0) if part else 0,

        },

        'quantity': req.quantity,

        'reason': req.reason,

        'usage_description': req.usage_description,

        'urgency': req.urgency,

        'status': req.status,

        'approval_status': req.approval_status,

        'approved_by': req.approved_by,

        'approved_at': req.approved_at.isoformat() if req.approved_at else None,

    })


\n\n"""
s=s[:start]+new+s[end:]
p.write_text(s.replace('\n','\r\n'), encoding='utf-8')
print('get req updated')
