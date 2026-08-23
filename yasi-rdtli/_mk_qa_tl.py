# -*- coding: utf-8 -*-
"""把 s_qa.py 复制改造为 s_qa_tl.py（听力版 QA），精确替换关键配置"""
import io
from pathlib import Path

ROOT = Path(r'D:\a.create\_MY_GIT_lib\GITEE\yasi\yasi-rdtli')
src_path = ROOT / 's_qa.py'
dst_path = ROOT / 's_qa_tl.py'

s = io.open(src_path, encoding='utf-8').read()

reps = [
    # 1) 文档头部说明
    ('QA 问答版三栏 HTML 生成器\n- 输入: qa-md/qa-XX.md（问答精要，含 ## Qn 与 ### 子标题）\n- 输出: HTML/qa-XX.html（英文文件名）+ HTML/qa-index.html 目录页\n- 左一: 14 篇问答文档 | 左二: 本页问题（H3） | 右: 本页章节（H2）',
     'QA 问答版三栏 HTML 生成器（听力版）\n- 输入: qa-md-tl/qa-tl-XX.md（听力问答精要，含 ## Qn 与 ### 子标题）\n- 输出: HTML/qa-tl-XX.html（英文文件名）+ HTML/qa-tl-index.html 目录页\n- 左一: 8 篇问答文档 | 左二: 本页问题（H3） | 右: 本页章节（H2）'),
    # 2) QA_MD_DIR 路径
    (r'qa-md', r'qa-md-tl'),
    # 3) 文件名编号正则
    ("QA_NUM_RE = re.compile(r'qa-(\\d+)\\.md$')",
     "QA_NUM_RE = re.compile(r'qa-tl-(\\d+)\\.md$')"),
    # 4) glob 课程文件
    ("QA_MD_DIR.glob('qa-*.md')", "QA_MD_DIR.glob('qa-tl-*.md')"),
    # 5) 页面 title 后缀
    ('· 雅思阅读13讲</title>', '· 雅思听力8讲</title>'),
    # 6) logo
    ('<div class="logo">雅思阅读<span> · 问答精要</span></div>',
     '<div class="logo">雅思听力<span> · 问答精要</span></div>'),
    # 7) 索引文件名 + 文案
    ("(HTML_DIR / 'qa-index.html').write_text(index_html, encoding='utf-8')",
     "(HTML_DIR / 'qa-tl-index.html').write_text(index_html, encoding='utf-8')"),
    ("title='问答精要目录'", "title='听力问答精要目录'"),
    ("content='<h1>雅思阅读 13 讲 · 问答精要</h1>'",
     "content='<h1>雅思听力 8 讲 · 问答精要</h1>'"),
    ('需要完整逐字稿版请查看 <a href="index.html" style="color:#2c5cdc;">原版课程页</a>',
     '需要完整逐字稿版请查看 <a href="tl-index.html" style="color:#2c5cdc;">听力原版课程页</a>'),
    ("print(f'\\n[OK] qa-index.html generated')",
     "print(f'\\n[OK] qa-tl-index.html generated')"),
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
