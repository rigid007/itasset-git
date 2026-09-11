from pathlib import Path
p=Path('blueprints/asset.py')
s=p.read_text(encoding='utf-8').replace('\r\n','\n')
# replace spare_parts_inventory function between def and next @asset_bp.route('/spare_parts/requests')
start=s.find('def spare_parts_inventory():')
end=s.find("@asset_bp.route('/spare_parts/requests')", start)
if start==-1 or end==-1: raise SystemExit('inventory bounds missing')
new = """def spare_parts_inventory():

    parts = [_part_view(p) for p in SparePart.query.order_by(SparePart.part_name.asc()).all()]

    suppliers = Supplier.query.order_by(Supplier.name.asc()).all()

    low_stock = [p for p in parts if p.current_stock <= p.min_stock_level]

    return render_template('asset/spare_parts_inventory.html',

                           spare_parts=parts,

                           low_stock=low_stock,

                           suppliers=suppliers)


\n\n"""
s=s[:start]+new+s[end:]
# replace spare_parts_requests function between def and next @asset_bp.route('/spare_parts/request/create')
start=s.find('def spare_parts_requests():')
end=s.find("@asset_bp.route('/spare_parts/request/create'", start)
if start==-1 or end==-1: raise SystemExit('requests bounds missing')
new = """def spare_parts_requests():

    \"\"\"备件申请列表，默认显示全部申请。\"\"\"

    requests = SparePartRequest.query.order_by(SparePartRequest.requested_at.desc()).all()

    spare_parts = [_part_view(p) for p in SparePart.query.filter_by(is_active=True).all()]

    return render_template('asset/spare_parts_requests.html',

                           requests=requests,

                           spare_parts=spare_parts)


\n\n"""
s=s[:start]+new+s[end:]
# replace request create function between def and next @asset_bp.route('/spare_parts/usage')
start=s.find('def spare_parts_request_create():')
end=s.find("@asset_bp.route('/spare_parts/usage')", start)
if start==-1 or end==-1: raise SystemExit('request create bounds missing')
new = """def spare_parts_request_create():

    \"\"\"创建备件申请\"\"\"

    form = SparePartRequestForm()

    form.spare_part_id.choices = [(p.id, f"{p.part_name or p.model or p.asset_number} ({p.model or '-'})") for p in SparePart.query.all()]

    

    if form.validate_on_submit():

        request = SparePartRequest(

            request_number=f"SPR{datetime.now().strftime('%Y%m%d%H%M%S')}",

            spare_part_id=form.spare_part_id.data,

            quantity=form.quantity.data,

            requester_id=current_user.id,

            requester_name=current_user.username,

            reason=form.reason.data,

            urgency=form.urgency.data,

            status='pending',

            approval_status='pending'

        )

        db.session.add(request)

        db.session.commit()

        log_audit('create', 'spare_part_request', request.id, f"创建备件申请", user_id=current_user.id if current_user.is_authenticated else None)

        flash('备件申请提交成功', 'success')

        return redirect(url_for('asset.spare_parts_requests'))

    

    return render_template('asset/spare_parts_request_create.html', form=form)


\n\n"""
s=s[:start]+new+s[end:]
p.write_text(s.replace('\n','\r\n'), encoding='utf-8')
print('asset top spare funcs updated')
