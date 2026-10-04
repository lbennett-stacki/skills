#!/usr/bin/env python3
"""Turn a text file into an MP3 with OpenAI or ElevenLabs TTS, playing it as chunks arrive."""

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

OUT_DIR = Path.home() / "Music" / "read-aloud"
PERSONAL_ENV = Path.home() / ".config" / "read-aloud" / "env"
EXTRA_ENVS = [Path(f).expanduser() for f in os.environ.get("READ_ALOUD_ENV_FILES", "").split(":") if f]

OPENAI_MODEL = os.environ.get("READ_ALOUD_OPENAI_MODEL", "gpt-4o-mini-tts")
OPENAI_VOICE = os.environ.get("READ_ALOUD_OPENAI_VOICE", "coral")
OPENAI_STYLE = (
    "Read like a thoughtful colleague reading something aloud to a teammate. "
    "Natural pace, clear emphasis on headings and key numbers, no theatrics."
)
ELEVEN_MODEL = os.environ.get("READ_ALOUD_ELEVEN_MODEL", "eleven_multilingual_v2")
ELEVEN_VOICE = os.environ.get("READ_ALOUD_ELEVEN_VOICE", "JBFqnCBsd6RMkjVDRZzb")


def read_env_file(path: Path, keys: set[str]) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        k, _, v = line.removeprefix("export ").partition("=")
        if k.strip() in keys and not os.environ.get(k.strip()):
            os.environ[k.strip()] = v.strip().strip("'\"")


def load_keys() -> None:
    # Shell env wins; a project's .env only reaches the shell when direnv loads it, so read listed files directly.
    for path in [PERSONAL_ENV, *EXTRA_ENVS]:
        read_env_file(path, {"OPENAI_API_KEY", "ELEVENLABS_API_KEY"})


def post(url: str, headers: dict, body: dict) -> bytes:
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        sys.exit(f"{url} -> HTTP {e.code}: {e.read().decode(errors='replace')[:500]}")


def openai_tts(text: str, prev: str, nxt: str, speed: float) -> bytes:
    return post(
        "https://api.openai.com/v1/audio/speech",
        {"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
        {
            "model": OPENAI_MODEL,
            "voice": OPENAI_VOICE,
            "input": text,
            "instructions": OPENAI_STYLE,
            "response_format": "mp3",
            "speed": speed,
        },
    )


def eleven_tts(text: str, prev: str, nxt: str, speed: float) -> bytes:
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        sys.exit(f"Set ELEVENLABS_API_KEY in the environment or {PERSONAL_ENV}.")
    return post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVEN_VOICE}?output_format=mp3_44100_128",
        {"xi-api-key": key},
        {
            "text": text,
            "model_id": ELEVEN_MODEL,
            "previous_text": prev[-1000:],
            "next_text": nxt[:1000],
            "voice_settings": {"speed": speed},
        },
    )


PROVIDERS = {
    "openai": (openai_tts, 3000),
    "eleven": (eleven_tts, 4500),
}


def chunk(text: str, limit: int) -> list[str]:
    """Split on paragraph, then sentence, boundaries so no request exceeds the provider limit."""
    pieces: list[str] = []
    for para in re.split(r"\n\s*\n", text.strip()):
        if len(para) <= limit:
            pieces.append(para)
            continue
        pieces.extend(re.split(r"(?<=[.!?])\s+", para))
    chunks, cur = [], ""
    for piece in pieces:
        if cur and len(cur) + len(piece) + 2 > limit:
            chunks.append(cur)
            cur = ""
        cur = f"{cur}\n\n{piece}" if cur else piece
    return chunks + [cur] if cur else chunks


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("text_file", type=Path)
    ap.add_argument("--name", help="output file stem; defaults to the text file's stem")
    ap.add_argument("--provider", choices=PROVIDERS, default=os.environ.get("READ_ALOUD_PROVIDER", "openai"))
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--no-play", action="store_true")
    args = ap.parse_args()

    load_keys()
    synth, limit = PROVIDERS[args.provider]
    chunks = chunk(args.text_file.read_text(), limit)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{args.name or args.text_file.stem}.mp3"
    parts_dir = OUT_DIR / ".parts"
    parts_dir.mkdir(exist_ok=True)
    print(f"{args.provider}: {len(chunks)} chunk(s), {sum(map(len, chunks))} chars -> {out}", flush=True)

    partial = out.with_suffix(".partial")
    with ThreadPoolExecutor(max_workers=4) as pool, partial.open("wb") as f:
        futures = [
            pool.submit(synth, c, chunks[i - 1] if i else "", chunks[i + 1] if i + 1 < len(chunks) else "", args.speed)
            for i, c in enumerate(chunks)
        ]
        for i, fut in enumerate(futures):
            audio = fut.result()
            f.write(audio)
            f.flush()
            print(f"chunk {i + 1}/{len(chunks)} ready", flush=True)
            if not args.no_play:
                part = parts_dir / f"{out.stem}.{i}.mp3"
                part.write_bytes(audio)
                subprocess.run(["afplay", str(part)], check=False)
                part.unlink()
    partial.rename(out)
    print(f"saved {out}")


if __name__ == "__main__":
    main()
