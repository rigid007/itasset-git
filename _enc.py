import pathlib
p=pathlib.Path('models/maintenance_models.py')
b=p.read_bytes()[:200]
print(b)
for enc in ['utf-8','gb18030','gbk']:
    try:
        s=p.read_text(encoding=enc)
        print(enc, 'ok', s[:30])
    except Exception as e:
        print(enc, 'err', e)
