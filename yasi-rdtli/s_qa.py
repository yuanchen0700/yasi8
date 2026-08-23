# -*- coding: utf-8 -*-
"""
QA 问答版三栏 HTML 生成器
- 输入: qa-md/qa-XX.md（问答精要，含 ## Qn 与 ### 子标题）
- 输出: HTML/qa-XX.html（英文文件名）+ HTML/qa-index.html 目录页
- 左一: 14 篇问答文档 | 左二: 本页问题（H3） | 右: 本页章节（H2）
"""
import re
import sys
import markdown
from html import escape
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

QA_MD_DIR = Path(r'D:\a.create\_MY_GIT_lib\GITEE\yasi\yasi-rdtli\qa-md')
HTML_DIR = Path(r'D:\a.create\_MY_GIT_lib\GITEE\yasi\yasi-rdtli\HTML')
QA_NUM_RE = re.compile(r'qa-(\d+)\.md$')
DISPLAY_RE = re.compile(r'第\s*(\d+)\s*讲\s*[·\-\s]*([^（(]*)')


def extract_display_title(h1: str) -> str:
    """从 H1 提取 '第XX讲 XXX'，去掉（问答精要）后缀"""
    m = DISPLAY_RE.search(h1 or '')
    if m:
        name = m.group(2).strip()
        return f'第{m.group(1)}讲 {name}' if name else f'第{m.group(1)}讲'
    return h1 or '未命名'


def slugify(text: str) -> str:
    s = re.sub(r'[^\w\u4e00-\u9fff\- ]+', '', text).strip().lower()
    s = re.sub(r'\s+', '-', s)
    return s or 'h'


def parse_md_structure(md_text: str):
    """解析 md 标题结构并注入锚点，返回 (h1_raw, sections, new_md)"""
    h1_raw = None
    sections = []
    current_section = None
    new_lines = []
    used_anchors = set()

    def unique_anchor(base: str) -> str:
        a, i = base, 2
        while a in used_anchors:
            a = f'{base}-{i}'
            i += 1
        used_anchors.add(a)
        return a

    in_first_h1 = True
    for line in md_text.splitlines():
        if line.startswith('# ') and in_first_h1:
            h1_raw = line[2:].strip()
            in_first_h1 = False
            new_lines.append(f'# {h1_raw}')
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
    return h1_raw, sections, '\n'.join(new_lines)


