from pathlib import Path
p=Path('blueprints/asset.py')
s=p.read_text(encoding='utf-8').replace('\r\n','\n')
start=s.find('def add_spare_part_request():')
end=s.find("@asset_bp.route('/spare_part_request/edit/<int:id>'", start)
if start==-1 or end==-1: raise SystemExit('bounds missing')
block=s[start:end]
newblock = """def add_spare_part_request():

    \"\"\"新增备件申请\"\"\"

    try:

        spare_part_id = request.form.get('spare_part_id', type=int)

        quantity = request.form.get('quantity', type=int)

        reason = request.form.get('reason')

        urgency = request.form.get('urgency', 'medium')

        usage_description = request.form.get('usage_description')

        if not spare_part_id or not quantity or not reason:

            return jsonify(success=False, message='备件、数量和原因为必填项'), 400

        spare_part = SparePart.query.get(spare_part_id)

        if not spare_part:

            return jsonify(success=False, message='备件不存在'), 404

        req = SparePartRequest(

            request_number=f"SPR{datetime.now().strftime('%Y%m%d%H%M%S')}",

            spare_part_id=spare_part_id,

            quantity=quantity,

            reason=reason,

            urgency=urgency,

            usage_description=usage_description,

            requester_id=current_user.id,

            requester_name=current_user.username,

            department=getattr(current_user, 'department', None),

            approval_status='pending',

            status='pending'

        )

        db.session.add(req)

        db.session.commit()

        log_audit('create', 'spare_part_request', req.id, f"创建备件申请: {req.id}", user_id=current_user.id if current_user.is_authenticated else None)

        send_new_request_notification(req)

        return jsonify(success=True, message='申请提交成功', request_id=req.id)

    except Exception as e:

        db.session.rollback()

        current_app.logger.error(f"添加申请失败: {str(e)}")

        return jsonify(success=False, message=str(e)), 500


\n\n"""
s=s[:start]+newblock+s[end:]
p.write_text(s.replace('\n','\r\n'), encoding='utf-8')
print('add req function replaced')
