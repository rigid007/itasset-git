from pathlib import Path
p=Path('templates/base.html')
s=p.read_text(encoding='utf-8').replace('\r\n','\n')
marker = "url_for('maintenance.work_order_categories')"
i=s.find(marker)
if i==-1: raise SystemExit('work_order_categories marker missing')
j=s.find("\n                            -->\n", i)
if j==-1: raise SystemExit('closing comment missing')
insert_pos=j+len("\n                            -->\n")
block = """                            <!-- 维护计划与备件 -->\n                            <li><hr class="dropdown-divider"></li>\n                            <li class="dropdown-header">维护计划与备件</li>\n                            <li><a class="dropdown-item" href="{{ url_for('maintenance.maintenance_tasks') }}">\n                                <i class="fas fa-list-check"></i> 维护任务\n                            </a></li>\n                            <li><a class="dropdown-item" href="{{ url_for('maintenance.maintenance_schedule') }}">\n                                <i class="fas fa-calendar-alt"></i> 维护计划\n                            </a></li>\n                            <li><a class="dropdown-item" href="{{ url_for('maintenance.spare_parts_inventory') }}">\n                                <i class="fas fa-boxes"></i> 备件库存\n                            </a></li>\n                            <li><a class="dropdown-item" href="{{ url_for('maintenance.spare_parts_requests') }}">\n                                <i class="fas fa-clipboard-list"></i> 备件申请\n                            </a></li>\n                            <li><a class="dropdown-item" href="{{ url_for('maintenance.spare_parts_usage') }}">\n                                <i class="fas fa-chart-line"></i> 备件使用统计\n                            </a></li>\n                            <li><a class="dropdown-item" href="{{ url_for('maintenance.supplier_management') }}">\n                                <i class="fas fa-truck"></i> 供应商管理\n                            </a></li>\n"""
s=s[:insert_pos]+block+s[insert_pos:]
p.write_text(s.replace('\n','\r\n'), encoding='utf-8')
print('base nav updated')
