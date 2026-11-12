#!/usr/bin/env python3
"""Divide una pista de voz ya generada en ElevenLabs en una pista por escena.

Sirve cuando la locución se generó entera (por ejemplo, desde la web de
ElevenLabs con una voz de la biblioteca) en vez de escena por escena con
generar_voz.py. Usa los tiempos por palabra de la speech-to-text de ElevenLabs
(audio/<pista>_stt.json) y escribe, para cada escena del guion:

    audio/<escena>.mp3   el tramo de la pista (cortado en los silencios)
    audio/<escena>.json  tiempos por carácter del texto de la escena

con el mismo formato que generar_voz.py, así montar_video.py no cambia.

    python3 cortar_pista.py
"""
import difflib, json, pathlib, re, subprocess, sys, unicodedata

BASE = pathlib.Path(__file__).resolve().parent.parent


def norm(w):
    w = unicodedata.normalize("NFD", w.lower())
    w = "".join(c for c in w if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9ñ]", "", w)


def main():
    g = json.loads((BASE / "guion/guion.json").read_text())
    v = g["voice"]
    pista = BASE / v["pista"]
    stt = json.loads((BASE / v["palabras"]).read_text())
    words = [w for w in stt["words"] if w.get("type") == "word"]
    total = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(pista)],
                                 capture_output=True, text=True, check=True).stdout)

    # palabras del guion con su escena y su posición en el texto
    toks = []  # (escena, inicio, fin, normalizada)
    for k, s in enumerate(g["scenes"]):
        for m in re.finditer(r"\S+", s["tts"]):
            n = norm(m.group())
            if n:
                toks.append((k, m.start(), m.end(), n))
    a = [t[3] for t in toks]
    b = [norm(w["text"]) for w in words]

    # alinear guion ↔ transcripción; los tramos distintos se reparten en el tiempo
    times = [None] * len(toks)
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            for d in range(i2 - i1):
                times[i1 + d] = (words[j1 + d]["start"], words[j1 + d]["end"])
        elif op == "replace" and i2 > i1:
            t0, t1 = words[j1]["start"], words[j2 - 1]["end"]
            step = (t1 - t0) / (i2 - i1)
            for d in range(i2 - i1):
                times[i1 + d] = (t0 + step * d, t0 + step * (d + 1))
    for i, t in enumerate(times):  # palabras sin pareja: hereda del vecino
        if t is None:
            prev = next((times[j] for j in range(i - 1, -1, -1) if times[j]), (0, 0))
            times[i] = (prev[1], prev[1] + 0.2)
    missing = sum(1 for op in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes() if op[0] != "equal")
    print(f"{len(toks)} palabras del guion, {len(words)} transcritas, {missing} tramos no idénticos")

    n = len(g["scenes"])
    first = [min(times[i][0] for i, t in enumerate(toks) if t[0] == k) for k in range(n)]
    last = [max(times[i][1] for i, t in enumerate(toks) if t[0] == k) for k in range(n)]
    cuts = [0.0] + [(last[k - 1] + first[k]) / 2 for k in range(1, n)] + [total]

    out = BASE / "audio"
    for k, s in enumerate(g["scenes"]):
        c0, c1 = cuts[k], cuts[k + 1]
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(pista), "-ss", f"{c0:.3f}", "-to", f"{c1:.3f}",
                        "-c:a", "libmp3lame", "-b:a", "192k", str(out / f"{s['id']}.mp3")], check=True)
        text = s["tts"]
        st = [None] * len(text)
        en = [None] * len(text)
        for i, (sk, p0, p1, _) in enumerate(toks):
            if sk != k:
                continue
            for c in range(p0, p1):
                st[c], en[c] = times[i][0] - c0, times[i][1] - c0
        # espacios y signos sueltos: toman el tiempo de la palabra anterior (o siguiente)
        for c in range(len(text)):
            if st[c] is None:
                j = next((x for x in range(c - 1, -1, -1) if st[x] is not None), None)
                if j is None:
                    j = next(x for x in range(c + 1, len(text)) if st[x] is not None)
                st[c], en[c] = en[j], en[j]
        al = {"characters": list(text), "character_start_times_seconds": st, "character_end_times_seconds": en}
        (out / f"{s['id']}.json").write_text(json.dumps({"text": text, "alignment": al}, ensure_ascii=False))
        print(f"{s['id']}: {c0:6.2f} → {c1:6.2f} s")


if __name__ == "__main__":
    sys.exit(main())
