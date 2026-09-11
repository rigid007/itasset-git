from pathlib import Path
p=Path('blueprints/asset.py')
s=p.read_text(encoding='utf-8').replace('\r\n','\n')
start=s.find('def get_spare_part(id):')
end=s.find("@asset_bp.route('/spare_part/add'", start)
if start==-1 or end==-1: raise SystemExit('get spare bounds missing')
new = """def get_spare_part(id):

    \"\"\"获取单个备件详情（JSON）\"\"\"

    part = SparePart.query.get(id)

    if not part:

        return jsonify(success=False, message='备件不存在'), 404

    

    return jsonify(success=True, part=_part_dict(part))


\n\n"""
s=s[:start]+new+s[end:]
p.write_text(s.replace('\n','\r\n'), encoding='utf-8')
print('get spare updated')
