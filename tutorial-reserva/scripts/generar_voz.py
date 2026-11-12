#!/usr/bin/env python3
"""Genera la locución del tutorial con ElevenLabs (una pista por escena + tiempos por carácter).

Uso:
    ELEVENLABS_API_KEY=... python3 generar_voz.py [--solo 03_el_polo,05_mapa]

Lee guion/guion.json y escribe audio/<escena>.mp3 y audio/<escena>.json (alineación).
Usa previous_text/next_text para que la entonación sea continua entre escenas.
"""
import argparse, base64, json, os, pathlib, sys, urllib.request

BASE = pathlib.Path(__file__).resolve().parent.parent
API = "https://api.elevenlabs.io/v1/text-to-speech/{voice}/with-timestamps?output_format=mp3_44100_128"


def tts(voice, model, settings, text, prev_text, next_text):
    body = {"text": text, "model_id": model, "voice_settings": settings}
    if prev_text:
        body["previous_text"] = prev_text
    if next_text:
        body["next_text"] = next_text
    req = urllib.request.Request(
        API.format(voice=voice), data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json",
                 # En el entorno cloud el proxy inyecta la clave real en esta cabecera.
                 "xi-api-key": os.environ.get("ELEVENLABS_API_KEY", "proxy-injected")})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--solo", help="ids de escena separados por coma")
    a = ap.parse_args()
    guion = json.loads((BASE / "guion/guion.json").read_text())
    v = guion["voice"]
    scenes = guion["scenes"]
    out = BASE / "audio"
    out.mkdir(exist_ok=True)
    only = set(a.solo.split(",")) if a.solo else None
    for i, s in enumerate(scenes):
        if only and s["id"] not in only:
            continue
        prev_text = scenes[i - 1]["tts"] if i else None
        next_text = scenes[i + 1]["tts"] if i + 1 < len(scenes) else None
        d = tts(v["voice_id"], v["model_id"], v["voice_settings"], s["tts"], prev_text, next_text)
        (out / f"{s['id']}.mp3").write_bytes(base64.b64decode(d["audio_base64"]))
        al = d.get("alignment") or d.get("normalized_alignment")
        (out / f"{s['id']}.json").write_text(json.dumps({"text": s["tts"], "alignment": al}, ensure_ascii=False))
        print(f"{s['id']}: {len(s['tts'])} car., fin {al['character_end_times_seconds'][-1]:.2f}s", flush=True)


if __name__ == "__main__":
    sys.exit(main())
