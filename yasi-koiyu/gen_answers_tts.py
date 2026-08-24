#!/usr/bin/env python3
"""Generate reference-answer audio for every Part 1 question using edge-tts,
then compress each mp3 with ffmpeg (48k mono) to keep the site snappy.

Output goes to `voice/ans/` (e.g. voice/ans/Q1.mp3), matching q.label in _init_data.js.
Re-run is safe: already-existing files are skipped.
"""
import asyncio
import json
import os
import re
import subprocess
import sys

import edge_tts

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_JS = os.path.join(ROOT, "_init_data.js")
P23_JSON = os.path.join(ROOT, "all_questions_part23.json")
OUT_DIR = os.path.join(ROOT, "voice", "ans")
RATE = "-8%"      # slightly slower reads more like a sample answer
PITCH = "+0Hz"


def load_questions():
    src = open(DATA_JS, encoding="utf-8").read()
    m = re.search(r"window\.INIT_DATA\s*=\s*(\[[\s\S]*\])\s*;?\s*$", src)
    if not m:
        raise SystemExit("cannot parse _init_data.js")
    return json.loads(m.group(1))


def load_p23():
    try:
        return json.load(open(P23_JSON, encoding="utf-8"))
    except OSError:
        return []


def compress(src, dst):
    """ffmpeg: 32kbps mono 22kHz mp3. Silence ffmpeg's normal chatter."""
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", src,
             "-codec:a", "libmp3lame", "-b:a", "32k", "-ar", "22050",
             "-ac", "1", dst],
            check=True,
        )
    except subprocess.CalledProcessError as e:
        print("  [ffmpeg failed]", src, e, file=sys.stderr)


async def gen_one(q):
    label = q["label"]
    out = os.path.join(OUT_DIR, label + ".mp3")
    if os.path.exists(out):
        print(f"skip  {label} (exists)")
        return
    tmp = out + ".raw.mp3"
    text = q.get("answer") or ""
    if not text.strip():
        print(f"warn  {label}: empty answer")
        return
    try:
        com = edge_tts.Communicate(text, voice=q.get("voice") or "en-GB-SoniaNeural",
                                   rate=RATE, pitch=PITCH)
        await com.save(tmp)
    except Exception as e:
        print(f"fail  {label}: {e}", file=sys.stderr)
        return
    compress(tmp, out)
    try:
        os.remove(tmp)
    except OSError:
        pass
    size = os.path.getsize(out) if os.path.exists(out) else 0
    print(f"ok    {label}  {size//1024}KB")


async def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    qs = load_questions() + load_p23()
    print(f"{len(qs)} questions -> {OUT_DIR}")
    # Semaphore to stay gentle on the network.
    sem = asyncio.Semaphore(4)

    async def worker(q):
        async with sem:
            await gen_one(q)

    await asyncio.gather(*(worker(q) for q in qs))
    n = len([f for f in os.listdir(OUT_DIR) if f.endswith(".mp3")])
    print(f"done: {n} answer mp3s in {OUT_DIR}")


if __name__ == "__main__":
    asyncio.run(main())
