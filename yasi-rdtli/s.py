# -*- coding: utf-8 -*-
"""
OpenCode 风格三栏 HTML 生成器
- 左：14 篇文档（一级）+ 当前文档 ## 标题（二级）
- 中：文档内容
- 右：当前页 ### 标题（页内目录）
"""
import os
import re
import sys
import shutil
import markdown
from pathlib import Path
from datetime import datetime
from html import escape

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

# ---------------- 配置 ----------------
MD_DIR = Path(r'D:\a.create\_MY_GIT_lib\GITEE\yasi\yasi-rdtli\md\雅思阅读13讲')
HTML_DIR = Path(r'D:\a.create\_MY_GIT_lib\GITEE\yasi\yasi-rdtli\HTML')
ONLY_FILES = None  # None = 全部生成；或传 set 限定子集

# 文件名映射：md 中文名 → 英文 HTML 名（HTML 文件间会互相 href 跳转，禁中文）
FILE_NAME_MAP = {f'阅读课程_{i:02d}.md': f'lesson-{i:02d}.html' for i in range(1, 15)}
FILE_NAME_MAP['阅读课程_00.md'] = 'index-source.html'  # 防御性 fallback


# ---------------- 标题提取 ----------------
COURSE_TITLE_RE = re.compile(r'雅思[\-－]?\s*(\d+)\s*[\.、．]\s*([^\s|·｜\|]+)')
LESSON_NUM_RE = re.compile(r'阅读课程_(\d+)')

def extract_display_title(h1: str, h2_first: str, fname: str) -> str:
    """提取显示标题：第N讲 · XXX"""
    # 1) 优先匹配 "雅思-N.XXX" 模式
    if h1:
        m = COURSE_TITLE_RE.search(h1)
        if m:
            return f'第{m.group(1)}讲 · {m.group(2)}'
        # 2) H1 拆 | 后取 "雅思-XXX" 之外的描述部分
        parts = [p.strip() for p in h1.split('|') if p.strip()]
        for p in parts:
            if '雅思-' in p or '雅思阅读全解' in p or re.match(r'^雅思阅读全解13讲\s*[\-－]?\s*\d*$', p):
                continue
            # 提取 " - N" 之后的部分作为课程名
            sub = re.sub(r'^[\-－]\s*\d+\s*[\.、．]?\s*', '', p).strip()
            if sub and len(sub) > 1:
                m2 = LESSON_NUM_RE.search(fname)
                num = m2.group(1) if m2 else ''
                return f'第{num}讲 · {sub}' if num else sub
    # 3) H1 没有有用信息就用 H2 章节（去掉前面的 "## N" 编号）
    m2 = LESSON_NUM_RE.search(fname)
    num = m2.group(1) if m2 else ''
    if h2_first:
        cleaned = re.sub(r'^\d+\s*[\.、．]?\s*', '', h2_first).strip()
        if cleaned and cleaned != h2_first:
            return f'第{num}讲 · {cleaned}' if num else cleaned
    return f'第{num}讲' if num else (h2_first or fname)


# ---------------- Markdown 解析 ----------------
def slugify(text: str) -> str:
    s = re.sub(r'[^\w\u4e00-\u9fff\- ]+', '', text).strip().lower()
    s = re.sub(r'\s+', '-', s)
    return s or 'h'


def parse_md_structure(md_text: str):
    """
    解析 md 标题结构，给每个标题加 id 锚点
    返回: (h1_raw, h1_display, sections, new_md_text)
    h1_raw: 原始 H1（用于提取课程名）
    h1_display: 简化 H1（用于页面显示）
    sections: [{'h2': 标题, 'anchor': ..., 'children': [{'h3', 'anchor'}]}]
    """
    h1_raw = None
    h1_display = None
    sections = []
    current_section = None
    new_lines = []
    used_anchors = set()

    def unique_anchor(base: str) -> str:
        a = base
        i = 2
        while a in used_anchors:
            a = f'{base}-{i}'
            i += 1
        used_anchors.add(a)
        return a

    in_first_h1 = True
    for line in md_text.splitlines():
        if line.startswith('# ') and in_first_h1:
            raw_h1 = line[2:].strip()
            h1_raw = raw_h1
            # 简化 H1 用于显示：取第一个 | 之前
            h1_display = raw_h1.split('|')[0].strip() or raw_h1
            in_first_h1 = False
            new_lines.append(f'# {h1_display}')
            continue
        if line.startswith('## '):
            title = line[3:].strip()
            anchor = unique_anchor(slugify(title) or f'sec{len(sections)}')
            current_section = {'h2': title, 'anchor': anchor, 'children': []}
            sections.append(current_section)
            new_lines.append(f'## <a id="{anchor}"></a>{title}')
            continue
        if line.startswith('### '):
            title = line[4:].strip()
            anchor = unique_anchor(slugify(title) or f'sub{len(used_anchors)}')
            if current_section is None:
                current_section = {'h2': '(无章节)', 'anchor': 'top', 'children': []}
                sections.append(current_section)
            current_section['children'].append({'h3': title, 'anchor': anchor})
            new_lines.append(f'### <a id="{anchor}"></a>{title}')
            continue
        new_lines.append(line)

    return h1_raw, h1_display, sections, '\n'.join(new_lines)


