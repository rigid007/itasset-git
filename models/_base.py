# models/_base.py
"""模型共用基础工具。"""

from datetime import datetime, timezone


def utcnow():
    """返回 naive UTC 时间，用于 Column 的 default/onupdate。

    必须传函数引用（`default=utcnow`）而不是调用结果（`default=utcnow()`），
    否则 SQLAlchemy 只在模块导入时求值一次，导致同进程内所有新行时间戳相同。
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)
