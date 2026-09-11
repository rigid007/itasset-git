from pathlib import Path
p=Path('blueprints/asset.py')
s=p.read_text(encoding='utf-8').replace('\r\n','\n')
start=s.find('def edit_spare_part(id):')
end=s.find("@asset_bp.route('/spare_part/delete/<int:id>'", start)
if start==-1 or end==-1: raise SystemExit('edit spare bounds missing')
new = """def edit_spare_part(id):

    \"\"\"编辑备件（接收表单数据）\"\"\"

    part = SparePart.query.get(id)

    if not part:

        return jsonify(success=False, message='备件不存在'), 404

    try:

        part.asset_number = request.form.get('part_number', part.asset_number) or request.form.get('asset_number', part.asset_number)

        part.part_name = request.form.get('name', part.part_name) or request.form.get('part_name', part.part_name)

        part.notes = request.form.get('description', part.notes) or request.form.get('notes', part.notes)

        part.part_type = request.form.get('category', part.part_type) or request.form.get('part_type', part.part_type)

        part.manufacturer = request.form.get('vendor', part.manufacturer) or request.form.get('manufacturer', part.manufacturer)

        part.model = request.form.get('model', part.model)

        unit_price = request.form.get('unit_price')

        if unit_price is not None and unit_price != '':

            part.unit_price = float(unit_price)

        current_stock = request.form.get('current_stock')

        if current_stock is not None and current_stock != '':

            part.current_stock = int(current_stock)

        min_stock = request.form.get('min_stock_level')

        if min_stock is not None and min_stock != '':

            part.min_stock_level = int(min_stock)

        max_stock = request.form.get('max_stock_level')

        if max_stock is not None and max_stock != '':

            part.max_stock_level = int(max_stock)

        part.warehouse_location = request.form.get('location', part.warehouse_location) or request.form.get('warehouse_location', part.warehouse_location)

        supplier_id = request.form.get('supplier_id')

        if supplier_id is not None and supplier_id != '':

            part.supplier_id = int(supplier_id)

        else:

            part.supplier_id = None

        installed_device_id = request.form.get('installed_device_id')

        if installed_device_id is not None and installed_device_id != '':

            part.installed_device_id = int(installed_device_id)

        part.is_active = request.form.get('is_active') == 'on' if 'is_active' in request.form else part.is_active

        part.updated_at = datetime.utcnow()

        db.session.commit()

        log_audit('update', 'spare_part', id, f"编辑备件: {part.part_name}", user_id=current_user.id if current_user.is_authenticated else None)

        return jsonify(success=True, message='备件更新成功')

    except Exception as e:

        db.session.rollback()

        current_app.logger.error(f"编辑备件 {id} 失败: {str(e)}")

        return jsonify(success=False, message=str(e)), 500


\n\n"""
s=s[:start]+new+s[end:]
p.write_text(s.replace('\n','\r\n'), encoding='utf-8')
print('edit spare updated')
