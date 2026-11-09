"""Generate listening samples of Amazon Polly English voices and an HTML page to compare them.

Usage (from interview-agent/):  .venv\\Scripts\\python scripts\\voice_samples.py
Uses AWS_PROFILE from the environment / .env. Output: voice-samples/index.html (git-ignored).
"""

from __future__ import annotations

import html
import os
from pathlib import Path

import boto3
from dotenv import load_dotenv

SAMPLE = (
    "Hello, and thank you for joining. I'm the automated interviewer for the backend engineer role. "
    "Can you describe a project where you built a REST API, and what your own role was?"
)
OUT = Path("voice-samples")
BASELINE = ("ap-south-1", "neural", "en-IN", "Kajal")  # what the agent uses today


def main() -> None:
    load_dotenv(".env", override=False)
    OUT.mkdir(exist_ok=True)
    rows: list[tuple[str, str, str, str, str, str]] = []

    targets: list[tuple[str, str, str, str, str]] = []
    us = boto3.client("polly", region_name="us-east-1")
    for voice in us.describe_voices(Engine="generative")["Voices"]:
        if voice["LanguageCode"].startswith("en-"):
            targets.append(("us-east-1", "generative", voice["LanguageCode"], voice["Id"], voice["Gender"]))
    targets.sort(key=lambda t: (t[2] != "en-IN", t[2], t[3]))
    targets.insert(0, (*BASELINE, "Female"))

    for region, engine, lang, voice_id, gender in targets:
        name = f"{voice_id}_{engine}_{lang}.mp3"
        path = OUT / name
        if not path.exists():
            client = boto3.client("polly", region_name=region)
            audio = client.synthesize_speech(
                Text=SAMPLE, OutputFormat="mp3", VoiceId=voice_id, Engine=engine, LanguageCode=lang
            )["AudioStream"].read()
            path.write_bytes(audio)
        rows.append((voice_id, gender, lang, engine, region, name))
        print(f"ok  {voice_id:10} {gender:7} {lang:6} {engine:10} {region}")

    items = "\n".join(
        f"<tr><th scope='row'>{html.escape(v)}</th><td>{g}</td><td>{l}</td><td>{e}"
        f"{' (current)' if (v, e) == ('Kajal', 'neural') else ''}</td><td>{r}</td>"
        f"<td><audio controls preload='none' src='{html.escape(n)}' aria-label='{html.escape(v)} {e} sample'></audio></td></tr>"
        for v, g, l, e, r, n in rows
    )
    (OUT / "index.html").write_text(
        f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Polly English voices</title>
<style>body{{font:15px system-ui;margin:2rem}}table{{border-collapse:collapse}}td,th{{padding:.4rem .8rem;border-bottom:1px solid #ddd;text-align:left}}</style>
</head><body><h1>Amazon Polly English voices</h1><p>Sample text: {html.escape(SAMPLE)}</p>
<table><thead><tr><th>Voice</th><th>Gender</th><th>Accent</th><th>Engine</th><th>Region</th><th>Listen</th></tr></thead>
<tbody>{items}</tbody></table></body></html>""",
        encoding="utf-8",
    )
    print(f"\nOpen {os.path.abspath(OUT / 'index.html')}")


if __name__ == "__main__":
    main()
