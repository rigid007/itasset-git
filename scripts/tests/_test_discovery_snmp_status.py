# -*- coding: utf-8 -*-
"""验证 detect_snmp_status 的三色分类：
绿(ok)               = 配置的团体号正确
黄(wrong_community)  = 设备支持SNMP但团体号不正确
红(unsupported)      = 不支持SNMP
"""
import sys
sys.path.insert(0, r"D:\asset")

import blueprints.device as D


def run():
    # 模拟 snmp_get_device_info：只有指定团体号能成功
    ok_communities = {"public", "private"}

    def fake_snmp_get_device_info(ip, community, version="2c", timeout=2, retries=1):
        if community in ok_communities:
            return True, {"sys_name": f"SW-{ip}", "sys_descr": "Switch", "sys_object_id": ""}
        return False, {}

    D.snmp_get_device_info = fake_snmp_get_device_info

    passed = 0

    # 1) 配置团体号正确 -> 绿
    status, info, detail = D.detect_snmp_status("10.0.0.1", "public", "2c", timeout=2, retries=1)
    assert status == D.SNMP_STATUS_OK, f"ok 分类错误: {status}"
    assert info.get("sys_name") == "SW-10.0.0.1"
    passed += 1

    # 2) 配置团体号错误，但设备支持SNMP（fallback public 成功）-> 黄
    status, info, detail = D.detect_snmp_status("10.0.0.2", "wrongcomm", "2c", timeout=2, retries=1)
    assert status == D.SNMP_STATUS_WRONG_COMMUNITY, f"wrong_community 分类错误: {status}"
    assert "wrongcomm" in detail and "public" in detail
    passed += 1

    # 3) 配置团体号错误，fallback private 成功 -> 黄
    ok_communities.discard("public")  # 仅 private 可用
    status, info, detail = D.detect_snmp_status("10.0.0.3", "badcomm", "2c", timeout=2, retries=1)
    assert status == D.SNMP_STATUS_WRONG_COMMUNITY, f"wrong_community(private) 分类错误: {status}"
    assert "private" in detail
    passed += 1

    # 4) 完全无SNMP -> 红
    ok_communities.clear()
    status, info, detail = D.detect_snmp_status("10.0.0.4", "public", "2c", timeout=2, retries=1)
    assert status == D.SNMP_STATUS_UNSUPPORTED, f"unsupported 分类错误: {status}"
    passed += 1

    # 5) snmp_get_device_info 抛异常 -> 红（优雅降级）
    def boom(*a, **k):
        raise RuntimeError("network error")
    D.snmp_get_device_info = boom
    status, info, detail = D.detect_snmp_status("10.0.0.5", "public", "2c", timeout=1, retries=1)
    assert status == D.SNMP_STATUS_UNSUPPORTED, f"异常降级分类错误: {status}"
    passed += 1

    print(f"[PASS] detect_snmp_status 三色分类测试通过: {passed}/5")


if __name__ == "__main__":
    run()
