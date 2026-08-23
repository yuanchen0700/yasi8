"""Parse Part 2 & Part 3 cue cards from the user's Markdown question bank.

Input format (per topic):
    # 中文标题
    **题目：Describe a person...**
    You should say:
    - bullet 1
    - bullet 2
    ...
    ### 教师的解析
    **审题方面** ... **思路方面** ... **结构方面** ...
    ### 答题参考
    - sentence 1 中英
    - sentence 2 中英
    ...
    ### Sample Answer
    long English paragraph
    ### Part 3
    #### Q1: ...
    **解题思路：** ...
    Sample answer: ...
    #### Q2: ...

Output:
    list of { "section": "Part 2" | "Part 3", "topic": "...",
              "label": "P2-1" | "P3-1.1", "text": "...",
              "bullets": [...], "analysis_zh": [...],
              "phrases": [...], "answer": "...",
              "audio_text": "..."   # what to send to TTS
            }
"""
import sys
import json
import re
from pathlib import Path


def parse(text: str):
    """Return list of parsed Part 2 + Part 3 entries."""
    # Find Part 2&3 section start
    m = re.search(r"^##\s+Part\s+2\s*&\s*3\s*$", text, re.MULTILINE)
    if not m:
        return []
    body = text[m.start():]

    # Each topic block starts with "# <title>" (single #, not ## ###)
    # Split on those boundaries
    lines = body.splitlines()
    topic_starts = []
    for i, ln in enumerate(lines):
        if re.match(r"^# [^#]", ln):
            title = ln.lstrip("# ").strip()
            if title.lower() in ("part 1", "part 2", "part 3", "part 2&3",
                                  "part 2 & 3"):
                continue
            topic_starts.append((i, title))

    # Build blocks
    blocks = []
    for k, (start, title) in enumerate(topic_starts):
        end = topic_starts[k + 1][0] if k + 1 < len(topic_starts) else len(lines)
        blocks.append((title, lines[start:end]))

    # Parse each block
    entries = []
    p2_counter = 0
    for title, lines_block in blocks:
        # Reassemble into text and split between Part 2 body and Part 3 body
        joined = "\n".join(lines_block)
        # Part 3 section starts at "### Part 3"
        p3_split = re.search(r"^###\s+Part\s+3\s*$", joined, re.MULTILINE)
        if p3_split:
            p2_text = joined[:p3_split.start()]
            p3_text = joined[p3_split.start():]
        else:
            p2_text = joined
            p3_text = ""

        # --- Part 2 ---
        p2 = parse_part2_cue(p2_text, title)
        if p2:
            p2_counter += 1
            p2["label"] = f"P2-{p2_counter}"
            entries.append(p2)

        # --- Part 3 ---
        for p3 in parse_part3_questions(p3_text, title):
            entries.append(p3)
    return entries


def parse_part2_cue(block: str, topic: str) -> dict | None:
    # The "题目：..." line
    m = re.search(r"\*\*题目：(.+?)\*\*", block, re.DOTALL)
    if not m:
        return None
    question_text = m.group(1).strip()

    # Bullet prompts (lines starting with "- " under "You should say:")
    bullets = []
    m = re.search(r"You should say:\s*\n(.*?)(?=\n###|\n##|\Z)", block, re.DOTALL)
    if m:
        for ln in m.group(1).splitlines():
            ln = ln.strip()
            if ln.startswith("- "):
                bullets.append(ln[2:].strip())

    # Chinese analysis (3 sections)
    analysis_zh = []
    for section_h in ["审题方面", "思路方面", "结构方面"]:
        m = re.search(rf"\*\*{section_h}\*\*\s*(.+?)(?=\*\*[^*]+\*\*|###|\Z)",
                      block, re.DOTALL)
        if m:
            text = " ".join(s.strip() for s in m.group(1).splitlines() if s.strip())
            analysis_zh.append({"section": section_h, "text": text})

    # 答题参考: lines starting with "- " under "### 答题参考"
    phrases = []
    m = re.search(r"### 答题参考\s*\n(.+?)(?=\n###|\n##|\Z)", block, re.DOTALL)
    if m:
        for ln in m.group(1).splitlines():
            ln = ln.strip()
            if ln.startswith("- "):
                phrases.append(ln[2:].strip())

    # Sample Answer paragraph
    answer = ""
    m = re.search(r"### Sample Answer\s*\n(.+?)(?=\n###|\n##|\Z)", block, re.DOTALL)
    if m:
        answer = " ".join(s.strip() for s in m.group(1).splitlines() if s.strip())

    # For TTS: read the question text + bullets (so the examiner reads the prompt)
    audio_text = question_text
    if bullets:
        audio_text += " You should say: " + "; ".join(bullets)

    return {
        "section":     "Part 2",
        "topic":       topic,
        "text":        question_text,
        "bullets":     bullets,
        "analysis_zh": analysis_zh,
        "phrases":     phrases,
        "answer":      answer,
        "audio_text":  audio_text,
    }


def parse_part3_questions(block: str, topic: str):
    """Each Part 3 question is a `#### QN: ...` block."""
    if not block.strip():
        return
    # Find all Q-block boundaries #### Q1: ... until next #### or end
    q_pattern = re.compile(r"^####\s+(Q\d+):\s*(.+?)$", re.MULTILINE)
    matches = list(q_pattern.finditer(block))
    # also count Part 2 index for label
    parent_label = None

    for i, m in enumerate(matches):
        qid     = m.group(1)        # e.g. "Q1"
        text    = m.group(2).strip()
        # Slice from this q header to the next q header (or end)
        start   = m.end()
        end     = matches[i + 1].start() if i + 1 < len(matches) else len(block)
        seg     = block[start:end]

        # 解题思路
        strategy = ""
        m2 = re.search(r"\*\*解题思路[：:]\*\*\s*(.+?)(?=Sample answer|\Z)", seg, re.DOTALL)
        if m2:
            strategy = " ".join(s.strip() for s in m2.group(1).splitlines() if s.strip())

        # Sample answer
        answer = ""
        m2 = re.search(r"Sample answer:\s*\n(.+?)(?=\n####|\n###|\Z)", seg, re.DOTALL)
        if m2:
            answer = " ".join(s.strip() for s in m2.group(1).splitlines() if s.strip())

        yield {
            "section":    "Part 3",
            "topic":      topic,
            "label":      f"P3-{topic}-{qid}",  # unique across all topics
            "text":       text,
            "strategy":   strategy,
            "phrases":    [],
            "answer":     answer,
            "audio_text": text,
        }


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("file", help="path to Markdown question bank")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    text = Path(args.file).read_text(encoding="utf-8", errors="replace")
    entries = parse(text)

    if args.json:
        print(json.dumps(entries, ensure_ascii=False, indent=2))
        return

    p2 = sum(1 for e in entries if e["section"] == "Part 2")
    p3 = sum(1 for e in entries if e["section"] == "Part 3")
    print(f"Part 2 cue cards: {p2}")
    print(f"Part 3 questions: {p3}")
    print(f"Total: {len(entries)}")
    print()
    print("sample P2:")
    for e in entries[:1]:
        if e["section"] != "Part 2": continue
        print(f"  topic: {e['topic']}")
        print(f"  text:  {e['text'][:100]}...")
        print(f"  bullets: {len(e['bullets'])}, phrases: {len(e['phrases'])}, answer: {len(e['answer'])} chars")
    print("\nsample P3 (first 2):")
    for e in entries:
        if e["section"] == "Part 3":
            print(f"  {e['label']}: {e['text'][:80]}...")


if __name__ == "__main__":
    main()