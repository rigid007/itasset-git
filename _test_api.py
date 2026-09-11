import os
os.chdir(r'D:\asset')
from app import app
from extensions import db
app.config['WTF_CSRF_ENABLED'] = False
from models.maintenance_models import MaintenanceTask, SparePart, SparePartRequest
with app.test_client() as c:
    with c.session_transaction() as sess:
        sess['_user_id'] = '1'
        sess['_fresh'] = True
    r = c.post('/api/maintenance/maintenance_tasks', json={
        'name':'CODEX TEST MT', 'maintenance_type':'preventive',
        'scheduled_date':'2026-09-12T10:00:00', 'estimated_duration':60,
        'status':'scheduled','priority':'medium','device_ids':[1] if False else []
    })
    print('mt create', r.status_code, r.get_json())
    r2 = c.post('/api/maintenance/spare_parts', json={'name':'CODEX TEST PART','part_number':'CODEX-P1','category':'test','min_stock_level':2,'current_stock':3,'max_stock_level':10})
    print('sp create', r2.status_code, r2.get_json())
    # cleanup created
    with app.app_context():
        db.session.query(MaintenanceTask).filter(MaintenanceTask.name.like('CODEX TEST MT%')).delete(synchronize_session=False)
        db.session.query(SparePart).filter(SparePart.part_name=='CODEX TEST PART').delete(synchronize_session=False)
        db.session.commit()
