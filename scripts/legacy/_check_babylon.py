import re
html = open(r'E:\asset\templates\dc\dc_view_babylon.html', encoding='utf-8').read()
blocks = re.findall(r'<script>(.*?)</script>', html, re.S)
target = next((b for b in blocks if 'BABYLON' in b and 'function init' in b), None)
if not target:
    print('INLINE_SCRIPT_NOT_FOUND')
else:
    target = re.sub(r'\{\{.*?\}\}', '1', target)
    open(r'E:\asset\babylon_check.js', 'w', encoding='utf-8').write(target)
    print('extracted', len(target), 'chars')
