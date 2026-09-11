from pathlib import Path
p=Path('templates/maintenance/kb_article.html')
s=p.read_text(encoding='utf-8').replace('\r\n','\n')
# Replace line containing helpful_count by simpler marker
lines=s.split('\n')
for i,line in enumerate(lines):
    if '{{ article.helpful_count or 0 }}' in line:
        lines[i] = line.replace('{{ article.helpful_count or 0 }}', '{{ article.helpful_count or 0 }} / {{ article.not_helpful_count or 0 }}')
        break
s='\n'.join(lines)
p.write_text(s.replace('\n','\r\n'), encoding='utf-8')
print('kb article count updated')
