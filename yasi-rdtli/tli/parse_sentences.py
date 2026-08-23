# -*- coding: utf-8 -*-
"""解析雅思阅读考点词例句 md → 结构化 JSON，供音频生成与播放页使用。"""
import json
import re
import sys
from pathlib import Path

SRC = Path('/workspace/.monkeycode-tmp-files/d46bb56b-long-input-20260810-143517.txt')
OUT = Path('/workspace/yasi/yasi-rdtli/tli/sentences.json')

lines = SRC.read_text(encoding='utf-8').splitlines()

entries = []       # 每个考点词/同义词一个 entry
cur_entry = None
cur_keyword = None
cur_type = None    # 'word' | 'synonym'

word_re = re.compile(r'^## \S+\s+([^\s　]+)\s*[　 ]+([^\n]+)')
syn_re = re.compile(r'^### ↳ 同义词 \*\*([^*]+)\*\*[　 ]*([^\n]*)')
sentence_re = re.compile(r'^(\d+)\. \*\*(.+)\*\*$')

for line in lines:
    line = line.strip()
    m = word_re.match(line)
    if m:
        cur_keyword = m.group(1).strip()
        cur_type = 'word'
        cur_entry = {'type': 'word', 'keyword': cur_keyword, 'meaning': m.group(2).strip(), 'sentences': []}
        entries.append(cur_entry)
        continue
    m = syn_re.match(line)
    if m:
        cur_keyword = m.group(1).strip()
        cur_type = 'synonym'
        cur_entry = {'type': 'synonym', 'keyword': cur_keyword, 'meaning': m.group(2).strip(), 'sentences': []}
        entries.append(cur_entry)
        continue
    m = sentence_re.match(line)
    if m and cur_entry is not None:
        en = m.group(2).strip()
        cur_entry['sentences'].append({'en': en, 'cn': ''})
        continue
    # 中文翻译行（> 开头，属于当前句）
    if line.startswith('>') and cur_entry is not None and cur_entry['sentences']:
        cn = line.lstrip('>').strip()
        if cur_entry['sentences'][-1]['cn'] == '':
            cur_entry['sentences'][-1]['cn'] = cn

# 只保留有句子的 entry
entries = [e for e in entries if e['sentences']]

data = {'total_entries': len(entries), 'total_sentences': sum(len(e['sentences']) for e in entries), 'entries': entries}
OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
print(f'entries={len(entries)}  sentences={data["total_sentences"]}')
print(f'已写入 {OUT}')
