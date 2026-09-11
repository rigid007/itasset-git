# -*- coding: utf-8 -*-
"""验证设备发现结果弹窗的模板渲染（三色状态 + 查看结果按钮）。"""
import sys
sys.path.insert(0, r"D:\asset")

from app import app
from flask_login import current_user


def run():
    with app.test_request_context('/devices/discovery'):
        html = app.jinja_env.get_template('device_discovery.html').render(current_user=current_user)
        checks = {
            'resultsModal': '结果弹窗',
            'view-result-btn': '查看结果按钮',
            '团体号正确': '绿色状态',
            '团体号错误': '黄色状态',
            '不支持SNMP': '红色状态',
        }
        for key, label in checks.items():
            assert key in html, f"缺少 {label}: {key}"
        print(f"[PASS] device_discovery.html 渲染成功（含结果弹窗与三色状态），长度 {len(html)}")


def run_api():
    """验证发现结果 API：正确返回持久化的结果与三色汇总。"""
    from extensions import db
    from models.models import DiscoveryTask, User
    from blueprints.device import (SNMP_STATUS_OK, SNMP_STATUS_WRONG_COMMUNITY,
                                   SNMP_STATUS_UNSUPPORTED)

    task = None
    try:
        with app.app_context():
            user = User.query.first()
            if user is None:
                print("[SKIP] 库中无用户，跳过 API 测试")
                return
            task = DiscoveryTask(
                name='__TEST_RESULT_API__',
                discovery_mode='device_scan',
                discovery_type='snmp_scan',
                target_type='ip_range',
                status='completed',
            )
            task.set_target_value({'ip_range': '192.168.99.1-3'})
            task.set_last_result({
                'summary': {'total': 3, 'ok': 1, 'wrong_community': 1, 'unsupported': 1},
                'results': [
                    {'ip': '192.168.99.1', 'snmp_status': SNMP_STATUS_OK, 'online': True,
                     'device_name': 'SW-A', 'added': True, 'device_type': 'switch'},
                    {'ip': '192.168.99.2', 'snmp_status': SNMP_STATUS_WRONG_COMMUNITY, 'online': True,
                     'device_name': 'SW-B', 'device_type': 'switch'},
                    {'ip': '192.168.99.3', 'snmp_status': SNMP_STATUS_UNSUPPORTED, 'online': True,
                     'device_name': 'PC-C', 'device_type': 'pc'},
                ],
            })
            db.session.add(task)
            db.session.commit()

        client = app.test_client()
        with client.session_transaction() as sess:
            sess['_user_id'] = str(user.id)
        resp = client.get(f'/devices/discovery/tasks/{task.id}/results')
        assert resp.status_code == 200, f"HTTP {resp.status_code}: {resp.get_data(as_text=True)[:200]}"
        data = resp.get_json()
        assert data['success'] is True
        assert len(data['results']) == 3
        assert data['summary']['ok'] == 1
        assert data['summary']['wrong_community'] == 1
        assert data['summary']['unsupported'] == 1
        statuses = {r['snmp_status'] for r in data['results']}
        assert statuses == {SNMP_STATUS_OK, SNMP_STATUS_WRONG_COMMUNITY, SNMP_STATUS_UNSUPPORTED}
        print("[PASS] 发现结果 API 返回三色状态与汇总正确")
    finally:
        with app.app_context():
            if task is not None:
                db.session.delete(task)
                db.session.commit()


if __name__ == "__main__":
    run()
    run_api()
