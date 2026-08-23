# -*- coding: utf-8 -*-
"""
听力课程拆分脚本
- 输入: 上传的 听力课程.md（8 节课：## tl01 + ## 02~08）
- 输出: md/雅思听力8讲/听力课程_XX.md（每课独立文件，对齐阅读版格式）
- 处理: 标题行映射、时间戳独立成行、每课补 H1
"""
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

SRC = Path(r'C:\Users\Cheng\.minimax\v2\assets\2026\08\04\16-59-12-720-asset_20260804-165912-720_e04d67c4f0e2_c733ca05-听力课程.md')
OUT_DIR = Path(r'D:\a.create\_MY_GIT_lib\GITEE\yasi\yasi-rdtli\md\雅思听力8讲')
H1 = '# 雅思听力全解8讲'

# 标题行映射：原始 "## xxx" → 规范 "## NN 课程名"
TITLE_MAP = {
    '## tl01': '## 01 导学课',
    '## 02': '## 02 Form Completion 个人信息表',
    '## 03': '## 03 地图题',
    # 04~08 标题已有完整课程名，保留原样
}

# 时间戳独立成行: "[00:00 - 00:20] 内容" → "[00:00 - 00:20]\n内容"
TS_RE = re.compile(r'^(\[\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2}\])\s*(.*)$')


def split_courses(text: str) -> list:
    """按 '## ' 行切分，返回 [(raw_title_line, content_lines)]
    首个 '## ' 标题之前的内容（如文档总标题 '# 公开课'）不属于任何一课，直接丢弃"""
    lines = text.splitlines()
    courses = []
    current_title = None
    current = []
    for line in lines:
        if line.startswith('## '):
            if current_title is not None:
                courses.append((current_title, current))
            current_title = line
            current = []
        elif current_title is not None:
            current.append(line)
    if current_title is not None:
        courses.append((current_title, current))
    return courses


def format_content(lines: list) -> list:
    """时间戳独立成行；去掉内容行的前导空行；保留段落空行"""
    out = []
    for line in lines:
        m = TS_RE.match(line)
        if m and m.group(2):
            out.append(m.group(1))
            out.append(m.group(2))
        else:
            out.append(line)
    # 去掉开头多余空行
    while out and not out[0].strip():
        out.pop(0)
    return out


def main():
    text = SRC.read_text(encoding='utf-8')
    courses = split_courses(text)
    print(f'共 {len(courses)} 节课:')
    for i, (raw_title, content) in enumerate(courses, 1):
        title = TITLE_MAP.get(raw_title, raw_title)
        num = f'{i:02d}'
        body = format_content(content)
        # 去掉文件内部残留的第二个 "## "（防御：如果某课内容里又出现 ## 标题行，保留）
        md_text = f'{H1}\n\n{title}\n\n' + '\n'.join(body) + '\n'
        out_path = OUT_DIR / f'听力课程_{num}.md'
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(md_text, encoding='utf-8')
        print(f'  [OK] {out_path.name}  <- {raw_title!r}  ({out_path.stat().st_size} bytes)')

    print(f'\n输出目录: {OUT_DIR}')


if __name__ == '__main__':
    main()
