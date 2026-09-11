from pathlib import Path
p=Path('blueprints/asset.py')
s=p.read_text(encoding='utf-8').replace('\r\n','\n')
# delete function
start=s.find('def delete_spare_part(id):')
end=s.find("@asset_bp.route('/spare_part/adjust-stock/<int:id>'", start)
if start==-1 or end==-1: raise SystemExit('delete spare bounds missing')
new = """def delete_spare_part(id):

    \"\"\"删除备件\"\"\"

    part = SparePart.query.get(id)

    if not part:

        return jsonify(success=False, message='备件不存在'), 404

    try:

        db.session.delete(part)

        db.session.commit()

        log_audit('delete', 'spare_part', id, f"删除备件: {part.part_name}", user_id=current_user.id if current_user.is_authenticated else None)

        return jsonify(success=True, message='备件删除成功')

    except Exception as e:

        db.session.rollback()

        current_app.logger.error(f"删除备件 {id} 失败: {str(e)}")

        return jsonify(success=False, message=str(e)), 500


\n\n"""
s=s[:start]+new+s[end:]
# adjust function
start=s.find('def adjust_stock(id):')
end=s.find("@asset_bp.route('/spare_part_request/get/<int:id>'", start)
if start==-1 or end==-1: raise SystemExit('adjust stock bounds missing')
new = """def adjust_stock(id):

    \"\"\"库存调整（接收 JSON）\"\"\"

    part = SparePart.query.get(id)

    if not part:

        return jsonify(success=False, message='备件不存在'), 404

    data = request.get_json()

    if not data:

        return jsonify(success=False, message='无效的请求数据'), 400

    adjustment = data.get('adjustment')

    reason = data.get('reason', '')

    if adjustment is None or not isinstance(adjustment, int):

        return jsonify(success=False, message='调整数量必须是整数'), 400

    try:

        part.current_stock = max(0, int(part.current_stock or 0) + adjustment)

        db.session.commit()

        log_audit('execute', 'spare_part', part.id, f"调整备件库存: {part.part_name}, 调整量: {adjustment}, 原因: {reason}", user_id=current_user.id if current_user.is_authenticated else None)

        return jsonify(success=True, message='库存调整成功', current_stock=part.current_stock)

    except Exception as e:

        db.session.rollback()

        current_app.logger.error(f"调整库存 {id} 失败: {str(e)}")

        return jsonify(success=False, message=str(e)), 500


\n\n"""
s=s[:start]+new+s[end:]
p.write_text(s.replace('\n','\r\n'), encoding='utf-8')
print('delete/adjust updated')
