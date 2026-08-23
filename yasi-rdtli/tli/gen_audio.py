# -*- coding: utf-8 -*-
"""用 edge-tts 批量生成雅思考点词例句音频，多口音轮换。"""
import asyncio
import json
import sys
from pathlib import Path

import edge_tts

BASE = Path('/workspace/yasi/yasi-rdtli/tli')
AUDIO_DIR = BASE / 'audio'
DATA = json.loads((BASE / 'sentences.json').read_text(encoding='utf-8'))

# 多口音轮换（男女交替，覆盖英/美/澳/加/爱尔兰/新西兰等）
VOICES = [
    'en-GB-RyanNeural',       # 英音男（考官感）
    'en-US-JennyNeural',      # 美音女
    'en-AU-WilliamNeural',    # 澳音男
    'en-GB-SoniaNeural',      # 英音女
    'en-US-GuyNeural',        # 美音男
    'en-CA-ClaraNeural',      # 加拿大女
    'en-IE-EmilyNeural',      # 爱尔兰女
    'en-NZ-MitchellNeural',   # 新西兰男
]

RATE = '-5%'
CONCURRENCY = 6
RETRY = 3

# 音频文件命名：word/NN.mp3（按句子全局序号），并记录 voice 映射
audio_map = {}   # idx -> {'file': ..., 'voice': ...}
entries_out = []


def sentence_global_index() -> int:
    return len(audio_map)


async def synth_one(text: str, voice: str, out_path: Path) -> None:
    for attempt in range(RETRY):
        try:
            c = edge_tts.Communicate(text, voice, rate=RATE)
            await c.save(str(out_path))
            return
        except Exception as e:
            if attempt == RETRY - 1:
                raise
            await asyncio.sleep(2 * (attempt + 1))


async def worker(sem: asyncio.Semaphore, idx: int, text: str, voice: str) -> None:
    async with sem:
        fname = f'{idx:04d}.mp3'
        out_path = AUDIO_DIR / fname
        if out_path.exists() and out_path.stat().st_size > 1000:
            audio_map[idx] = {'file': fname, 'voice': voice}
            return
        await synth_one(text, voice, out_path)
        audio_map[idx] = {'file': fname, 'voice': voice}
        if idx % 50 == 0 or idx == 1:
            print(f'  [{idx}/{len(audio_map) and "?"}] generated {fname}', flush=True)


async def main() -> None:
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    tasks = []
    sem = asyncio.Semaphore(CONCURRENCY)
    idx = 0
    for entry in DATA['entries']:
        e_out = {
            'type': entry['type'],
            'keyword': entry['keyword'],
            'meaning': entry['meaning'],
            'sentences': [],
        }
        for s in entry['sentences']:
            voice = VOICES[idx % len(VOICES)]
            tasks.append(asyncio.ensure_future(worker(sem, idx, s['en'], voice)))
            e_out['sentences'].append({
                'en': s['en'],
                'cn': s['cn'],
                'audio': f'audio/{idx:04d}.mp3',
                'voice': voice,
            })
            idx += 1
        entries_out.append(e_out)

    print(f'total sentences: {idx}')
    # 分批执行避免一次性创建过多任务
    for i in range(0, len(tasks), 60):
        batch = tasks[i:i + 60]
        await asyncio.gather(*batch)
        done = len(audio_map)
        print(f'progress: {done}/{idx}', flush=True)

    output = {
        'total': idx,
        'voices': VOICES,
        'entries': entries_out,
    }
    (BASE / 'sentences_audio.json').write_text(
        json.dumps(output, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'done. wrote sentences_audio.json')


if __name__ == '__main__':
    asyncio.run(main())
