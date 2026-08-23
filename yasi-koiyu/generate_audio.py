"""Generate IELTS examiner-style audio for ALL Part 1 questions using edge-tts.

Voice ROTATION policy
---------------------
Each question gets one of 4 accents so the student trains ear-recognition
across regions (per user's "声线要换着来" requirement):

  Q1, Q5, Q9, ...  →  en-GB-SoniaNeural  (British, mature female)
  Q2, Q6, Q10,...  →  en-US-BrianNeural  (American, mid male)
  Q3, Q7, Q11,...  →  en-AU-NatashaNeural (Australian, female)
  Q4, Q8, Q12,...  →  en-CA-LiamNeural   (Canadian, male)

Q1 → Mirrors was already generated in earlier milestone; this script
regenerates it for consistency. Existing files are overwritten.

Rate: -5% for slightly slower, clearer examiner pacing.
"""
import asyncio
import edge_tts
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
VENV_PY = HERE / ".venv" / "Scripts" / "python.exe"

VOICE_PALETTE = [
    ("en-GB-SoniaNeural",   "British (mature female)"),
    ("en-US-BrianNeural",   "American (mid male)"),
    ("en-AU-NatashaNeural", "Australian (female)"),
    ("en-CA-LiamNeural",    "Canadian (male)"),
]
RATE = "-5%"


def load_questions() -> list:
    """Read parsed questions from all_questions.json (output of parse_questions.py)."""
    f = HERE / "all_questions.json"
    if not f.exists():
        sys.exit("all_questions.json missing — run `python parse_questions.py questions.md --part1-only --json > all_questions.json` first")
    return json.loads(f.read_text(encoding="utf-8"))


def voice_for(q_index_1based: int) -> tuple[str, str]:
    """Return (voice_id, accent_label) for the given question index (1-based)."""
    return VOICE_PALETTE[(q_index_1based - 1) % len(VOICE_PALETTE)]


async def synthesize_one(out_path: Path, text: str, voice: str):
    comm = edge_tts.Communicate(text, voice, rate=RATE)
    await comm.save(str(out_path))


async def main():
    questions = load_questions()
    print(f"edge-tts · voice ROTATION ({len(VOICE_PALETTE)} accents) · rate={RATE}")
    print(f"loaded {len(questions)} Part 1 questions from all_questions.json")
    print("-" * 80)

    # Voice-to-question map (saved for reference, not consumed by index.html which gets its own JS)
    voice_map = []

    # Concurrency limit — edge-tts doesn't choke but we want to be a polite citizen
    sem = asyncio.Semaphore(8)

    async def task(idx_1based, q):
        voice, accent = voice_for(idx_1based)
        out = HERE / f"Q{idx_1based}.mp3"
        async with sem:
            await synthesize_one(out, q["text"], voice)
        return {"q": idx_1based, "voice": voice, "accent": accent, "label": q.get("label"),
                "topic": q.get("topic"), "text": q["text"]}

    tasks = [task(i + 1, q) for i, q in enumerate(questions)]
    results = await asyncio.gather(*tasks)

    # Write voices.json (label, voice, accent, text) for the web app to import
    voice_map = [
        {"label": f"Q{i+1}", "voice": r["voice"], "accent": r["accent"],
         "text": r["text"], "topic": r["topic"], "qid": i+1}
        for i, r in enumerate(results)
    ]
    (HERE / "voices.json").write_text(json.dumps(voice_map, ensure_ascii=False, indent=2), encoding="utf-8")
    print("-" * 80)
    print(f"Done. {len(results)} files + voices.json written.")

    # Quick sanity counts
    from collections import Counter
    cnt = Counter(r["voice"] for r in results)
    print("\nvoice distribution:")
    for v, n in cnt.items():
        print(f"  {v:22s}  {n:>3d} questions")


if __name__ == "__main__":
    asyncio.run(main())