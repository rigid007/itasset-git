from pathlib import Path
s=Path('blueprints/asset.py').read_text(encoding='utf-8').replace('\r\n','\n')
start=s.find('def add_spare_part_request():')
end=s.find("@asset_bp.route('/spare_part_request/edit/<int:id>'", start)
print(s[start:end])
