"""Parse a JSON or Markdown question bank into structured records.

Two formats accepted:

FORMAT A — JSON (compact, machine-readable)
--------------------------------------------
[
  {
    "topic": "Tidiness",          // optional
    "label": "Q1",                // optional; auto-generated if missing
    "text":  "Do you like to keep things tidy?",
    "phrases": ["clean environment 整洁环境", "..."],   // optional
    "answer": "Yes, I do like..."                         // optional
  },
  ...
]

  OR an object with a "questions" key:
  { "topic": "Mirrors", "questions": [ ... ] }

  Each question may also carry a "voice" hint (e.g. "en-US-BrianNeural")
  to override the rotation default.

FORMAT B — Markdown (human-readable)
-----------------------------------
# Tidiness

## Q1: Do you like to keep things tidy?

Useful phrases:
- clean environment 整洁环境
- feel more comfortable 感觉更舒服
- stay organised 保持有条理

Sample answer:
Yes, I do like to keep things tidy, because a clean environment...

## Q2: Did you use to keep your room tidy as a child?
...

Heuristics for Markdown:
- Heading 1 / Heading 2 with no "Question" → topic name
- Heading 2 / Heading 3 containing "Question" or "Q1:" → question text
- Lines under "Useful phrases:" until next heading → phrase list (one per line)
- Lines under "Sample answer:" until next heading → answer paragraph

Usage
-----
    .venv/Scripts/python parse_questions.py <file>             # auto-detect
    .venv/Scripts/python parse_questions.py <file> --json      # emit JSON
    .venv/Scripts/python parse_questions.py <file> --topic X   # filter to topic
"""
import sys
import json
import re
import argparse
from pathlib import Path


def parse_json(path: Path):
    raw = path.read_text(encoding="utf-8", errors="replace")
    data = json.loads(raw)
    if isinstance(data, dict) and "questions" in data:
        topic_default = data.get("topic")
        data = data["questions"]
    else:
        topic_default = None
    out = []
    for i, q in enumerate(data):
        label = q.get("label") or f"Q{i+1}"
        out.append({
            "topic":  q.get("topic", topic_default),
            "label":  label,
            "text":   (q.get("text") or "").strip(),
            "phrases": q.get("phrases") or [],
            "answer": (q.get("answer") or "").strip(),
            "voice":  q.get("voice"),  # optional override
        })
    return out


QHEAD = re.compile(r"^#{1,6}\s+(?:Question\s*\d+\s*[:：\.]\s*|Q\d+\s*[:：\.\)]\s*)(.+)$", re.IGNORECASE)
TOPIC_HEAD = re.compile(r"^#{1,6}\s+(.+)$")
SECTION_RE = re.compile(r"^(useful phrases|sample answer|phrases|answer)\s*[:：]?\s*$", re.IGNORECASE)