# ---------------- 搜索 JS 块 ----------------
# 用 .format() 处理模板时不能直接含 { } ，所以先 format 再用占位符 replace 注入
SEARCH_JS = '''<script>
(function(){
  var input = document.getElementById('search-input');
  var panel = document.getElementById('search-panel');
  if (!input || !panel) return;
  var main = document.querySelector('.col-main');
  var leftLinks = Array.prototype.slice.call(document.querySelectorAll('.col-left ul li a'));
  var rightLinks = Array.prototype.slice.call(document.querySelectorAll('.col-right ul li a'));

  function escHtml(s){
    return s.replace(/[&<>"']/g, function(c){
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];
    });
  }
  function escapeRegex(s){
    return s.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&');
  }
  function clearHighlights(){
    if (!main) return;
    var marks = main.querySelectorAll('mark.search-hl');
    for (var i = 0; i < marks.length; i++) {
      var m = marks[i];
      var text = document.createTextNode(m.textContent);
      m.parentNode.replaceChild(text, m);
    }
    main.normalize();
  }
  function highlightInMain(kw){
    if (!main) return;
    clearHighlights();
    if (!kw) return;
    var re = new RegExp(escapeRegex(kw), 'gi');
    var walker = document.createTreeWalker(main, NodeFilter.SHOW_TEXT, {
      acceptNode: function(n){
        if (!n.nodeValue || !n.nodeValue.trim()) return NodeFilter.FILTER_REJECT;
        var p = n.parentElement;
        if (!p) return NodeFilter.FILTER_REJECT;
        var tag = p.tagName;
        if (tag === 'SCRIPT' || tag === 'STYLE' || tag === 'CODE' || tag === 'PRE') return NodeFilter.FILTER_REJECT;
        if (p.closest && p.closest('mark.search-hl')) return NodeFilter.FILTER_REJECT;
        return n.nodeValue.toLowerCase().indexOf(kw.toLowerCase()) >= 0 ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
      }
    });
    var nodes = [];
    var n;
    while ((n = walker.nextNode())) nodes.push(n);
    for (var i = 0; i < nodes.length; i++) {
      var node = nodes[i];
      var src = node.nodeValue;
      var html = '';
      var last = 0;
      var match;
      re.lastIndex = 0;
      while ((match = re.exec(src)) !== null) {
        html += escHtml(src.slice(last, match.index));
        html += '<mark class="search-hl">' + escHtml(match[0]) + '</mark>';
        last = match.index + match[0].length;
        if (match[0].length === 0) re.lastIndex++;
      }
      html += escHtml(src.slice(last));
      var tmp = document.createElement('span');
      tmp.innerHTML = html;
      var parent = node.parentNode;
      while (tmp.firstChild) parent.insertBefore(tmp.firstChild, node);
      parent.removeChild(node);
    }
  }
  function search(q){
    q = (q || '').trim();
    panel.innerHTML = '';
    if (!q) {
      panel.hidden = true;
      leftLinks.forEach(function(a){ a.parentElement.style.display = ''; });
      rightLinks.forEach(function(a){ a.parentElement.style.display = ''; });
      clearHighlights();
      return;
    }
    var qLower = q.toLowerCase();
    var courseHits = leftLinks.filter(function(a){
      return a.textContent.toLowerCase().indexOf(qLower) >= 0;
    });
    leftLinks.forEach(function(a){
      a.parentElement.style.display = courseHits.indexOf(a) >= 0 ? '' : 'none';
    });
    var sectionHits = rightLinks.filter(function(a){
      return a.textContent.toLowerCase().indexOf(qLower) >= 0;
    });
    rightLinks.forEach(function(a){
      a.parentElement.style.display = sectionHits.indexOf(a) >= 0 ? '' : 'none';
    });
    var parts = [];
    if (courseHits.length) {
      parts.push('<div class="sp-group">课程（' + courseHits.length + '）</div>');
      parts.push('<ul>' + courseHits.map(function(a){
        return '<li><a href="' + a.getAttribute('href') + '">' + escHtml(a.textContent) + '</a></li>';
      }).join('') + '</ul>');
    }
    if (sectionHits.length) {
      parts.push('<div class="sp-group">本页小节（' + sectionHits.length + '）</div>');
      parts.push('<ul>' + sectionHits.map(function(a){
        return '<li><a href="' + a.getAttribute('href') + '">' + escHtml(a.textContent) + '</a></li>';
      }).join('') + '</ul>');
    }
    if (!parts.length) parts.push('<div class="sp-empty">无匹配结果</div>');
    panel.innerHTML = parts.join('');
    panel.hidden = false;
    highlightInMain(q);
  }
  var timer = null;
  input.addEventListener('input', function(e){
    clearTimeout(timer);
    timer = setTimeout(function(){ search(e.target.value); }, 80);
  });
  input.addEventListener('keydown', function(e){
    if (e.key === 'Escape') { input.value = ''; search(''); input.blur(); panel.hidden = true; }
  });
  document.addEventListener('click', function(e){
    if (panel.contains(e.target) || e.target === input) return;
    panel.hidden = true;
  });
  document.addEventListener('keydown', function(e){
    if ((e.ctrlKey || e.metaKey) && (e.key === 'k' || e.key === 'K')) {
      e.preventDefault();
      input.focus();
      input.select();
    }
  });
  panel.addEventListener('click', function(e){
    var a = e.target.closest('a');
    if (a) panel.hidden = true;
  });
})();
</script>'''

