from pathlib import Path
s=Path('templates/base.html').read_text(encoding='utf-8').replace('\r\n','\n')
i=s.find('<!--')
# find around '宸ュ崟妯℃澘' can't because mojibake? use 'work_order_templates'
i=s.find("url_for('maintenance.work_order_templates')")
print(i)
print(repr(s[i-200:i+800]))
