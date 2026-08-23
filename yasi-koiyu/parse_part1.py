"""Parse Part 1 questions from _pdf_text.txt into structured records.

Usage:
    .venv/Scripts/python parse_part1.py --topic Mirrors
    .venv/Scripts/python parse_part1.py --all          # every Part 1 topic
    .venv/Scripts/python parse_part1.py --topic Mirrors --json
"""
import re
import json
import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TXT  = HERE / "_pdf_text.txt"

# --- heading detector (a topic title is a line of capitalized words on its own)
HEADING = re.compile(r"^([A-Z][A-Za-z0-9 &/\-'.]+)\s*$")
QUESTION = re.compile(r"^Question\s*(\d+)\s*:?\s*$", re.MULTILINE)

# --- split text into blocks: a heading line introduces a block; the block ends at next heading
def split_topics(text: str):
    """Split the entire PDF text into topic blocks.

    The PDF text is form-feed (\f) paged. We first locate the start of Part 1
    body (after the dotted-leader TOC), then rejoin pages with a page-break
    sentinel that the heading-detector treats as a soft separator. Each topic
    block runs from a heading line to the next heading line.
    """
    pages = text.split("\f")
    # find the page that starts Part 1 body (first page where a topic heading
    # is followed shortly by "Question")
    body_start_idx = None
    for i, p in enumerate(pages):
        if "Question" in p and "【当季新题】" in p:
            body_start_idx = i
            break
    if body_start_idx is None:
        body_start_idx = 0

    # join all body pages with a sentinel newline so question continuations
    # across pages are preserved
    body_text = "\n".join(p[1:] if p.startswith("\n") else p for p in pages[body_start_idx:])
    lines = body_text.splitlines()

    # find first real heading
    real_start = 0
    for idx, ln in enumerate(lines):
        if HEADING.match(ln):
            window = "\n".join(lines[idx:idx+250])
            if "Question" in window:
                real_start = idx
                break
    body = lines[real_start:]

    blocks = []
    current = None
    for i, ln in enumerate(body):
        m = HEADING.match(ln)
        # a real heading is short (<=40 chars), NOT a TOC dotted line, and is NOT a Question marker
        if m and len(m.group(1)) <= 40 and not m.group(1).startswith("Question"):
            lookahead = body[i+1] if i+1 < len(body) else ""
            if "....." in lookahead:
                continue  # skip TOC dotted lines
            if current is not None:
                blocks.append(current)
            current = {"topic": m.group(1).strip(), "lines": []}
        else:
            if current is not None:
                current["lines"].append(ln)
    if current is not None:
        blocks.append(current)
    return blocks

# --- parse a single topic block into list of questions
def parse_topic(topic_block):
    topic = topic_block["topic"]
    raw   = "\n".join(topic_block["lines"])
    # split by Question markers (some have ":" some don't: "Question 1:" vs "Question 3")
    parts = re.split(r"Question\s*(\d+)\s*:?", raw)
    # parts[0] = preamble, then (qid_str, content) alternating
    qs = []
    for i in range(1, len(parts), 2):
        qid_str = parts[i]
        seg = parts[i+1] if i+1 < len(parts) else ""
        seg = seg.strip()
        if not seg:
            continue
        lines = [l.strip() for l in seg.splitlines() if l.strip()]
        # find first non-empty as the question text
        qtext = lines[0] if lines else ""
        # phrases section starts after "Useful phrases:" line
        phrases = []
        answer = ""
        state = "qtext"
        for ln in lines[1:]:
            if ln.lower().startswith("useful phrases"):
                state = "phrases"; continue
            if ln.lower().startswith("sample answer"):
                state = "answer"; continue
            if state == "phrases":
                phrases.append(ln)
            elif state == "answer":
                answer = (answer + " " + ln).strip() if answer else ln
        # parse_topic helper: strip trailing page-number artifact like " 6"
        answer = re.sub(r"\s+\d{1,3}\s*$", "", answer).strip()
        qs.append({
            "topic": topic,
            "qid":   int(qid_str),
            "text":  qtext,
            "phrases": phrases,
            "answer": answer,
        })
    return qs

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic", help="filter to one topic (e.g. Mirrors)")
    ap.add_argument("--all",   action="store_true", help="dump every topic")
    ap.add_argument("--json",  action="store_true", help="emit JSON instead of @-prefixed text")
    args = ap.parse_args()

    text = TXT.read_text(encoding="utf-8", errors="replace")
    blocks = split_topics(text)
    all_qs = []
    for b in blocks:
        qs = parse_topic(b)
        all_qs.extend(qs)

    if args.topic:
        all_qs = [q for q in all_qs if q["topic"].lower() == args.topic.lower()]

    if args.json:
        print(json.dumps(all_qs, ensure_ascii=False, indent=2))
        return

    last_topic = None
    for q in all_qs:
        if q["topic"] != last_topic:
            print()
            last_topic = q["topic"]
        if not args.json:
            print(f"@topic:  {q['topic']}")
            print(f"@qid:    {q['qid']}")
            print(f"@text:   {q['text']}")
            print(f"@phrases: {', '.join(q['phrases'])}")
            print(f"@answer: {q['answer']}")
            print()

if __name__ == "__main__":
    main()