SEARCH_PLACEHOLDER = '__SEARCH_JS_PLACEHOLDER__'


# ---------------- HTML 模板 ----------------
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} · 雅思阅读13讲</title>
<style>
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; padding: 0; height: 100%; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif; color: #1f2328; background: #fff; }}
  a {{ color: #2c5cdc; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}

  /* 顶部 */
  .topbar {{ position: fixed; top: 0; left: 0; right: 0; height: 56px; display: flex; align-items: center; padding: 0 24px; border-bottom: 1px solid #e5e7eb; background: #fff; z-index: 10; }}
  .logo {{ font-weight: 800; font-size: 20px; letter-spacing: -0.5px; color: #111; }}
  .logo span {{ color: #6b7280; font-weight: 500; }}
  .topbar-right {{ margin-left: auto; display: flex; gap: 16px; align-items: center; position: relative; }}
  .topbar-right input {{ border: 1px solid #d1d5db; border-radius: 6px; padding: 6px 10px; font-size: 13px; width: 240px; background: #f9fafb; }}
  .topbar-right input:focus {{ outline: none; border-color: #2c5cdc; background: #fff; box-shadow: 0 0 0 3px rgba(44,92,220,0.12); }}
  #search-panel {{ position: absolute; top: 44px; right: 0; width: 360px; max-height: 70vh; overflow-y: auto; background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; box-shadow: 0 10px 25px rgba(0,0,0,0.08); padding: 8px 0; z-index: 100; font-size: 13px; }}
  #search-panel .sp-group {{ padding: 8px 14px 4px; font-size: 11px; color: #6b7280; text-transform: uppercase; font-weight: 600; letter-spacing: 0.5px; }}
  #search-panel ul {{ list-style: none; padding: 0; margin: 0; }}
  #search-panel li a {{ display: block; padding: 6px 14px; color: #374151; line-height: 1.4; font-size: 12.5px; }}
  #search-panel li a:hover {{ background: #f3f4f6; color: #1d4ed8; text-decoration: none; }}
  #search-panel .sp-empty {{ padding: 24px; text-align: center; color: #9ca3af; font-size: 12px; }}
  mark.search-hl {{ background: #fff3a3; color: inherit; padding: 0 2px; border-radius: 2px; }}

  /* 三栏布局 */
  .layout {{ display: flex; padding-top: 56px; min-height: 100vh; }}
  .col-left {{ width: 240px; flex-shrink: 0; border-right: 1px solid #e5e7eb; padding: 20px 14px 40px; overflow-y: auto; height: calc(100vh - 56px); position: sticky; top: 56px; }}
  .col-left ul {{ list-style: none; padding: 0; margin: 0 0 16px; }}
  .col-left li {{ margin: 2px 0; }}
  .col-left a {{ display: block; padding: 6px 10px; border-radius: 6px; font-size: 13.5px; color: #374151; line-height: 1.4; }}
  .col-left a:hover {{ background: #f3f4f6; text-decoration: none; }}
  .col-left a.active {{ background: #eff6ff; color: #1d4ed8; font-weight: 600; }}
  .col-left h3 {{ font-size: 11px; text-transform: uppercase; color: #6b7280; margin: 18px 8px 8px; letter-spacing: 0.5px; font-weight: 600; }}
  .col-left .sub {{ padding-left: 24px !important; font-size: 12.5px; color: #4b5563; }}

  .col-main {{ flex: 1; min-width: 0; padding: 40px 56px 80px; max-width: 820px; margin: 0 auto; }}
  .col-main h1 {{ font-size: 32px; margin-top: 0; border-bottom: 1px solid #e5e7eb; padding-bottom: 12px; line-height: 1.3; }}
  .col-main h2 {{ font-size: 24px; margin-top: 40px; padding-top: 16px; border-top: 1px solid #f3f4f6; }}
  .col-main h3 {{ font-size: 18px; margin-top: 28px; color: #1f2937; }}
  .col-main p {{ line-height: 1.75; color: #374151; }}

  .col-right {{ width: 220px; flex-shrink: 0; border-left: 1px solid #e5e7eb; padding: 24px 18px; font-size: 13px; height: calc(100vh - 56px); position: sticky; top: 56px; overflow-y: auto; }}
  .col-right h4 {{ font-size: 11px; text-transform: uppercase; color: #6b7280; margin: 0 0 12px; letter-spacing: 0.5px; font-weight: 600; }}
  .col-right ul {{ list-style: none; padding: 0; margin: 0; }}
  .col-right li {{ margin: 6px 0; }}
  .col-right a {{ color: #4b5563; line-height: 1.45; font-size: 12.5px; }}
  .col-right a:hover {{ color: #1d4ed8; }}
  .col-right .section {{ color: #1f2937; font-weight: 600; margin-top: 14px; }}
  .col-right .empty {{ color: #9ca3af; font-size: 12px; padding: 6px 0; }}

  @media (max-width: 1100px) {{ .col-right {{ display: none; }} }}
  @media (max-width: 800px) {{ .col-left {{ display: none; }} .col-main {{ padding: 24px; }} }}
</style>
</head>
<body>
<header class="topbar">
  <div class="logo">雅思阅读<span> · 13讲</span></div>
  <div class="topbar-right">
    <span style="font-size:18px;">🐙</span>
    <span style="font-size:18px;">💬</span>
    <input id="search-input" placeholder="搜索 Ctrl K" autocomplete="off">
    <div id="search-panel" hidden></div>
  </div>
</header>
<div class="layout">
  <aside class="col-left">
    <h3>课程目录</h3>
    <ul>
      {doc_list}
    </ul>
    {sub_section}
  </aside>
  <main class="col-main">
    {content}
  </main>
  <aside class="col-right">
    {page_toc}
  </aside>
</div>
{search_js}
</body>
</html>
"""


# ---------------- 构建块 ----------------
def build_doc_list_html(docs: list, current_filename: str) -> str:
    items = []
    for doc in docs:
        cls = ' class="active"' if doc['filename'] == current_filename else ''
        items.append(f'<li><a href="{doc["html_name"]}"{cls}>{escape(doc["display"])}</a></li>')
    return '\n'.join(items)


def build_sub_section_html(sections: list) -> str:
    """二级：当前文档的所有 ### 子标题（"本页问题"）"""
    children = []
    for s in sections:
        for c in s.get('children', []):
            children.append(c)
    if not children:
        return '<h3>本页问题</h3><p class="empty" style="padding:6px 10px;font-size:12px;color:#9ca3af;margin:0;">无小节</p>'
    items = ''.join(
        f'<li><a class="sub" href="#{c["anchor"]}">{escape(c["h3"])}</a></li>'
        for c in children
    )
    return f'<h3>本页问题</h3><ul>{items}</ul>'


def build_page_toc_html(sections: list) -> str:
    """右侧：本页的 ## 章节列表（简洁版）"""
    if not sections:
        return '<h4>本页章节</h4><p class="empty">无小节</p>'
    items = []
    for s in sections:
        if s.get('h2') and s['h2'] not in ('(无章节)',):
            items.append(f'<li><a href="#{s["anchor"]}">{escape(s["h2"])}</a></li>')
    if not items:
        return '<h4>本页章节</h4><p class="empty">无小节</p>'
    return f'<h4>本页章节</h4><ul>{"".join(items)}</ul>'


# ---------------- 单篇转换 ----------------
def convert_one(md_path: Path, doc_index: list) -> Path:
    raw = md_path.read_text(encoding='utf-8')
    h1_raw, h1_display, sections, new_md = parse_md_structure(raw)
    body_html = markdown.markdown(
        new_md,
        extensions=['tables', 'fenced_code', 'sane_lists'],
        output_format='html',
    )
    h2_first = sections[0]['h2'] if sections else ''
    display = extract_display_title(h1_raw, h2_first, md_path.stem)

    html_out = HTML_TEMPLATE.format(
        title=escape(display),
        doc_list=build_doc_list_html(doc_index, md_path.stem),
        sub_section=build_sub_section_html(sections),
        content=body_html,
        page_toc=build_page_toc_html(sections),
        search_js=SEARCH_PLACEHOLDER,
    )
    html_out = html_out.replace(SEARCH_PLACEHOLDER, SEARCH_JS)
    out_path = HTML_DIR / FILE_NAME_MAP.get(md_path.name, md_path.stem + '.html')
    out_path.write_text(html_out, encoding='utf-8')
    print(f'[OK]  {md_path.name} -> {out_path.name}  ({out_path.stat().st_size} bytes)')
    return out_path


def build_doc_index() -> list:
    docs = []
    for md_file in sorted(MD_DIR.glob('阅读课程_*.md')):
        raw = md_file.read_text(encoding='utf-8')
        h1_raw, h1_display, sections, _ = parse_md_structure(raw)
        h2_first = sections[0]['h2'] if sections else ''
        display = extract_display_title(h1_raw, h2_first, md_file.stem)
        html_name = FILE_NAME_MAP.get(md_file.name, md_file.stem + '.html')
        docs.append({'filename': md_file.stem, 'html_name': html_name, 'display': display})
    return docs


def main():
    if not MD_DIR.exists():
        print(f'[ERR] MD dir not found: {MD_DIR}')
        return
    HTML_DIR.mkdir(parents=True, exist_ok=True)

    print('Building doc index...')
    doc_index = build_doc_index()
    print(f'  {len(doc_index)} docs total')
    for d in doc_index:
        print(f'    {d["filename"]}  ->  {d["display"]}')
    print()

    converted = []
    for md_file in sorted(MD_DIR.glob('阅读课程_*.md')):
        if ONLY_FILES is not None and md_file.name not in ONLY_FILES:
            continue
        convert_one(md_file, doc_index)
        converted.append(md_file.stem)

    # index.html
    if converted:
        items = '\n'.join(
            f'<li><a href="{d["html_name"]}">{escape(d["display"])}</a></li>'
            for d in doc_index
            if d['filename'] in converted
        )
        index_html = HTML_TEMPLATE.format(
            title='课程目录',
            doc_list=items,
            sub_section='',
            content='<h1>雅思阅读 13 讲</h1><p>从左侧选择课程开始学习。</p>',
            page_toc='<h4>本页内容</h4><p class="empty">课程入口</p>',
            search_js=SEARCH_PLACEHOLDER,
        )
        index_html = index_html.replace(SEARCH_PLACEHOLDER, SEARCH_JS)
        (HTML_DIR / 'index.html').write_text(index_html, encoding='utf-8')
        print(f'\n[OK] index.html generated')

    print(f'\nOutput dir: {HTML_DIR}')


if __name__ == '__main__':
    main()
