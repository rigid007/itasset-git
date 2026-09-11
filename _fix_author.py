from pathlib import Path
p=Path('models/maintenance_models.py')
s=p.read_text(encoding='utf-8').replace('\r\n','\n')
bad = "    author = db.relationship('User', foreign_keys=[author_id], backref='knowledge_articles')\n"
# Remove first occurrence (in Supplier)
s=s.replace(bad, '', 1)
# Insert in KnowledgeArticle: find class KnowledgeArticle and its updated_at line within next 2000 chars
start=s.find('class KnowledgeArticle(db.Model):')
end=s.find('class OnCallSchedule', start)
block=s[start:end]
if 'updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)' not in block:
    raise SystemExit('kb updated_at missing')
newblock=block.replace('    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)\n', '    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)\n    author = db.relationship(\'User\', foreign_keys=[author_id], backref=\'knowledge_articles\')\n', 1)
s=s[:start]+newblock+s[end:]
p.write_text(s.replace('\n','\r\n'), encoding='utf-8')
print('author relationship fixed')