# ---------------- 搜索 JS 块（与 s.py 共用同一份代码） ----------------
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
    return s.replace(/[.*+?^${}()|[\\]\\\\]/g, function(m){ return '\\\\' + m; });
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
    timer = setTimeout(function(){ search(input.value); }, 80);
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
  .col-main h2 {{ font-size: 23px; margin-top: 40px; padding-top: 16px; border-top: 1px solid #f3f4f6; }}
  .col-main h3 {{ font-size: 18px; margin-top: 28px; color: #1f2937; }}
  .col-main p {{ line-height: 1.75; color: #374151; }}
  .col-main blockquote {{ border-left: 3px solid #dbeafe; background: #f8fafc; margin: 16px 0; padding: 10px 16px; color: #4b5563; border-radius: 0 6px 6px 0; }}
  .col-main blockquote p {{ margin: 0; }}
  .col-main table {{ border-collapse: collapse; width: 100%; margin: 16px 0; font-size: 14px; }}
  .col-main th, .col-main td {{ border: 1px solid #e5e7eb; padding: 8px 12px; text-align: left; }}
  .col-main th {{ background: #f9fafb; font-weight: 600; }}
  .col-main tr:nth-child(even) td {{ background: #fcfcfd; }}

  .col-right {{ width: 220px; flex-shrink: 0; border-left: 1px solid #e5e7eb; padding: 24px 18px; font-size: 13px; height: calc(100vh - 56px); position: sticky; top: 56px; overflow-y: auto; }}
  .col-right h4 {{ font-size: 11px; text-transform: uppercase; color: #6b7280; margin: 0 0 12px; letter-spacing: 0.5px; font-weight: 600; }}
  .col-right ul {{ list-style: none; padding: 0; margin: 0; }}
  .col-right li {{ margin: 6px 0; }}
  .col-right a {{ color: #4b5563; line-height: 1.45; font-size: 12.5px; }}
  .col-right a:hover {{ color: #1d4ed8; }}
  .col-right .empty {{ color: #9ca3af; font-size: 12px; padding: 6px 0; }}

  @media (max-width: 1100px) {{ .col-right {{ display: none; }} }}
  @media (max-width: 800px) {{ .col-left {{ display: none; }} .col-main {{ padding: 24px; }} }}
</style>
</head>
<body>
<header class="topbar">
  <div class="logo">雅思阅读<span> · 问答精要</span></div>
  <div class="topbar-right">
    <a href="qa-index.html" style="font-size:13px;color:#6b7280;">目录</a>
    <input id="search-input" placeholder="搜索 Ctrl K" autocomplete="off">
    <div id="search-panel" hidden></div>
  </div>
</header>
<div class="layout">
  <aside class="col-left">
    <h3>问答文档</h3>
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


def build_doc_list_html(docs: list, current_stem: str) -> str:
    items = []
    for d in docs:
        cls = ' class="active"' if d['stem'] == current_stem else ''
        items.append(f'<li><a href="{d["html_name"]}"{cls}>{escape(d["display"])}</a></li>')
    return '\n'.join(items)


def build_sub_section_html(sections: list) -> str:
    """左二：本页问题（所有 H3）"""
    children = [c for s in sections for c in s.get('children', [])]
    if not children:
        return '<h3>本页问题</h3><p class="empty" style="padding:6px 10px;margin:0;">无小节</p>'
    items = ''.join(
        f'<li><a class="sub" href="#{c["anchor"]}">{escape(c["h3"])}</a></li>'
        for c in children
    )
    return f'<h3>本页问题</h3><ul>{items}</ul>'


def build_page_toc_html(sections: list) -> str:
    """右侧：本页 H2 章节（Q 列表）"""
    items = [f'<li><a href="#{s["anchor"]}">{escape(s["h2"])}</a></li>'
             for s in sections if s.get('h2') and s['h2'] != '(无章节)']
    if not items:
        return '<h4>本页章节</h4><p class="empty">无小节</p>'
    return f'<h4>本页章节</h4><ul>{"".join(items)}</ul>'


def convert_one(md_path: Path, doc_index: list) -> Path:
    raw = md_path.read_text(encoding='utf-8')
    h1_raw, sections, new_md = parse_md_structure(raw)
    body_html = markdown.markdown(new_md, extensions=['tables', 'fenced_code', 'sane_lists'], output_format='html')
    display = extract_display_title(h1_raw)

    html_out = HTML_TEMPLATE.format(
        title=escape(display),
        doc_list=build_doc_list_html(doc_index, md_path.stem),
        sub_section=build_sub_section_html(sections),
        content=body_html,
        page_toc=build_page_toc_html(sections),
        search_js=SEARCH_PLACEHOLDER,
    )
    html_out = html_out.replace(SEARCH_PLACEHOLDER, SEARCH_JS)
    out_path = HTML_DIR / (md_path.stem + '.html')
    out_path.write_text(html_out, encoding='utf-8')
    print(f'[OK]  {md_path.name} -> {out_path.name}  ({out_path.stat().st_size} bytes)')
    return out_path


def build_doc_index() -> list:
    docs = []
    for md_file in sorted(QA_MD_DIR.glob('qa-*.md')):
        raw = md_file.read_text(encoding='utf-8')
        h1_raw, sections, _ = parse_md_structure(raw)
        docs.append({
            'stem': md_file.stem,
            'html_name': md_file.stem + '.html',
            'display': extract_display_title(h1_raw),
        })
    return docs


def main():
    if not QA_MD_DIR.exists():
        print(f'[ERR] QA dir not found: {QA_MD_DIR}')
        return
    HTML_DIR.mkdir(parents=True, exist_ok=True)

    print('Building QA doc index...')
    doc_index = build_doc_index()
    for d in doc_index:
        print(f'    {d["stem"]}  ->  {d["display"]}')
    print()

    for md_file in sorted(QA_MD_DIR.glob('qa-*.md')):
        convert_one(md_file, doc_index)

    # 目录页 qa-index.html
    items = '\n'.join(
        f'<li><a href="{d["html_name"]}">{escape(d["display"])}</a></li>'
        for d in doc_index
    )
    index_html = HTML_TEMPLATE.format(
        title='问答精要目录',
        doc_list=items,
        sub_section='',
        content='<h1>雅思阅读 13 讲 · 问答精要</h1>'
                '<p>这是全课程的<b>问答化速查版</b>：每讲以问答（Q&A）形式浓缩核心考点与方法，'
                '左侧选择课程，右侧看本页问题。</p>'
                '<p style="color:#6b7280;">需要完整逐字稿版请查看 <a href="index.html" style="color:#2c5cdc;">原版课程页</a>。</p>',
        page_toc='<h4>本页内容</h4><p class="empty">问答入口</p>',
        search_js=SEARCH_PLACEHOLDER,
    )
    index_html = index_html.replace(SEARCH_PLACEHOLDER, SEARCH_JS)
    (HTML_DIR / 'qa-index.html').write_text(index_html, encoding='utf-8')
    print(f'\n[OK] qa-index.html generated')

    print(f'\nOutput dir: {HTML_DIR}')


if __name__ == '__main__':
    main()
