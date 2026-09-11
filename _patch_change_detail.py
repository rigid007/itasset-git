from pathlib import Path
p=Path('templates/maintenance/change_detail.html')
s=p.read_text(encoding='utf-8').replace('\r\n','\n')
old = """        {% if change.status == 'in_progress' %}\n            <a href="{{ url_for('maintenance.complete_change', change_id=change.id) }}" class="btn btn-success">\n                <i class="fas fa-check-circle me-1"></i>瀹屾垚瀹炴柦\n            </a>\n        {% endif %}"""
new = """        {% if change.status == 'in_progress' %}\n            <button type=\"button\" class=\"btn btn-success\" data-bs-toggle=\"modal\" data-bs-target=\"#completeChangeModal\">\n                <i class=\"fas fa-check-circle me-1\"></i>瀹屾垚瀹炴柦\n            </button>\n        {% endif %}"""
if old not in s:
    # ASCII fallback: locate complete_change link block
    marker = "url_for('maintenance.complete_change', change_id=change.id)"
    i=s.find(marker)
    if i==-1: raise SystemExit('complete link missing')
    # replace the <a ...>...</a> containing marker
    start=s.rfind('{% if change.status', 0, i)
    end=s.find('{% endif %}', i)+len('{% endif %}')
    s=s[:start]+new+s[end:]
else:
    s=s.replace(old,new,1)
# Insert complete modal before approve modal
anchor = "<!-- 鎵瑰噯妯℃€佹锛堜粎鏃犲鎵归摼鏃跺惎鐢級 -->"
# fallback ascii around approveModal
if anchor not in s:
    anchor = "<!-- 鎵瑰噯妯℃€佹锛堜粎鏃犲鎵归摼鏃跺惎鐢級 -->"
if anchor not in s:
    # use id=approveModal marker and insert before its preceding comment if any
    marker2 = '<div class="modal fade" id="approveModal"'
    j=s.find(marker2)
    # find preceding comment block
    k=s.rfind('<!--',0,j)
    if k!=-1:
        anchor=s[k:j]
    else:
        anchor=None
if anchor is not None:
    modal = """<!-- Complete change modal -->\n<div class=\"modal fade\" id=\"completeChangeModal\" tabindex=\"-1\" aria-labelledby=\"completeChangeModalLabel\" aria-hidden=\"true\">\n    <div class=\"modal-dialog modal-lg\">\n        <div class=\"modal-content\">\n            <form action=\"{{ url_for('maintenance.complete_change', change_id=change.id) }}\" method=\"POST\">\n                <input type=\"hidden\" name=\"csrf_token\" value=\"{{ csrf_token() }}\">\n                <div class=\"modal-header\">\n                    <h5 class=\"modal-title\" id=\"completeChangeModalLabel\">完成变更 {{ change.change_number }}</h5>\n                    <button type=\"button\" class=\"btn-close\" data-bs-dismiss=\"modal\" aria-label=\"Close\"></button>\n                </div>\n                <div class=\"modal-body\">\n                    <div class=\"mb-3\">\n                        <label class=\"form-label\">实施结果</label>\n                        <textarea class=\"form-control\" name=\"implementation_result\" rows=\"3\">{{ change.implementation_result or '' }}</textarea>\n                    </div>\n                    <div class=\"mb-3\">\n                        <label class=\"form-label\">遇到的问题</label>\n                        <textarea class=\"form-control\" name=\"issues_encountered\" rows=\"2\">{{ change.issues_encountered or '' }}</textarea>\n                    </div>\n                    <div class=\"mb-3\">\n                        <label class=\"form-label\">实施后评审</label>\n                        <textarea class=\"form-control\" name=\"post_implementation_review\" rows=\"3\">{{ change.post_implementation_review or '' }}</textarea>\n                    </div>\n                    <div class=\"mb-3\">\n                        <label class=\"form-label\">经验教训</label>\n                        <textarea class=\"form-control\" name=\"lessons_learned\" rows=\"2\">{{ change.lessons_learned or '' }}</textarea>\n                    </div>\n                    <div class=\"mb-3\">\n                        <label class=\"form-label\">成功标准是否达成</label>\n                        <select class=\"form-select\" name=\"success_criteria_met\">\n                            <option value=\"\">-- 请选择 --</option>\n                            <option value=\"yes\" {% if change.success_criteria_met %}selected{% endif %}>是</option>\n                            <option value=\"no\" {% if change.success_criteria_met is sameas false %}selected{% endif %}>否</option>\n                        </select>\n                    </div>\n                </div>\n                <div class=\"modal-footer\">\n                    <button type=\"button\" class=\"btn btn-secondary\" data-bs-dismiss=\"modal\">取消</button>\n                    <button type=\"submit\" class=\"btn btn-success\">确认完成</button>\n                </div>\n            </form>\n        </div>\n    </div>\n</div>\n\n"""
    s=s.replace(anchor, modal+anchor, 1)
p.write_text(s.replace('\n','\r\n'), encoding='utf-8')
print('change detail updated')
