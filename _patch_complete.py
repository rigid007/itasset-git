from pathlib import Path
p=Path('blueprints/maintenance_routes.py')
s=p.read_text(encoding='utf-8').replace('\r\n','\n')
start=s.find('def complete_change(change_id):')
end=s.find("@maintenance_bp.route('/change/<int:change_id>/print')", start)
if start==-1 or end==-1: raise SystemExit('complete change bounds missing')
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
s = s[:start] + new + s[end:]
p.write_text(s.replace('\n','\r\n'), encoding='utf-8')
print('complete route updated')
