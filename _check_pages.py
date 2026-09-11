import os
os.chdir(r'D:\asset')
from app import app
urls = [
'/maintenance/change/requests','/maintenance/change/approval','/maintenance/change/calendar','/maintenance/change/request/new',
'/maintenance/problems','/maintenance/knowledge-base','/maintenance/knowledge-base/manage','/maintenance/kb/create','/maintenance/known-errors',
'/maintenance/spare_parts/inventory','/maintenance/spare_parts/requests','/maintenance/suppliers','/maintenance/maintenance_tasks','/maintenance/maintenance_schedule',
'/asset/spare_parts/inventory','/asset/spare_parts/requests','/asset/supplier/management','/asset/inventory'
]
with app.test_client() as c:
    with c.session_transaction() as sess:
        sess['_user_id'] = '1'
        sess['_fresh'] = True
    for url in urls:
        r = c.get(url, follow_redirects=False)
        print(url, r.status_code, r.headers.get('Location',''))
        if r.status_code >= 400:
            print(r.get_data(as_text=True)[:800])
