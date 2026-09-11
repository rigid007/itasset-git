from pathlib import Path
p=Path('blueprints/maintenance_extra.py')
s=p.read_text(encoding='utf-8').replace('\r\n','\n')
old = """                device_type=request.form.get('device_type', ''),\n                vendor=request.form.get('vendor', ''),\n                author_id=current_user.id,\n"""
new = """                device_type=request.form.get('device_type', ''),\n                vendor=request.form.get('vendor', ''),\n                model=request.form.get('model', ''),\n                author_id=current_user.id,\n"""
if old not in s: raise SystemExit('kb create model block missing')
s=s.replace(old,new,1)
old = """            article.device_type = request.form.get('device_type', '')\n            article.vendor = request.form.get('vendor', '')\n            article.is_featured = request.form.get('is_featured') == 'on'\n"""
new = """            article.device_type = request.form.get('device_type', '')\n            article.vendor = request.form.get('vendor', '')\n            article.model = request.form.get('model', '')\n            article.is_featured = request.form.get('is_featured') == 'on'\n"""
if old not in s: raise SystemExit('kb edit model block missing')
s=s.replace(old,new,1)
# Add feedback route before kb_article route
old = "@maintenance_extra_bp.route('/kb/article/<int:id>')\n@login_required\n@permission_required('maintenance:view')\ndef kb_article(id):"
new = """@maintenance_extra_bp.route('/kb/<int:id>/feedback', methods=['POST'])\n@login_required\n@permission_required('maintenance:view')\ndef kb_feedback(id):\n    \"\"\"Record helpful/not-helpful feedback for a knowledge article.\"\"\"\n    article = KnowledgeArticle.query.get_or_404(id)\n    feedback = request.form.get('feedback', 'helpful')\n    if feedback == 'helpful':\n        article.helpful_count = int(article.helpful_count or 0) + 1\n    elif feedback == 'not_helpful':\n        article.not_helpful_count = int(article.not_helpful_count or 0) + 1\n    else:\n        flash('Invalid feedback type', 'warning')\n        return redirect(url_for('maintenance_extra.kb_article', id=article.id))\n    db.session.commit()\n    flash('Thank you for your feedback', 'success')\n    return redirect(url_for('maintenance_extra.kb_article', id=article.id))\n\n\n@maintenance_extra_bp.route('/kb/article/<int:id>')\n@login_required\n@permission_required('maintenance:view')\ndef kb_article(id):"""
if old not in s: raise SystemExit('kb article route marker missing')
s=s.replace(old,new,1)
p.write_text(s.replace('\n','\r\n'), encoding='utf-8')
print('maintenance_extra updated')
