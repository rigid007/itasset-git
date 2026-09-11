import os
os.chdir(r'D:\asset')
from app import app
from extensions import db
app.config['WTF_CSRF_ENABLED'] = False
from models.maintenance_models import ChangeRequest, ProblemRecord, KnowledgeArticle
with app.test_client() as c:
    with c.session_transaction() as sess:
        sess['_user_id'] = '1'
        sess['_fresh'] = True
    # change create via form
    r = c.post('/maintenance/change/request/new', data={
        'title':'CODEX TEST CHANGE','change_type':'normal','category':'test',
        'impact_level':'medium','risk_level':'medium','scheduled_date':'2026-09-15',
        'scheduled_start_time':'10:00','scheduled_end_time':'11:00',
        'estimated_duration_hours':'1','implementer_id':'1','affected_devices_ids':'',
        'cab_review_required':''
    }, follow_redirects=False)
    print('change create', r.status_code, r.headers.get('Location'))
    with app.app_context():
        cr = ChangeRequest.query.filter_by(title='CODEX TEST CHANGE').first()
        print('cr?', cr.id if cr else None, cr.status if cr else None, cr.change_number if cr else None)
        if cr:
            pid = cr.id
    if cr:
        r2 = c.post(f'/maintenance/change/request/{cr.id}/submit', follow_redirects=False)
        print('change submit', r2.status_code, r2.headers.get('Location'))
        with app.app_context():
            cr2 = ChangeRequest.query.get(pid)
            print('after submit', cr2.status, cr2.approval_chain.count())
        # cleanup
        with app.app_context():
            cr = ChangeRequest.query.get(pid)
            if cr:
                db.session.delete(cr); db.session.commit()
    # problem create
    r3 = c.post('/maintenance/problem/create', data={'title':'CODEX TEST PROBLEM','description':'desc','category':'test','severity':'high','priority':'high','assigned_to':'1','device_id':'','asset_id':''}, follow_redirects=False)
    print('problem create', r3.status_code, r3.headers.get('Location'))
    with app.app_context():
        pr = ProblemRecord.query.filter_by(title='CODEX TEST PROBLEM').first(); print('pr', pr.id if pr else None)
        if pr: db.session.delete(pr); db.session.commit()
    # kb create
    r4 = c.post('/maintenance/kb/create', data={'title':'CODEX TEST KB','content':'content','category':'test','status':'published','tags':'test'}, follow_redirects=False)
    print('kb create', r4.status_code, r4.headers.get('Location'))
    with app.app_context():
        ka = KnowledgeArticle.query.filter_by(title='CODEX TEST KB').first(); print('ka', ka.id if ka else None)
        if ka: db.session.delete(ka); db.session.commit()
