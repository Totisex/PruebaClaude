#!/usr/bin/env python3
"""Descarga del historial de ElevenLabs la locución generada desde la web y la transcribe.

Busca la generación más reciente hecha con la voz del guion (por defecto Brian -
Social Media) cuyo texto contenga una frase clave, la guarda en voice.pista y
pide a la speech-to-text de ElevenLabs los tiempos por palabra (voice.palabras).
Después: python3 cortar_pista.py && python3 montar_video.py

    ELEVENLABS_API_KEY=... python3 descargar_pista.py --guion guion/guion-v3.json --clave "cada lunes"
"""
import argparse, json, os, pathlib, subprocess, sys, urllib.request

BASE = pathlib.Path(__file__).resolve().parent.parent
API = "https://api.elevenlabs.io/v1"
KEY = os.environ.get("ELEVENLABS_API_KEY", "proxy-injected")  # en el entorno cloud lo inyecta el proxy


def get(url):
    req = urllib.request.Request(url, headers={"xi-api-key": KEY})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--guion", default="guion/guion.json")
    ap.add_argument("--clave", required=True, help="frase que debe aparecer en el texto generado")
    a = ap.parse_args()
    g = json.loads((BASE / a.guion).read_text())
    v = g["voice"]
    hist = json.loads(get(f"{API}/history?page_size=100"))["history"]
    found = None
    for it in sorted(hist, key=lambda x: -x["date_unix"]):
        parts = it.get("dialogue") or [{"voice_id": it.get("voice_id"), "text": it.get("text")}]
        text = " ".join(p.get("text") or "" for p in parts)
        voices = {p.get("voice_id") for p in parts}
        if v["voice_id"] in voices and a.clave.lower() in text.lower():
            found = it
            break
    if not found:
        print(f"No hay en el historial una generación con {v['name']} que contenga «{a.clave}».")
        return 1
    print("generación:", found["history_item_id"], found.get("model_id"), found["date_unix"])
    pista = BASE / v["pista"]
    pista.write_bytes(get(f"{API}/history/{found['history_item_id']}/audio"))
    out = subprocess.run(["curl", "-sS", "-X", "POST", f"{API}/speech-to-text", "-H", f"xi-api-key: {KEY}",
                          "-F", "model_id=scribe_v1", "-F", "language_code=spa", "-F", "timestamps_granularity=word",
                          "-F", f"file=@{pista}"], capture_output=True, text=True, check=True).stdout
    (BASE / v["palabras"]).write_text(out)
    print("transcripción:", json.loads(out)["text"][:200], "…")


if __name__ == "__main__":
    sys.exit(main())
