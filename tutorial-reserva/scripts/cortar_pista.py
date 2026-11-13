#!/usr/bin/env python3
"""Divide las locuciones ya generadas en ElevenLabs en una pista por escena.

Sirve cuando la locución se generó entera (por ejemplo, desde la web de
ElevenLabs con una voz de la biblioteca) en vez de escena por escena con
generar_voz.py. Usa los tiempos por palabra de la speech-to-text de ElevenLabs
y escribe, para cada escena del guion:

    audio/<escena>.mp3   el tramo de la pista (cortado en los silencios)
    audio/<escena>.json  tiempos por carácter del texto de la escena

con el mismo formato que generar_voz.py, así montar_video.py no cambia.

La pista principal es voice.pista / voice.palabras; una escena puede usar otra
pista con sus propias claves "pista" y "palabras" (por ejemplo, una locución
añadida después). Una escena con "skip": true se corta igual (para que su
frase no se cuele en las vecinas) pero no se usa en el video.

    python3 cortar_pista.py
"""
import difflib, json, pathlib, re, subprocess, sys, unicodedata

BASE = pathlib.Path(__file__).resolve().parent.parent


def norm(w):
    w = unicodedata.normalize("NFD", w.lower())
    w = "".join(c for c in w if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9ñ]", "", w)


def cortar(scenes, pista, palabras):
    stt = json.loads((BASE / palabras).read_text())
    words = [w for w in stt["words"] if w.get("type") == "word"]
    total = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                  str(BASE / pista)], capture_output=True, text=True, check=True).stdout)
    toks = []  # (escena, inicio, fin, normalizada)
    for k, s in enumerate(scenes):
        for m in re.finditer(r"\S+", s["tts"]):
            n = norm(m.group())
            if n:
                toks.append((k, m.start(), m.end(), n))
    a = [t[3] for t in toks]
    b = [norm(w["text"]) for w in words]
    times = [None] * len(toks)
    ops = difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes()
    for op, i1, i2, j1, j2 in ops:
        if op == "equal":
            for d in range(i2 - i1):
                times[i1 + d] = (words[j1 + d]["start"], words[j1 + d]["end"])
        elif op == "replace" and i2 > i1:
            t0, t1 = words[j1]["start"], words[j2 - 1]["end"]
            step = (t1 - t0) / (i2 - i1)
            for d in range(i2 - i1):
                times[i1 + d] = (t0 + step * d, t0 + step * (d + 1))
    for i, t in enumerate(times):
        if t is None:
            prev = next((times[j] for j in range(i - 1, -1, -1) if times[j]), (0, 0))
            times[i] = (prev[1], prev[1] + 0.2)
    print(f"{pista}: {len(toks)} palabras del guion, {len(words)} transcritas, "
          f"{sum(1 for op in ops if op[0] != 'equal')} tramos no idénticos")

    n = len(scenes)
    first = [min(times[i][0] for i, t in enumerate(toks) if t[0] == k) for k in range(n)]
    last = [max(times[i][1] for i, t in enumerate(toks) if t[0] == k) for k in range(n)]
    cuts = [0.0] + [(last[k - 1] + first[k]) / 2 for k in range(1, n)] + [total]
    out = BASE / "audio"
    for k, s in enumerate(scenes):
        c0, c1 = cuts[k], cuts[k + 1]
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(BASE / pista), "-ss", f"{c0:.3f}", "-to", f"{c1:.3f}",
                        "-c:a", "libmp3lame", "-b:a", "192k", str(out / f"{s['id']}.mp3")], check=True)
        text = s["tts"]
        st, en = [None] * len(text), [None] * len(text)
        for i, (sk, p0, p1, _) in enumerate(toks):
            if sk == k:
                for c in range(p0, p1):
                    st[c], en[c] = times[i][0] - c0, times[i][1] - c0
        for c in range(len(text)):
            if st[c] is None:
                j = next((x for x in range(c - 1, -1, -1) if st[x] is not None), None)
                if j is None:
                    j = next(x for x in range(c + 1, len(text)) if st[x] is not None)
                st[c], en[c] = en[j], en[j]
        al = {"characters": list(text), "character_start_times_seconds": st, "character_end_times_seconds": en}
        (out / f"{s['id']}.json").write_text(json.dumps({"text": text, "alignment": al}, ensure_ascii=False))
        print(f"  {s['id']}: {c0:6.2f} → {c1:6.2f} s" + ("  (omitida)" if s.get("skip") else ""))


def main():
    g = json.loads((BASE / "guion/guion.json").read_text())
    v = g["voice"]
    pistas = {}
    for s in g["scenes"]:
        key = (s.get("pista", v["pista"]), s.get("palabras", v["palabras"]))
        pistas.setdefault(key, []).append(s)
    for (pista, palabras), scenes in pistas.items():
        cortar(scenes, pista, palabras)


if __name__ == "__main__":
    sys.exit(main())
