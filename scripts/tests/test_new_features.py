#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""新增功能回归：SLA 策略管理 + 重大事件标记（路由与页面接线）。

用法：
    python scripts/tests/test_new_features.py

说明：
  - 使用 admin/admin123 登录后走真实 HTTP 流程；
  - SLA 策略创建->启停->编辑->删除，结束时删除策略本身，不残留数据；
  - 重大事件标记以路由存在性 + 模板渲染校验。
"""
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))

from app import app  # noqa: E402
from extensions import db  # noqa: E402
from flask import render_template  # noqa: E402
from models.maintenance_models import SLAPolicy  # noqa: E402
from datetime import datetime  # noqa: E402


def _csrf(client, path):
    r = client.get(path)
    assert r.status_code == 200, f'GET {path} -> {r.status_code}'
    m = re.search(r'name="csrf_token" value="([^"]+)"', r.get_data(as_text=True))
    assert m, f'未找到 CSRF token in {path}'
    return m.group(1)


def test_sla_policy_crud():
    client = app.test_client()
    with client:
        login_token = _csrf(client, '/login')
        r = client.post('/login', data={
            'csrf_token': login_token, 'username': 'admin', 'password': 'admin123',
        })
        assert r.status_code in (200, 302), f'登录失败: {r.status_code}'
        assert '/login' not in (r.headers.get('Location') or ''), '登录未成功'

        token = _csrf(client, '/sla-policies')

        # 1) 创建
        r = client.post('/sla-policies/create', data={
            'csrf_token': token, 'name': '__test_policy__', 'category': 'incident',
            'priority': 'high', 'response_time': '60', 'resolution_time': '240',
            'is_active': 'on',
        }, follow_redirects=False)
        assert r.status_code == 302, f'创建失败: {r.status_code}'
        policy = SLAPolicy.query.filter_by(name='__test_policy__').first()
        assert policy is not None and policy.response_time == 60

        # 2) 启停
        r = client.post(f'/sla-policies/{policy.id}/toggle', data={'csrf_token': token})
        assert r.status_code == 302, f'toggle(停) 状态码异常: {r.status_code}'
        policy = db.session.get(SLAPolicy, policy.id)
        assert policy.is_active is False, '停用失败'
        r = client.post(f'/sla-policies/{policy.id}/toggle', data={'csrf_token': token})
        assert r.status_code == 302, f'toggle(启) 状态码异常: {r.status_code}'
        policy = db.session.get(SLAPolicy, policy.id)
        assert policy.is_active is True, '启用失败'

        # 3) 编辑
        r = client.post(f'/sla-policies/{policy.id}/edit', data={
            'csrf_token': token, 'name': '__test_policy__', 'category': 'request',
            'priority': 'low', 'response_time': '30', 'resolution_time': '120',
            'is_active': 'on',
        })
        policy = db.session.get(SLAPolicy, policy.id)
        assert policy.category == 'request' and policy.resolution_time == 120, '编辑失败'

        # 4) 删除
        r = client.post(f'/sla-policies/{policy.id}/delete', data={'csrf_token': token})
        assert SLAPolicy.query.filter_by(id=policy.id).first() is None, '删除失败'
        print('[OK] SLA 策略 CRUD 全流程通过')


def test_major_incident_wiring():
    with app.test_request_context('/'):
        rules = {r.endpoint for r in app.url_map.iter_rules()}
        assert 'maintenance.toggle_major_work_order' in rules

        class _D:
            pass
        wo = _D()
        wo.work_order_number = 'WO-TEST-001'
        wo.is_major = True
        wo.status = 'in_progress'
        wo.priority = 'critical'
        wo.title = 'test'
        wo.requester_name = 'u'
        wo.created_at = datetime.utcnow()
        wo.updated_at = datetime.utcnow()
        wo.assigned_to_name = None
        wo.id = 1

        html = render_template('maintenance/work_order_list.html',
                               work_orders=[wo], status_filter='all', priority_filter='all',
                               category_filter='all', major_filter='1', total_orders=1,
                               open_orders=1, in_progress_orders=0, closed_orders=0,
                               major_orders=1, engineers=[])
        assert 'WO-TEST-001' in html and '重大' in html

        html = render_template('maintenance/work_order_detail.html', work_order=wo)
        assert '重大事件' in html and 'toggle-major' in html and 'majorForm' in html
        print('[OK] 重大事件标记路由与页面接线通过')


if __name__ == '__main__':
    test_sla_policy_crud()
    test_major_incident_wiring()
    print('FEATURE TEST PASSED')
