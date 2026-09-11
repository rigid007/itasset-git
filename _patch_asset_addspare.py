from pathlib import Path
p=Path('blueprints/asset.py')
s=p.read_text(encoding='utf-8').replace('\r\n','\n')
start=s.find('def add_spare_part():')
end=s.find("@asset_bp.route('/spare_part/edit/<int:id>'", start)
if start==-1 or end==-1: raise SystemExit('add spare bounds missing')
new = """def add_spare_part():

    \"\"\"新增备件（接收表单数据）\"\"\"

    try:

        part_number = request.form.get('part_number') or request.form.get('asset_number')

        name = request.form.get('name') or request.form.get('part_name')

        if not part_number or not name:

            return jsonify(success=False, message='备件编号和名称为必填项'), 400

        part = SparePart(

            asset_number=part_number,

            part_name=name,

            notes=request.form.get('description') or request.form.get('notes'),

            part_type=request.form.get('category') or request.form.get('part_type'),

            manufacturer=request.form.get('vendor') or request.form.get('manufacturer'),

            model=request.form.get('model'),

            unit_price=request.form.get('unit_price', type=float),

            current_stock=request.form.get('current_stock', type=int) or 0,

            min_stock_level=request.form.get('min_stock_level', type=int) or 0,

            max_stock_level=request.form.get('max_stock_level', type=int) or 0,

            warehouse_location=request.form.get('location') or request.form.get('warehouse_location'),

            supplier_id=request.form.get('supplier_id', type=int) or None,

            installed_device_id=request.form.get('installed_device_id', type=int) or None,

            is_active=request.form.get('is_active') == 'on'

        )

        db.session.add(part)

        db.session.commit()

        log_audit('create', 'spare_part', part.id, f"添加备件: {name}", user_id=current_user.id if current_user.is_authenticated else None)

        return jsonify(success=True, message='备件添加成功', part_id=part.id)

    except Exception as e:

        db.session.rollback()

        current_app.logger.error(f"添加备件失败: {str(e)}")

        return jsonify(success=False, message=str(e)), 500


\n\n"""
s=s[:start]+new+s[end:]
p.write_text(s.replace('\n','\r\n'), encoding='utf-8')
print('add spare updated')
