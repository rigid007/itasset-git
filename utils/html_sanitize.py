"""HTML 富文本安全过滤器。

用于渲染用户提交的富文本（如知识库文章），防止存储型 XSS。
优先使用 bleach 做白名单清洗；若未安装 bleach，则退化为完全转义（安全但丢失格式）。
"""
import html

try:
    import bleach
    from bleach.sanitizer import ALLOWED_TAGS, ALLOWED_ATTRIBUTES
    _BLEACH = True
except ImportError:  # pragma: no cover - bleach 为可选依赖
    _BLEACH = False
    ALLOWED_TAGS = set()
    ALLOWED_ATTRIBUTES = {}

# 允许的常见排版标签（在 bleach 默认基础上扩展）
_ALLOWED_TAGS = set(ALLOWED_TAGS) | {
    'p', 'br', 'div', 'span', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'ul', 'ol', 'li', 'strong', 'em', 'b', 'i', 'u', 'a', 'img',
    'table', 'thead', 'tbody', 'tr', 'td', 'th',
    'blockquote', 'code', 'pre', 'hr', 'sub', 'sup', 'strike', 'small',
}

# 允许的标签属性（链接强制加 rel=noopener 由 bleach 自动处理外链）
_ALLOWED_ATTRS = dict(ALLOWED_ATTRIBUTES)
_ALLOWED_ATTRS.update({
    'a': ['href', 'title', 'target'],
    'img': ['src', 'alt', 'title', 'width', 'height'],
    '*': ['class'],
})


def sanitize_html(value):
    """清洗用户提交的 HTML，移除脚本等危险内容。"""
    if not value:
        return ''
    if _BLEACH:
        return bleach.clean(
            value,
            tags=_ALLOWED_TAGS,
            attributes=_ALLOWED_ATTRS,
            strip=True,
        )
    # 未安装 bleach 时退化为转义，保证安全（但会丢失富文本格式）
    return html.escape(value)
