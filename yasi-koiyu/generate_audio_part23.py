"""Generate audio for Part 2 & Part 3 questions using edge-tts.

Voice rotation: same as Part 1 (4 accents, in order: GB, US, AU, CA).
File naming: uses the question's `label` directly (e.g. "P2-1.mp3", "P3-医疗行业-Q1.mp3").

We DO NOT reuse Part 1's Q1..Q120.mp3 names because they're a different set.
"""
import asyncio
import edge_tts
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

VOICE_PALETTE = [
    "en-GB-SoniaNeural",   # British (mature female)
    "en-US-BrianNeural",   # American (mid male)
    "en-AU-NatashaNeural", # Australian (female)
    "en-CA-LiamNeural",    # Canadian (male)
]
RATE = "-5%"


def load_questions() -> list:
    f = HERE / "all_questions_part23.json"
    if not f.exists():
        sys.exit("all_questions_part23.json missing — run parse_part23.py first")
    return json.loads(f.read_text(encoding="utf-8"))


def voice_for(idx_1based: int) -> str:
    return VOICE_PALETTE[(idx_1based - 1) % len(VOICE_PALETTE)]


def safe_filename(label: str) -> str:
    """Convert label like 'P3-医疗行业-Q1' to a safe filename like 'P3-医疗行业-Q1.mp3'."""
    # lowercase Chinese stays the same; just strip trailing junk
    return label.replace("/", "-").replace("\\", "-").replace(":", "-").replace(" ", "_") + ".mp3"


async def synthesize_one(out: Path, text: str, voice: str):
    for attempt in range(3):
        try:
            comm = edge_tts.Communicate(text, voice, rate=RATE)
            await comm.save(str(out))
            return
        except Exception as e:
            if attempt == 2:
                raise
            await asyncio.sleep(2 * (attempt + 1))


async def main():
    questions = load_questions()
    print(f"edge-tts · Part 2/3 · 4-accent rotation · rate={RATE}")
    print(f"loaded {len(questions)} entries from all_questions_part23.json")
    p2 = sum(1 for q in questions if q["section"] == "Part 2")
    p3 = sum(1 for q in questions if q["section"] == "Part 3")
    print(f"  Part 2 cue cards: {p2}")
    print(f"  Part 3 questions: {p3}")
    print("-" * 80)

    sem = asyncio.Semaphore(2)  # reduced from 8 to avoid 503 from edge-tts
    voice_map = []

    async def task(idx_1based, q):
        voice = voice_for(idx_1based)
        out = HERE / "voice" / "q" / safe_filename(q["label"])
        async with sem:
            await synthesize_one(out, q["audio_text"], voice)
        return {"label": q["label"], "voice": voice, "section": q["section"],
                "topic": q["topic"], "text": q["text"]}

    results = await asyncio.gather(*[task(i + 1, q) for i, q in enumerate(questions)])
    (HERE / "voices_part23.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    print("-" * 80)
    print(f"Done. {len(results)} files + voices_part23.json written.")
    from collections import Counter
    cnt = Counter(r["voice"] for r in results)
    print("\nvoice distribution:")
    for v, n in cnt.items():
        print(f"  {v:22s}  {n:>3d} questions")


if __name__ == "__main__":
    asyncio.run(main())
