# -*- coding: utf-8 -*-
"""把 s.py 复制改造为 s_tl.py（听力版），精确替换关键配置"""
import io
from pathlib import Path

ROOT = Path(r'D:\a.create\_MY_GIT_lib\GITEE\yasi\yasi-rdtli')
src_path = ROOT / 's.py'
dst_path = ROOT / 's_tl.py'

s = io.open(src_path, encoding='utf-8').read()

reps = [
    # 1) 文档头部说明
    ('左：14 篇文档（一级）+ 当前文档 ## 标题（二级）',
     '左：8 篇文档（一级）+ 当前文档 ## 标题（二级）'),
    # 2) MD_DIR 路径
    (r'md\雅思阅读13讲', r'md\雅思听力8讲'),
    # 3) 文件名映射
    ("FILE_NAME_MAP = {f'阅读课程_{i:02d}.md': f'lesson-{i:02d}.html' for i in range(1, 15)}",
     "FILE_NAME_MAP = {f'听力课程_{i:02d}.md': f'tl-{i:02d}.html' for i in range(1, 9)}"),
    ("FILE_NAME_MAP['阅读课程_00.md'] = 'index-source.html'  # 防御性 fallback",
     "FILE_NAME_MAP['听力课程_00.md'] = 'tl-index-source.html'  # 防御性 fallback"),
    # 4) 课程编号正则
    ("LESSON_NUM_RE = re.compile(r'阅读课程_(\\d+)')",
     "LESSON_NUM_RE = re.compile(r'听力课程_(\\d+)')"),
    # 5) H1 跳过正则（阅读专属 → 听力专属）
    ("'雅思阅读全解' in p or re.match(r'^雅思阅读全解13讲\\s*[\\-－]?\\s*\\d*$', p)",
     "'雅思听力全解' in p or re.match(r'^雅思听力全解8讲\\s*[\\-－]?\\s*\\d*$', p)"),
    # 6) glob 课程文件
    ("MD_DIR.glob('阅读课程_*.md')", "MD_DIR.glob('听力课程_*.md')"),
    # 7) 页面 title 后缀
    ('· 雅思阅读13讲</title>', '· 雅思听力8讲</title>'),
    # 8) logo
    ('<div class="logo">雅思阅读<span> · 13讲</span></div>',
     '<div class="logo">雅思听力<span> · 8讲</span></div>'),
    # 9) 索引文件名 + 文案
    ("(HTML_DIR / 'index.html').write_text(index_html, encoding='utf-8')",
     "(HTML_DIR / 'tl-index.html').write_text(index_html, encoding='utf-8')"),
    ("title='课程目录'", "title='听力课程目录'"),
    ("content='<h1>雅思阅读 13 讲</h1><p>从左侧选择课程开始学习。</p>'",
     "content='<h1>雅思听力 8 讲</h1><p>从左侧选择课程开始学习。</p>'"),
    ("print(f'\\n[OK] index.html generated')",
     "print(f'\\n[OK] tl-index.html generated')"),
]

missed = []
for a, b in reps:
    if a in s:
        s = s.replace(a, b)
    else:
        missed.append(a[:70])
io.open(dst_path, 'w', encoding='utf-8').write(s)
print('done, missed:', len(missed))
for m in missed:
    print('  MISS:', m)
