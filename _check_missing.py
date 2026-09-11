import os, re, glob
os.chdir(r'D:\asset')
from app import app
registered = {r.endpoint for r in app.url_map.iter_rules()}
pat = re.compile(r"url_for\(\s*['\"]([^'\"]+)['\"]")
missing = {}
for path in glob.glob(r'templates/**/*.html', recursive=True):
    text = open(path, encoding='utf-8', errors='ignore').read()
    for ep in pat.findall(text):
        if ep == 'static':
            continue
        if ep not in registered:
            missing.setdefault(ep, []).append(path)
for ep in sorted(missing):
    print('\n', ep)
    for p in missing[ep][:20]: print(' ', p)
print('\nMISSING ENDPOINTS:', len(missing))
