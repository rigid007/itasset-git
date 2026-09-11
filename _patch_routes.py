from pathlib import Path
p=Path('blueprints/maintenance_routes.py')
s=p.read_text(encoding='utf-8').replace('\r\n','\n')
# Replace _spare_part_view function
start=s.find('def _spare_part_view(part):')
end=s.find('\n\n\ndef _spare_request_view', start)
if start==-1 or end==-1: raise SystemExit('spare view func missing')
new = """def _spare_part_view(part):
    installed = part.installed_device
    supplier = part.supplier
    current_stock = int(part.current_stock or 0)
    min_stock = int(part.min_stock_level or 0)
    max_stock = int(part.max_stock_level or 0)
    if min_stock > 0:
        stock_status = 'low' if current_stock <= min_stock else ('excess' if (max_stock and current_stock > max_stock * 1.5) else 'normal')
    else:
        stock_status = 'normal'
    usage_percentage = 0
    if max_stock > 0:
        usage_percentage = min(100, int(current_stock / max_stock * 100))
    elif min_stock > 0:
        usage_percentage = min(100, int(current_stock / (min_stock * 3) * 100))
    return SimpleNamespace(
        id=part.id,
        asset_number=part.asset_number,
        part_number=part.asset_number,
        name=part.part_name or part.model or part.asset_number or f'SparePart {part.id}',
        part_name=part.part_name,
        model=part.model,
        vendor=part.manufacturer,
        description=part.notes,
        category=part.part_type,
        unit_price=float(part.unit_price or 0),
        current_stock=current_stock,
        min_stock_level=min_stock,
        max_stock_level=max_stock,
        stock_status=stock_status,
        is_low_stock=stock_status == 'low',
        usage_percentage=usage_percentage,
        location=part.warehouse_location,
        supplier_id=part.supplier_id,
        supplier=SimpleNamespace(id=supplier.id if supplier else None, name=supplier.name if supplier else (part.manufacturer or '-')),
        installed_device=SimpleNamespace(hostname=installed.name if installed else None),
        status=part.status,
        is_active=bool(part.is_active),
    )
"""
s = s[:start] + new + s[end:]
# Replace _spare_request_view part current stock/min from part
old = """        part=SimpleNamespace(
            id=part.id if part else None,
            name=part.part_name if part else '-',
            part_number=part.asset_number if part else '-',
            model=part.model if part else '',
            unit_price=float(part.unit_price or 0) if part else 0,
            current_stock=0,
            min_stock_level=0,
        ),
"""
new = """        part=SimpleNamespace(
            id=part.id if part else None,
            name=part.part_name if part else '-',
            part_number=part.asset_number if part else '-',
            model=part.model if part else '',
            unit_price=float(part.unit_price or 0) if part else 0,
            current_stock=int(part.current_stock or 0) if part else 0,
            min_stock_level=int(part.min_stock_level or 0) if part else 0,
        ),
"""
if old not in s: raise SystemExit('spare request part block missing')
s=s.replace(old,new,1)
# Remove duplicate first create_change_request block from @maintenance_bp.route('/change/request/new') before second? We need identify block from first decorator to docstring before import uuid.
# Find first occurrence and next occurrence of @maintenance_bp.route('/change/request/new'
first=s.find("@maintenance_bp.route('/change/request/new', methods=['GET', 'POST'])")
second=s.find("@maintenance_bp.route('/change/request/new', methods=['GET', 'POST'])", first+10)
if first==-1 or second==-1: raise SystemExit('duplicate create change missing')
# Keep second occurrence, remove from first decorator to just before second decorator.
s = s[:first] + s[second:]
# Add permission_required to create_change? second already has.
# Change complete route to accept review fields. Use a precise replacement of function body.
old = """def complete_change(change_id):
    \"\"\"瀹屾垚瀹炴柦鍙樻洿銆?\"\"\"
    change = ChangeRequest.query.get_or_404(change_id)
    if change.status != 'in_progress':
        flash('鍙湁瀹炴柦涓殑鍙樻洿鎵嶈兘瀹屾垚', 'warning')
    else:
        now = datetime.utcnow()
        change.status = 'completed'
        change.actual_end_date = now
        change.actual_duration_hours = round((now - (change.actual_start_date or now)).total_seconds() / 3600, 2)
        change.closed_by = current_user.username
        change.closed_date = now
        change.updated_by = current_user.username
        change.updated_at = now
        db.session.commit()
        log_audit('update', 'change_request', change.id,
                  f"瀹屾垚瀹炴柦鍙樻洿: {change.change_number}",
                  user_id=current_user.id if current_user.is_authenticated else None)
        flash(f'鍙樻洿 {change.change_number} 宸插畬鎴愬疄鏂?, 'success')
    return redirect(url_for('maintenance.change_detail', change_id=change.id))
"""
if old not in s:
    print('complete old not exact; skipping')
else:
    new = """def complete_change(change_id):
    \"\"\"Complete change implementation and persist post-implementation review.\"\"\"
    change = ChangeRequest.query.get_or_404(change_id)
    if change.status != 'in_progress':
        flash('Only in-progress changes can be completed', 'warning')
    else:
        now = datetime.utcnow()
        change.status = 'completed'
        change.actual_end_date = now
        change.actual_duration_hours = round((now - (change.actual_start_date or now)).total_seconds() / 3600, 2)
        change.closed_by = current_user.username
        change.closed_date = now
        change.updated_by = current_user.username
        change.updated_at = now
        change.implementation_result = request.form.get('implementation_result', change.implementation_result)
        change.issues_encountered = request.form.get('issues_encountered', change.issues_encountered)
        change.post_implementation_review = request.form.get('post_implementation_review', change.post_implementation_review)
        change.lessons_learned = request.form.get('lessons_learned', change.lessons_learned)
        success_value = request.form.get('success_criteria_met')
        if success_value in ('yes', 'on', 'true', '1'):
            change.success_criteria_met = True
        elif success_value in ('no', 'false', '0'):
            change.success_criteria_met = False
        db.session.commit()
        log_audit('update', 'change_request', change.id,
                  f"Complete change: {change.change_number}",
                  user_id=current_user.id if current_user.is_authenticated else None)
        flash(f'Change {change.change_number} completed', 'success')
    return redirect(url_for('maintenance.change_detail', change_id=change.id))
"""
    s=s.replace(old,new,1)
p.write_text(s.replace('\n','\r\n'), encoding='utf-8')
print('maintenance routes updated')
