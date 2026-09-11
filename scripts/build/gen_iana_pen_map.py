# -*- coding: utf-8 -*-
"""gen_iana_pen_map.py — 从 IANA 官方注册表生成 PEN→组织名压缩映射。

数据来源（IANA 官方，可自由使用，无 GPL 传染）：
  https://www.iana.org/assignments/enterprise-numbers/enterprise-numbers
  （即 data/enterprise-numbers.txt，IANA 定期更新，建议每季度重新下载生成）

用法:
  python scripts/build/gen_iana_pen_map.py            # 解析 data/enterprise-numbers.txt
  python scripts/build/gen_iana_pen_map.py <文件路径>  # 指定其他输入文件

输出:
  data/iana_pen.json.gz  — {"pen": {"9": "Cisco Systems", ...}, "generated": "...", "source": "..."}
  由 utils/vendor_oid_map.py 懒加载，作为 sysObjectID 厂商识别的全量兜底。
"""
import gzip
import json
import os
import re
import sys
from datetime import date

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_INPUT = os.path.join(BASE_DIR, 'data', 'enterprise-numbers.txt')
DEFAULT_OUTPUT = os.path.join(BASE_DIR, 'data', 'iana_pen.json.gz')

# 组织名清洗：去掉尾部 "(https://...)" 等括注 URL、多余空白
_PAREN_URL = re.compile(r'\s*\((?:https?://|www\.)[^)]*\)\s*')


def _clean_org(name):
    name = _PAREN_URL.sub('', name).strip()
    # 去掉行内尾注（如 "IBM ( Retired )"）
    name = re.sub(r'\s*\(\s*Retired\s*\)\s*$', '', name, flags=re.I).strip()
    return name[:80]  # 防异常长名


def parse_enterprise_numbers(path):
    """解析 IANA 文本注册表 → {pen_str: org_name}。

    文件格式（每条记录）:
        1234
          Organization Name
            Contact Person
              email&example.com
    """
    pens = {}
    current = None
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        for raw in f:
            line = raw.rstrip('\n')
            if not line.strip():
                continue
            if not line[0].isspace():
                # 顶格行：企业号或文件头
                if line.strip().isdigit():
                    current = line.strip()
                continue
            # 缩进行：第一层（2 空格）是组织名
            if current is not None and line.startswith('  ') and not line.startswith('    '):
                org = _clean_org(line.strip())
                if org and org.lower() not in ('reserved',):
                    pens[current] = org
                current = None  # 该条记录完成
    return pens


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_INPUT
    if not os.path.exists(src):
        print(f'输入文件不存在: {src}')
        print('请先下载: https://www.iana.org/assignments/enterprise-numbers/enterprise-numbers')
        sys.exit(1)

    pens = parse_enterprise_numbers(src)
    if len(pens) < 50000:  # 正常应 7 万+ 条
        print(f'警告: 仅解析到 {len(pens)} 条（正常 7 万+），请检查文件格式')

    payload = {
        'source': 'iana/enterprise-numbers',
        'generated': date.today().isoformat(),
        'count': len(pens),
        'pen': pens,
    }
    os.makedirs(os.path.dirname(DEFAULT_OUTPUT), exist_ok=True)
    with gzip.open(DEFAULT_OUTPUT, 'wt', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, separators=(',', ':'))

    size_kb = os.path.getsize(DEFAULT_OUTPUT) // 1024
    print(f'完成: {len(pens)} 条 PEN → {DEFAULT_OUTPUT} ({size_kb} KB)')
    # 抽样展示
    for k in ('9', '11', '2011', '25506', '4881', '674', '2636'):
        if k in pens:
            print(f'  {k:>6s} = {pens[k]}')


if __name__ == '__main__':
    main()
