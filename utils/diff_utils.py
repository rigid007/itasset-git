"""配置差异比较工具"""
import difflib


def generate_diff_html(old_text, new_text):
    """生成逐行差异对比HTML"""
    old_lines = old_text.splitlines(keepends=True)
    new_lines = new_text.splitlines(keepends=True)
    diff = difflib.unified_diff(old_lines, new_lines, n=3)
    return ''.join(diff)


def generate_side_by_side_html(old_text, new_text):
    """生成左右对照的差异HTML"""
    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()
    diff = list(difflib.Differ().compare(old_lines, new_lines))

    left_parts = []
    right_parts = []
    left_line_no = 0
    right_line_no = 0

    for line in diff:
        op = line[0] if line else ' '
        content = line[2:] if len(line) > 2 else ''

        if op == ' ':
            left_line_no += 1
            right_line_no += 1
            left_parts.append((left_line_no, content, 'unchanged'))
            right_parts.append((right_line_no, content, 'unchanged'))
        elif op == '-':
            left_line_no += 1
            left_parts.append((left_line_no, content, 'removed'))
        elif op == '+':
            right_line_no += 1
            right_parts.append((right_line_no, content, 'added'))
        else:
            # '?' lines — skip
            continue

    # Pad shorter side
    max_len = max(len(left_parts), len(right_parts))
    while len(left_parts) < max_len:
        left_parts.append((None, '', 'empty'))
    while len(right_parts) < max_len:
        right_parts.append((None, '', 'empty'))

    return left_parts, right_parts


def detect_changes(old_text, new_text):
    """返回变更摘要列表"""
    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()
    diff = list(difflib.Differ().compare(old_lines, new_lines))

    changes = []
    added = 0
    removed = 0
    modified = 0

    for line in diff:
        if not line:
            continue
        op = line[0]
        content = line[2:] if len(line) > 2 else ''
        if op == '+':
            added += 1
            changes.append({'type': 'added', 'content': content})
        elif op == '-':
            removed += 1
            changes.append({'type': 'removed', 'content': content})

    lines_changed = added + removed
    modified = min(added, removed)

    summary_parts = []
    if lines_changed > 0:
        summary_parts.append(f'共{lines_changed}行变更')
    if added > 0:
        summary_parts.append(f'+{added}行新增')
    if removed > 0:
        summary_parts.append(f'-{removed}行删除')

    return {
        'summary': ', '.join(summary_parts) if summary_parts else '无变更',
        'added': added,
        'removed': removed,
        'modified': modified,
        'total_changes': lines_changed,
    }
