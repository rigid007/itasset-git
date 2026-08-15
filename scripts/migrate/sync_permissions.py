#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""权限与角色同步脚本

用途
----
`utils/permission.py` 里新增权限键后，已有的生产库不会自动获得这些权限
（`create_default_roles_and_permissions()` 只在 `init_database()` 内被调用，
而 `init_database()` 只在 `python app.py` / `python wsgi.py` 启动时执行）。

本脚本让你在**不重启应用**的前提下把权限定义同步进库。
操作是幂等的：已存在的权限不会重复创建，角色→权限映射会按最新定义重刷。

用法
----
    python sync_permissions.py              # 预演（只报告差异，不写库）
    python sync_permissions.py --execute    # 实际写入

注意
----
角色→权限映射采用**覆盖式**同步（`role.permissions = [...]`）。
如果你在界面上手工给内置角色（admin/operator/viewer/user）加过额外权限，
执行后会被重置回代码里定义的集合。自定义角色不受影响。
"""
import os
import argparse
import sys

# 使脚本可从任意目录运行（scripts/migrate -> 项目根）
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

def _parse_role_targets(src, all_codes):
    """从 create_default_roles_and_permissions 源码中解析每个角色的目标权限集合。

    仅用于 --dry-run 预览，避免为了看差异而先写库。
    """
    import re
    targets = {}
    # 匹配 {'name': 'xxx', ... 'permissions': [ ... ]}
    for m in re.finditer(
        r"'name'\s*:\s*'(\w+)'(.*?)'permissions'\s*:\s*(\[[^\]]*\])",
        src, re.S
    ):
        rname, _mid, plist = m.group(1), m.group(2), m.group(3)
        if 'for code' in plist:  # admin 用推导式拿全部权限
            targets[rname] = set(all_codes)
        else:
            targets[rname] = set(re.findall(r"'([a-z_]+(?::[a-z_]+)+)'", plist))
    return targets


def main():
    parser = argparse.ArgumentParser(description='同步权限与角色定义到数据库')
    parser.add_argument('--execute', action='store_true',
                        help='实际写入数据库（默认仅预演）')
    args = parser.parse_args()

    from app import app
    from extensions import db
    from models.config_models import Permission, Role
    from utils.permission import create_default_roles_and_permissions

    with app.app_context():
        uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
        # 隐去密码
        if '@' in uri:
            head, tail = uri.split('@', 1)
            uri = (head.split('//')[0] + '//***@' + tail)
        print('=' * 68)
        print(' 权限同步')
        print('=' * 68)
        print(f'数据库: {uri}')
        print(f'模式  : {"实际写入" if args.execute else "预演（不写库）"}')
        print('-' * 68)

        before_codes = {p.code for p in Permission.query.all()}
        before_roles = {}
        for r in Role.query.all():
            before_roles[r.name] = {p.code for p in r.permissions}

        # 从代码定义里取出目标权限清单（复用同一份源，避免两处维护）
        import inspect
        import re
        src = inspect.getsource(create_default_roles_and_permissions)
        target_codes = set(re.findall(r"\(\s*'([a-z_]+(?::[a-z_]+)+)'\s*,\s*'", src))

        new_codes = sorted(target_codes - before_codes)
        stale_codes = sorted(before_codes - target_codes)

        print(f'库中已有权限: {len(before_codes)} 个')
        print(f'代码定义权限: {len(target_codes)} 个')
        if new_codes:
            print(f'\n将新增 {len(new_codes)} 个权限:')
            for c in new_codes:
                print(f'  + {c}')
        else:
            print('\n无新增权限（库已是最新）')
        if stale_codes:
            print(f'\n库中存在但代码未定义的权限 {len(stale_codes)} 个（不会被删除）:')
            for c in stale_codes:
                print(f'  ? {c}')

        # 预算角色映射变化：内置角色是覆盖式同步，需提前暴露"会被移除"的权限
        role_targets = _parse_role_targets(src, target_codes)
        print('\n角色映射预览:')
        risky = False
        for rname, codes in sorted(role_targets.items()):
            was = before_roles.get(rname)
            if was is None:
                print(f'  {rname:10s} 新建角色，将授予 {len(codes)} 个权限')
                continue
            gained = sorted(codes - was)
            lost = sorted(was - codes)
            if lost:
                risky = True
            if gained or lost:
                print(f'  {rname:10s} {len(was)} → {len(codes)} 个权限'
                      + (f'，新增 {gained}' if gained else '')
                      + (f'，[!] 移除 {lost}' if lost else ''))
            else:
                print(f'  {rname:10s} 无变化（{len(was)} 个权限）')
        untouched = sorted(set(before_roles) - set(role_targets))
        if untouched:
            print(f'  （自定义角色不受影响: {untouched}）')
        if risky:
            print('\n[!] 上面标注"移除"的权限是手工授予的，同步后会被重置回代码定义。')

        if not args.execute:
            print('\n' + '-' * 68)
            print('预演结束，未写入任何数据。加 --execute 参数实际执行。')
            return 0

        print('\n' + '-' * 68)
        try:
            create_default_roles_and_permissions()
        except Exception as e:
            db.session.rollback()
            print(f'[ERROR] 同步失败，已回滚: {type(e).__name__}: {e}')
            return 1

        after_codes = {p.code for p in Permission.query.all()}
        added = sorted(after_codes - before_codes)
        print(f'[OK] 权限同步完成，新增 {len(added)} 个: {added if added else "（无）"}')

        # 报告角色映射变化
        for r in Role.query.order_by(Role.name).all():
            now = {p.code for p in r.permissions}
            was = before_roles.get(r.name)
            if was is None:
                print(f'[OK] 角色 {r.name}: 新建，授予 {len(now)} 个权限')
                continue
            gained = sorted(now - was)
            lost = sorted(was - now)
            if gained or lost:
                print(f'[OK] 角色 {r.name}: 共 {len(now)} 个权限'
                      + (f'，新增 {gained}' if gained else '')
                      + (f'，移除 {lost}' if lost else ''))
            else:
                print(f'     角色 {r.name}: 无变化（{len(now)} 个权限）')

        print('\n提示: 已登录的用户可能需要重新登录，权限缓存才会刷新。')
        return 0


if __name__ == '__main__':
    sys.exit(main())