def parse_markdown(path: Path, part1_only: bool = False):
    """Parse a Markdown question bank into structured records.

    If part1_only=True, the text is truncated at the first occurrence of
    "## Part 2" or "## Part 3" heading, since the file mixes Part 1 (Q&A)
    and Part 2/3 (cue cards) sections.
    """
    raw = path.read_text(encoding="utf-8", errors="replace")
    if part1_only:
        cut = re.search(r"^##\s+Part\s+(?:2|2\s*&\s*3|3)\s*$", raw, re.MULTILINE)
        if cut:
            raw = raw[:cut.start()]
    lines = raw.splitlines()

    # Pass 1: identify heading levels
    #   lines[i] is a heading if it starts with one-or-more "#"
    # We'll treat any "# ... Question N" or "# ... QN" line as a question header.
    # Plain "# TopicName" headings (no Question keyword, short) are topic names.

    blocks = []  # each block: {type: 'topic'|'question', title, start, end}
    for i, ln in enumerate(lines):
        if not ln.lstrip().startswith("#"):
            continue
        m = QHEAD.match(ln.strip())
        if m:
            blocks.append({"type": "question", "title": m.group(1).strip(),
                           "start": i, "level": len(ln) - len(ln.lstrip())})
        else:
            t = TOPIC_HEAD.match(ln.strip())
            if t and len(t.group(1)) <= 60 and "question" not in t.group(1).lower():
                # Filter out section headers like "Part 1", "Part 2", "Part 3"
                title = t.group(1).strip()
                if re.match(r"^Part\s+[123]$", title, re.IGNORECASE):
                    continue
                blocks.append({"type": "topic", "title": title,
                               "start": i, "level": len(ln) - len(ln.lstrip())})

    # Pair each question with the most recent preceding topic
    out = []
    last_topic = None
    q_counter = 0
    for idx, b in enumerate(blocks):
        if b["type"] == "topic":
            last_topic = b["title"]
            continue
        q_counter += 1
        # gather content from this question heading up to the next block
        start = b["start"] + 1
        end = blocks[idx + 1]["start"] if idx + 1 < len(blocks) else len(lines)
        seg = lines[start:end]

        # segment by SECTION_RE
        phrases, answer = [], ""
        state = "skip"  # before any section marker
        buf = []
        cur_phrases, cur_answer = [], ""
        for ln in seg:
            if SECTION_RE.match(ln.strip()):
                # flush previous
                if state == "phrases":
                    cur_phrases = [l.strip().lstrip("-").lstrip("*").strip() for l in buf if l.strip()]
                elif state == "answer":
                    cur_answer = " ".join(s for s in (l.strip() for l in buf) if s)
                m2 = SECTION_RE.match(ln.strip())
                kind = m2.group(1).lower()
                if "phrase" in kind:
                    state = "phrases"
                else:
                    state = "answer"
                buf = []
                continue
            # skip markdown table separators and headings
            if ln.strip().startswith("#") or re.match(r"^[-:\s|]+$", ln):
                continue
            if state in ("phrases", "answer"):
                buf.append(ln)

        # tail flush
        if state == "phrases":
            cur_phrases = [l.strip().lstrip("-").lstrip("*").strip() for l in buf if l.strip()]
        elif state == "answer":
            cur_answer = " ".join(s for s in (l.strip() for l in buf) if s)

        out.append({
            "topic":   last_topic,
            "label":   f"Q{q_counter}",
            "text":    b["title"],
            "phrases": cur_phrases,
            "answer":  cur_answer,
        })
    return out


def detect_format(path: Path) -> str:
    head = path.read_text(encoding="utf-8", errors="replace")[:512].lstrip()
    if head.startswith("{") or head.startswith("["):
        return "json"
    return "markdown"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file", help="path to JSON or Markdown question bank")
    ap.add_argument("--json", action="store_true", help="emit JSON only")
    ap.add_argument("--topic", help="filter to one topic")
    ap.add_argument("--part1-only", action="store_true",
                    help="for Markdown: only parse Part 1 section, stop at Part 2/3")
    args = ap.parse_args()

    path = Path(args.file)
    if not path.exists():
        print(f"file not found: {path}", file=sys.stderr)
        sys.exit(1)

    fmt = detect_format(path)
    print(f"# detected format: {fmt}", file=sys.stderr)
    qs = parse_json(path) if fmt == "json" else parse_markdown(path, part1_only=args.part1_only)

    if args.topic:
        qs = [q for q in qs if (q.get("topic") or "").lower() == args.topic.lower()]

    if args.json:
        print(json.dumps(qs, ensure_ascii=False, indent=2))
        return

    last_topic = None
    for q in qs:
        if q.get("topic") != last_topic:
            print()
            print(f"### Topic: {q.get('topic') or '(unspecified)'}")
            last_topic = q.get("topic")
        print(f"  {q['label']}: {q['text']}")
        if q["phrases"]:
            for p in q["phrases"]:
                print(f"      - {p}")
        if q["answer"]:
            print(f"      answer: {q['answer'][:80]}...")


if __name__ == "__main__":
    main()