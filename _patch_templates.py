from pathlib import Path
# knowledge_base
p=Path('templates/maintenance/knowledge_base.html')
s=p.read_text(encoding='utf-8').replace('\r\n','\n')
s=s.replace('{{ article.author_id }}', '{{ article.author.username if article.author else article.author_id }}')
p.write_text(s.replace('\n','\r\n'), encoding='utf-8')
# problem_detail
p=Path('templates/maintenance/problem_detail.html')
s=p.read_text(encoding='utf-8').replace('\r\n','\n')
s=s.replace('{{ problem.created_by }}', '{{ problem.creator.username if problem.creator else problem.created_by }}')
p.write_text(s.replace('\n','\r\n'), encoding='utf-8')
# kb_article add feedback buttons before article info card or after view counts
p=Path('templates/maintenance/kb_article.html')
s=p.read_text(encoding='utf-8').replace('\r\n','\n')
old = """                    <tr><th>闃呰娆℃暟</th><td>{{ article.view_count or 0 }}</td></tr>\n                    <tr><th>鏈夊府鍔?/th><td>{{ article.helpful_count or 0 }}</td></tr>"""
new = """                    <tr><th>闃呰娆℃暟</th><td>{{ article.view_count or 0 }}</td></tr>\n                    <tr><th>鏈夊府鍔?/th><td>{{ article.helpful_count or 0 }} / {{ article.not_helpful_count or 0 }}</td></tr>"""
# Since Chinese may be mojibake in read due console but actual file is correct UTF-8; our old text copied mojibake maybe not match.
# Use ASCII-based unique: 'view_count or 0' around article info
old = """                    <tr><th>闃呰娆℃暟</th><td>{{ article.view_count or 0 }}</td></tr>\n                    <tr><th>鏈夊府鍔?/th><td>{{ article.helpful_count or 0 }}</td></tr>"""
if old not in s:
    # fallback: locate via '{{ article.view_count or 0 }}'
    marker = '{{ article.view_count or 0 }}'
    i=s.find(marker)
    if i!=-1:
        # replace surrounding row values is harder; just leave and add feedback block after card
        pass
# Add feedback forms after article info card (before 设备信息)
anchor = "        <!-- 璁惧淇℃伅 -->"
if anchor in s:
    feedback = """        <!-- 鏈夊府鍔╁弽棣?-->\n        <div class=\"card mb-4\">\n            <div class=\"card-header\"><h5 class=\"mb-0\">鏈夊府鍔╁弽棣?/h5></div>\n            <div class=\"card-body\">\n                <p class=\"text-muted small mb-2\">杩欑瘒鏂囩珷瀵逛綘鏈夊府鍔╁悧锛?/p>\n                <form method=\"POST\" action=\"{{ url_for('maintenance_extra.kb_feedback', id=article.id) }}\" class=\"d-inline\">\n                    <input type=\"hidden\" name=\"csrf_token\" value=\"{{ csrf_token() }}\">\n                    <input type=\"hidden\" name=\"feedback\" value=\"helpful\">\n                    <button class=\"btn btn-sm btn-success\"><i class=\"fas fa-thumbs-up\"></i> 鏈夊府鍔?/button>\n                </form>\n                <form method=\"POST\" action=\"{{ url_for('maintenance_extra.kb_feedback', id=article.id) }}\" class=\"d-inline\">\n                    <input type=\"hidden\" name=\"csrf_token\" value=\"{{ csrf_token() }}\">\n                    <input type=\"hidden\" name=\"feedback\" value=\"not_helpful\">\n                    <button class=\"btn btn-sm btn-outline-danger\"><i class=\"fas fa-thumbs-down\"></i> 娌℃湁甯姪</button>\n                </form>\n            </div>\n        </div>\n"""
    s=s.replace(anchor, feedback+anchor, 1)
p.write_text(s.replace('\n','\r\n'), encoding='utf-8')
print('templates updated')
