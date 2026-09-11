from pathlib import Path
p=Path('blueprints/asset.py')
s=p.read_text(encoding='utf-8').replace('\r\n','\n')
old = """def spare_parts_inventory():
    spare_parts = SparePart.query.all()
    suppliers = Supplier.query.all()   # 修正：从 Supplier 查询
    low_stock = [p for p in spare_parts if p.current_stock <= p.min_stock_level]
    return render_template('asset/spare_parts_inventory.html',
                           spare_parts=spare_parts,
                           low_stock=low_stock,
                           suppliers=suppliers)
"""
new = """def spare_parts_inventory():
    parts = [_part_view(p) for p in SparePart.query.order_by(SparePart.part_name.asc()).all()]
    suppliers = Supplier.query.order_by(Supplier.name.asc()).all()
    low_stock = [p for p in parts if p.current_stock <= p.min_stock_level]
    return render_template('asset/spare_parts_inventory.html',
                           spare_parts=parts,
                           low_stock=low_stock,
                           suppliers=suppliers)
"""
if old not in s: raise SystemExit('inventory old missing')
s=s.replace(old,new,1)
old = """def spare_parts_requests():
    # 可按查询参数过滤状态，这里简单返回所有
    requests = SparePartRequest.query.order_by(SparePartRequest.requested_at.desc()).all()
    # 获取所有启用备件供下拉选择
    spare_parts = SparePart.query.filter_by(is_active=True).all()
    return render_template('asset/spare_parts_requests.html',
                           requests=requests,
                           spare_parts=spare_parts)
"""
new = """def spare_parts_requests():
    # Keep request objects as-is; template uses req.spare_part.name, which will resolve after model fix below.
    requests = SparePartRequest.query.order_by(SparePartRequest.requested_at.desc()).all()
    spare_parts = [_part_view(p) for p in SparePart.query.filter_by(is_active=True).all()]
    return render_template('asset/spare_parts_requests.html',
                           requests=requests,
                           spare_parts=spare_parts)
"""
if old not in s: raise SystemExit('requests old missing')
s=s.replace(old,new,1)
old = """    form.spare_part_id.choices = [(p.id, f"{p.name} ({p.model})") for p in SparePart.query.all()]
"""
new = """    form.spare_part_id.choices = [(p.id, f"{p.part_name or p.model or p.asset_number} ({p.model or '-'})") for p in SparePart.query.all()]
"""
if old not in s: raise SystemExit('request choices missing')
s=s.replace(old,new,1)
old = """        request = SparePartRequest(
            spare_part_id=form.spare_part_id.data,
            quantity=form.quantity.data,
            requester=current_user.username,
            reason=form.reason.data,
            urgency=form.urgency.data
        )
"""
new = """        request = SparePartRequest(
            request_number=f"SPR{datetime.now().strftime('%Y%m%d%H%M%S')}",
            spare_part_id=form.spare_part_id.data,
            quantity=form.quantity.data,
            requester_id=current_user.id,
            requester_name=current_user.username,
            reason=form.reason.data,
            urgency=form.urgency.data,
            status='pending',
            approval_status='pending',
        )
"""
if old not in s: raise SystemExit('request create block missing')
s=s.replace(old,new,1)
p.write_text(s.replace('\n','\r\n'), encoding='utf-8')
print('asset inventory/request updated')
