#!/usr/bin/env python3
"""Monta el video tutorial a partir de las capturas, la locución y el guion.

    python3 montar_video.py            # video completo -> salida/como-reservar.mp4
    python3 montar_video.py --frames 3.5,42,97   # solo fotogramas sueltos (PNG) para revisar

Todo se sincroniza con los tiempos por carácter que devuelve ElevenLabs
(audio/<escena>.json): cada «at» del guion es un trozo del texto narrado, y el
cursor, los resaltados y los subtítulos ocurren justo cuando la voz lo dice.
"""
import argparse, json, math, pathlib, re, subprocess, sys, wave
from functools import lru_cache
from multiprocessing import Pool

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

BASE = pathlib.Path(__file__).resolve().parent.parent
W, H, FPS = 1920, 1080, 30
FULL = (0, 0, W, H)
PINK, PINK_DEEP, INK, CREAM, WHITE = (229, 23, 127), (156, 0, 79), (11, 11, 11), (235, 230, 223), (255, 255, 255)
XFADE, CAM_T = 0.35, 0.9
SR = 44100


def font(name, size):
    return ImageFont.truetype(str(BASE / "fuentes" / name), size)


ANTON = lambda s: font("anton-latin-400-normal.woff2", s)
FREDOKA = lambda s: font("fredoka-latin-700-normal.woff2", s)
FREDOKA6 = lambda s: font("fredoka-latin-600-normal.woff2", s)
INTER_B = lambda s: font("Inter-Bold.otf", s)
INTER_SB = lambda s: font("Inter-SemiBold.otf", s)


def smooth(x):
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


def ease_io(x):
    x = max(0.0, min(1.0, x))
    return 0.5 - 0.5 * math.cos(math.pi * x)


def fade(t, a, b, fin=0.25, fout=0.25):
    """Opacidad 0..1 de algo visible entre a y b con fundidos."""
    if t < a or t > b:
        return 0.0
    return min(1.0, (t - a) / fin if fin else 1.0, (b - t) / fout if fout else 1.0)


def duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return float(out)


# --------------------------------------------------------------------------- línea de tiempo
def build_timeline():
    g = json.loads((BASE / "guion/guion.json").read_text())
    cajas = json.loads((BASE / "capturas/cajas.json").read_text())
    repl = g.get("subtitle_replacements", {})
    T = dict(scenes=[], shots=[], clicks=[], highs=[], caps=[], overlays=[], badges=[], cursor_vis=[])
    # con una pista única cortada por escenas, los tramos ya traen sus silencios
    d_lead, d_tail = (0.0, 0.0) if "pista" in g["voice"] else (0.35, 0.55)
    t = 0.0
    for s in g["scenes"]:
        al = json.loads((BASE / f"audio/{s['id']}.json").read_text())["alignment"]
        text = s["tts"]
        starts, ends = al["character_start_times_seconds"], al["character_end_times_seconds"]
        assert "".join(al["characters"]) == text, f"alineación distinta al guion en {s['id']}"
        lead, tail = s.get("lead", d_lead), s.get("tail", d_tail)
        adur = duration(BASE / f"audio/{s['id']}.mp3")
        dur = lead + adur + tail
        t0 = t

        def A(a, t0=t0, lead=lead, dur=dur, text=text, starts=starts):
            if a in (0, None):
                return t0
            if a == "end":
                return t0 + dur
            if isinstance(a, str) and a.startswith("@end-"):
                return t0 + dur - float(a[5:])
            i = text.lower().find(a.lower())
            assert i >= 0, (s["id"], a)
            return t0 + lead + starts[i]

        T["scenes"].append(dict(id=s["id"], t0=t0, t1=t0 + dur, lead=lead))
        first_shot = len(T["shots"])
        for sh in s["shots"]:
            T["shots"].append(dict(t=A(sh["at"]), img=sh["img"], cam=tuple(sh.get("cam", FULL)), blur=sh.get("blur", False)))
        scene_shots = T["shots"][first_shot:]

        def img_at(when):
            cur = scene_shots[0]["img"]
            for sh in scene_shots:
                if sh["t"] <= when + 1e-6:
                    cur = sh["img"]
            return cur

        def resolve(item, when):
            box = item["box"]
            if isinstance(box, str):
                img = item.get("img") or img_at(when)
                box = cajas[img][box]
                assert box, (s["id"], item)
            x, y, w, h = box
            p = item.get("pad", 0)
            return (x - p, y - p, w + 2 * p, h + 2 * p)

        # cursor
        T["cursor_vis"].append((t0, 0.0 if s.get("cursor") == "hidden" else 1.0, s.get("cursor_start")))
        scene_clicks = []
        for c in s.get("clicks", []):
            when = A(c["at"])
            box = resolve(c, when)
            T["clicks"].append(dict(t=when, box=box, click=not c.get("noclick"), input=c.get("noclick", False)))
            scene_clicks.append((when, box))

        def inside(box, hb):
            cx, cy = box[0] + box[2] / 2, box[1] + box[3] / 2
            return hb[0] <= cx <= hb[0] + hb[2] and hb[1] <= cy <= hb[1] + hb[3]

        # resaltados: duran hasta el siguiente, hasta que el cursor va a otra parte o 4 s
        hs = sorted(s.get("highlights", []), key=lambda h: A(h["at"]))
        for k, h in enumerate(hs):
            a = A(h["at"])
            hb = resolve(h, a)
            ends_ = [a + 4.0, t0 + dur]
            if k + 1 < len(hs):
                ends_.append(A(hs[k + 1]["at"]))
            ends_ += [max(a + 0.6, ct - 0.85) for ct, cb in scene_clicks if ct > a and not inside(cb, hb)]
            T["highs"].append(dict(t=a, end=min(ends_), box=hb))
        for o in s.get("overlays", []):
            T["overlays"].append(dict(o, t=A(o["from"]), end=A(o["to"])))
        for b in s.get("badges", []):
            T["badges"].append(dict(b, t=A(b["at"]), end=A(b.get("to", "end"))))
        # subtítulos
        for (i, j) in caption_spans(text):
            k0 = next(k for k in range(i, j) if not text[k].isspace())
            line = text[i:j].strip()
            for a_, b_ in repl.items():
                line = line.replace(a_, b_)
            T["caps"].append(dict(t=t0 + lead + starts[k0], end=t0 + lead + ends[j - 1] + 0.35, text=line))
        t += dur
    # un subtítulo termina cuando empieza el siguiente
    for a, b in zip(T["caps"], T["caps"][1:]):
        if b["t"] - a["end"] < 0.25:
            a["end"] = b["t"] - 0.02
    T["total"] = t
    return T


def caption_spans(text, maxlen=66):
    """Parte el texto en frases (y por comas si son largas). Devuelve rangos [i, j)."""
    spans, i = [], 0
    for m in re.finditer(r"[.!?:;](?=\s|$)", text):
        spans.append((i, m.end()))
        i = m.end()
    if i < len(text) and text[i:].strip():
        spans.append((i, len(text)))
    out = []
    for a, b in spans:
        if b - a <= maxlen:
            out.append((a, b))
            continue
        cuts = [m.end() for m in re.finditer(r",(?=\s)", text[a:b])]
        start = a
        while b - start > maxlen:
            best = None
            for c in cuts:
                pos = a + c
                if start < pos and pos - start <= maxlen and b - pos >= 12:
                    best = pos
            if not best:
                break
            out.append((start, best))
            start = best
        out.append((start, b))
    return out


# --------------------------------------------------------------------------- recursos (cache por proceso)
@lru_cache(maxsize=64)
def load_img(name, blur=False):
    im = Image.open(BASE / f"capturas/{name}.jpg").convert("RGB")
    if blur:
        im = im.filter(ImageFilter.GaussianBlur(14))
        im = Image.blend(im, Image.new("RGB", im.size, INK), 0.55)
    return im


@lru_cache(maxsize=1)
def cursor_sprite():
    s = 4  # superresolución
    pts = [(0, 0), (0, 34), (9, 26.5), (15, 40), (21.5, 37.5), (15.5, 24.5), (27, 24.5)]
    big = Image.new("RGBA", (40 * s, 48 * s), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    sh = [((x + 2.5) * s + 8, (y + 3) * s + 8) for x, y in pts]
    d.polygon(sh, fill=(0, 0, 0, 110))
    big = big.filter(ImageFilter.GaussianBlur(2 * s))
    d = ImageDraw.Draw(big)
    pp = [(x * s + 8, y * s + 8) for x, y in pts]
    d.polygon(pp, fill=WHITE + (255,), outline=INK + (255,), width=int(2.2 * s))
    return big.resize((int(big.width / s * 1.55), int(big.height / s * 1.55)), Image.LANCZOS)


@lru_cache(maxsize=256)
def caption_img(text):
    f = INTER_SB(44)
    words, lines, cur = text.split(), [], ""
    for w_ in words:
        test = (cur + " " + w_).strip()
        if f.getlength(test) > 1480 and cur:
            lines.append(cur)
            cur = w_
        else:
            cur = test
    lines.append(cur)
    lh = 58
    tw = int(max(f.getlength(l) for l in lines))
    bw, bh = tw + 64, lh * len(lines) + 30
    im = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((0, 0, bw - 1, bh - 1), radius=18, fill=(11, 11, 11, 215))
    for k, l in enumerate(lines):
        d.text((bw / 2, 15 + lh * k + lh / 2), l, font=f, fill=WHITE, anchor="mm")
    return im


@lru_cache(maxsize=16)
def badge_img(text, big):
    f = INTER_B(54 if big else 40)
    tw = f.getlength(text)
    bw, bh = int(tw + (90 if big else 70)), (96 if big else 76)
    im = Image.new("RGBA", (bw + 12, bh + 12), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((12, 12, bw + 11, bh + 11), radius=bh // 2, fill=INK + (255,))
    d.rounded_rectangle((0, 0, bw - 1, bh - 1), radius=bh // 2, fill=PINK + (255,), outline=INK + (255,), width=4)
    d.text((bw / 2, bh / 2 + 1), text, font=f, fill=WHITE, anchor="mm")
    return im


@lru_cache(maxsize=1)
def logo():
    return Image.open(BASE / "capturas/logo-oscuro.png").convert("RGBA")


# --------------------------------------------------------------------------- render
class Renderer:
    def __init__(self, T):
        self.T = T
        self.shot_t = [s["t"] for s in T["shots"]]

    def shot_index(self, t):
        k = 0
        for i, st in enumerate(self.shot_t):
            if st <= t + 1e-9:
                k = i
        return k

    def cam(self, t):
        shots = self.T["shots"]
        k = self.shot_index(t)
        cur = shots[k]["cam"]
        if k == 0:
            return cur
        if (shots[k]["img"], shots[k]["blur"]) != (shots[k - 1]["img"], shots[k - 1]["blur"]):
            return cur  # otra captura: entra con su encuadre (el fundido se encarga del cambio)
        prev = self.cam(shots[k]["t"] - 1e-4)
        e = ease_io((t - shots[k]["t"]) / CAM_T)
        return tuple(p + (c - p) * e for p, c in zip(prev, cur))

    def to_screen(self, cam, x, y):
        cx, cy, cw, ch = cam
        return (x - cx) * W / cw, (y - cy) * H / ch

    def box_screen(self, cam, box):
        x, y, w, h = box
        x0, y0 = self.to_screen(cam, x, y)
        x1, y1 = self.to_screen(cam, x + w, y + h)
        return x0, y0, x1, y1

    def base(self, t, cam):
        shots = self.T["shots"]
        k = self.shot_index(t)
        s = shots[k]

        def render(sh, c):
            im = load_img(sh["img"], sh["blur"])
            if sh["blur"] or tuple(round(v, 3) for v in c) == FULL:
                return im
            x, y, w, h = c
            return im.resize((W, H), Image.BICUBIC, box=(x, y, x + w, y + h))

        cur = render(s, cam)
        if k > 0 and t - s["t"] < XFADE:
            p = shots[k - 1]
            if (p["img"], p["blur"]) != (s["img"], s["blur"]):
                prev = render(p, self.cam(s["t"] - 1e-4))
                return Image.blend(prev, cur, smooth((t - s["t"]) / XFADE))
        return cur

    # ------------------------------------------------------------- cursor
    def cursor_state(self, t):
        """Posición (en coordenadas de captura), visibilidad y efecto de clic."""
        T = self.T
        vis_keys = T["cursor_vis"]
        pos = (W * 0.5, H * 0.62)
        vis_prev, vis_cur, vis_t = 0.0, 0.0, 0.0
        for (st, v, start) in vis_keys:
            if st <= t:
                vis_prev, vis_cur, vis_t = vis_cur, v, st
                if start:
                    pos = tuple(start)
        vis = vis_prev + (vis_cur - vis_prev) * smooth((t - vis_t) / 0.35)
        # recorrer clics anteriores para saber de dónde viene
        last_arrive = -9
        ring = None
        press = 0.0
        scene_t0 = max([st for (st, _, _) in vis_keys if st <= t] or [0])
        for (st, v, start) in vis_keys:
            if st == scene_t0 and start:
                pos = tuple(start)
        for c in T["clicks"]:
            x, y, w, h = c["box"]
            tgt = (x + min(w * 0.18, 70), y + h * 0.55) if c["input"] else (x + w * 0.5, y + h * 0.55)
            arrive = c["t"]
            if c["t"] < scene_t0:
                pos = tgt
                last_arrive = arrive
                continue
            start_move = max(last_arrive + 0.25, arrive - 0.85)
            start_move = min(start_move, arrive - 0.3)
            if t < start_move:
                break
            if t < arrive:
                e = ease_io((t - start_move) / (arrive - start_move))
                pos = (pos[0] + (tgt[0] - pos[0]) * e, pos[1] + (tgt[1] - pos[1]) * e)
                break
            pos = tgt
            last_arrive = arrive
            if c["click"]:
                dt = t - arrive
                if 0 <= dt < 0.6:
                    ring = dt / 0.6
                if 0 <= dt < 0.22:
                    press = math.sin(math.pi * dt / 0.22)
        return pos, vis, ring, press

    # ------------------------------------------------------------- overlays
    def draw_highlight(self, layer, cam, t):
        for h in self.T["highs"]:
            a = fade(t, h["t"], h["end"], 0.3, 0.3)
            if a <= 0:
                continue
            x0, y0, x1, y1 = self.box_screen(cam, h["box"])
            bw, bh = x1 - x0, y1 - y0
            pad = min(10, 0.1 * min(bw, bh)) + 2.5 * math.sin((t - h["t"]) * 2 * math.pi * 1.1)
            x0, y0, x1, y1 = x0 - pad, y0 - pad, x1 + pad, y1 + pad
            dim = Image.new("RGBA", (W, H), (11, 11, 11, int(120 * a)))
            dd = ImageDraw.Draw(dim)
            dd.rounded_rectangle((x0, y0, x1, y1), radius=18, fill=(0, 0, 0, 0))
            layer.alpha_composite(dim)
            d = ImageDraw.Draw(layer)
            d.rounded_rectangle((x0 - 6, y0 - 6, x1 + 6, y1 + 6), radius=24, outline=PINK + (int(80 * a),), width=10)
            d.rounded_rectangle((x0, y0, x1, y1), radius=18, outline=PINK + (int(255 * a),), width=6)

    def draw_cursor(self, layer, cam, t):
        pos, vis, ring, press = self.cursor_state(t)
        if vis <= 0.01:
            return
        sx, sy = self.to_screen(cam, *pos)
        if ring is not None:
            r = 14 + 58 * smooth(ring)
            al = int(230 * (1 - ring) * vis)
            d = ImageDraw.Draw(layer)
            d.ellipse((sx - r, sy - r, sx + r, sy + r), fill=PINK + (int(al * 0.25),), outline=PINK + (al,), width=6)
        spr = cursor_sprite()
        if press > 0:
            sc = 1 - 0.14 * press
            spr = spr.resize((int(spr.width * sc), int(spr.height * sc)), Image.BILINEAR)
        if vis < 1:
            spr = spr.copy()
            spr.putalpha(spr.getchannel("A").point(lambda v: int(v * vis)))
        layer.alpha_composite(spr, (int(sx - 12), int(sy - 12)))

    def draw_captions(self, layer, t):
        for c in self.T["caps"]:
            a = fade(t, c["t"], c["end"], 0.12, 0.12)
            if a <= 0:
                continue
            im = caption_img(c["text"])
            if a < 1:
                im = im.copy()
                im.putalpha(im.getchannel("A").point(lambda v: int(v * a)))
            layer.alpha_composite(im, (int((W - im.width) / 2), int(H - 56 - im.height)))

    def draw_badges(self, layer, t):
        for b in self.T["badges"]:
            a = fade(t, b["t"], b["end"], 0.3, 0.3)
            if a <= 0:
                continue
            im = badge_img(b["text"], b.get("big", False))
            dy = int(30 * (1 - smooth((t - b["t"]) / 0.35)))
            if a < 1:
                im = im.copy()
                im.putalpha(im.getchannel("A").point(lambda v: int(v * a)))
            y = 120 + dy
            layer.alpha_composite(im, (int((W - im.width) / 2), y))

    def draw_overlays(self, layer, t):
        for o in self.T["overlays"]:
            if not (o["t"] <= t <= o["end"]):
                continue
            getattr(self, "ov_" + o["type"])(layer, t - o["t"], o["end"] - t, o)

    def _stagger(self, el_t, k, out_t):
        a = smooth((el_t - 0.15 - 0.14 * k) / 0.45) * smooth(out_t / 0.4)
        dy = int(46 * (1 - smooth((el_t - 0.15 - 0.14 * k) / 0.5)))
        return a, dy

    def _text(self, layer, xy, text, f, fill, a, anchor="la", spacing=0):
        if a <= 0:
            return
        tmp = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(tmp)
        if spacing:
            x, y = xy
            for ch in text:
                d.text((x, y), ch, font=f, fill=fill + (255,), anchor=anchor)
                x += f.getlength(ch) + spacing
        else:
            d.text(xy, text, font=f, fill=fill + (255,), anchor=anchor)
        if a < 1:
            tmp.putalpha(tmp.getchannel("A").point(lambda v: int(v * a)))
        layer.alpha_composite(tmp)

    def ov_title(self, layer, el, out, o):
        x = 150
        a, dy = self._stagger(el, 0, out)
        self._text(layer, (x, 250 + dy), o["kicker"].upper(), INTER_B(36), PINK, a, spacing=6)
        l1, l2 = o["title"].upper().split("\n")
        a, dy = self._stagger(el, 1, out)
        self._text(layer, (x - 6, 300 + dy), l1, ANTON(190), WHITE, a)
        a, dy = self._stagger(el, 2, out)
        self._text(layer, (x - 6, 520 + dy), l2, ANTON(190), PINK, a)
        a, dy = self._stagger(el, 3, out)
        if a > 0:
            lg = logo()
            lg = lg.resize((int(lg.width * 0.62), int(lg.height * 0.62)), Image.LANCZOS)
            if a < 1:
                lg.putalpha(lg.getchannel("A").point(lambda v: int(v * a)))
            layer.alpha_composite(lg, (x, 790 + dy))

    def ov_confirm(self, layer, el, out, o):
        a = smooth(el / 0.35) * smooth(out / 0.3)
        if a <= 0:
            return
        sc = 0.9 + 0.1 * smooth(el / 0.35)
        cw, ch = 980, 460
        card = Image.new("RGBA", (cw + 16, ch + 16), (0, 0, 0, 0))
        d = ImageDraw.Draw(card)
        d.rounded_rectangle((16, 16, cw + 15, ch + 15), radius=36, fill=INK + (255,))
        d.rounded_rectangle((0, 0, cw - 1, ch - 1), radius=36, fill=WHITE + (255,), outline=INK + (255,), width=6)
        cx, cy = cw / 2, 140
        d.ellipse((cx - 72, cy - 72, cx + 72, cy + 72), fill=PINK + (255,), outline=INK + (255,), width=6)
        d.line([(cx - 34, cy + 2), (cx - 8, cy + 28), (cx + 38, cy - 26)], fill=WHITE + (255,), width=16, joint="curve")
        d.text((cx, 290), o["title"], font=FREDOKA(76), fill=INK, anchor="mm")
        d.text((cx, 375), o["sub"], font=INTER_SB(40), fill=(107, 93, 102), anchor="mm")
        card = card.resize((int(card.width * sc), int(card.height * sc)), Image.BICUBIC)
        if a < 1:
            card.putalpha(card.getchannel("A").point(lambda v: int(v * a)))
        layer.alpha_composite(card, (int((W - card.width) / 2), int((H - card.height) / 2 - 40)))

    def ov_outro(self, layer, el, out, o):
        a, dy = self._stagger(el, 0, 9)
        if a > 0:
            lg = logo()
            lg = lg.resize((int(lg.width * 1.05), int(lg.height * 1.05)), Image.LANCZOS)
            if a < 1:
                lg.putalpha(lg.getchannel("A").point(lambda v: int(v * a)))
            layer.alpha_composite(lg, (int((W - lg.width) / 2), 120 + dy))
        l1, l2 = o["title"].split("\n")
        a, dy = self._stagger(el, 1, 9)
        self._text(layer, (W / 2, 470 + dy), l1.upper(), ANTON(96), WHITE, a, anchor="mm")
        a, dy = self._stagger(el, 2, 9)
        self._text(layer, (W / 2, 590 + dy), l2, FREDOKA(110), PINK, a, anchor="mm")
        a, dy = self._stagger(el, 3, 9)
        self._text(layer, (W / 2, 720 + dy), o["sub"], INTER_SB(44), CREAM, a, anchor="mm")

    # ------------------------------------------------------------- frame
    def frame(self, t):
        cam = self.cam(t)
        im = self.base(t, cam).convert("RGBA")
        self.draw_highlight(im, cam, t)
        self.draw_overlays(im, t)
        self.draw_badges(im, t)
        self.draw_cursor(im, cam, t)
        self.draw_captions(im, t)
        return im.convert("RGB")


# --------------------------------------------------------------------------- salida
def render_segment(args):
    i0, i1, path = args
    T = build_timeline()
    R = Renderer(T)
    ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                           "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                           "-pix_fmt", "yuv420p", "-r", str(FPS), str(path)], stdin=subprocess.PIPE)
    for i in range(i0, i1):
        ff.stdin.write(R.frame(i / FPS).tobytes())
    ff.stdin.close()
    assert ff.wait() == 0
    return path


def build_audio(T, path):
    total = int(math.ceil(T["total"] * SR)) + SR
    buf = np.zeros(total, dtype=np.float32)
    for sc in T["scenes"]:
        pcm = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(BASE / f"audio/{sc['id']}.mp3"), "-f", "s16le",
                              "-ac", "1", "-ar", str(SR), "-"], capture_output=True, check=True).stdout
        a = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768
        off = int(round((sc["t0"] + sc["lead"]) * SR))
        buf[off:off + len(a)] += a[: total - off]
    buf = buf[: int(round(T["total"] * SR))]
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(buf, -1, 1) * 32767).astype(np.int16).tobytes())


def write_vtt(T, path):
    def ts(x):
        h, r = divmod(x, 3600)
        m, s = divmod(r, 60)
        return f"{int(h):02d}:{int(m):02d}:{s:06.3f}"
    lines = ["WEBVTT", ""]
    for k, c in enumerate(T["caps"], 1):
        lines += [str(k), f"{ts(c['t'])} --> {ts(c['end'])}", c["text"], ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", help="segundos separados por coma: exporta solo esos fotogramas")
    ap.add_argument("--procs", type=int, default=4)
    a = ap.parse_args()
    out = BASE / "salida"
    out.mkdir(exist_ok=True)
    T = build_timeline()
    print(f"duración total: {T['total']:.2f} s, {len(T['caps'])} subtítulos")
    if a.frames:
        R = Renderer(T)
        for s in a.frames.split(","):
            R.frame(float(s)).save(out / f"frame_{float(s):07.2f}.png")
        return
    n = int(round(T["total"] * FPS))
    tmp = out / "tmp"
    tmp.mkdir(exist_ok=True)
    k = a.procs
    bounds = [round(n * j / k) for j in range(k + 1)]
    jobs = [(bounds[j], bounds[j + 1], tmp / f"seg{j}.mp4") for j in range(k)]
    with Pool(k) as p:
        segs = p.map(render_segment, jobs)
    (tmp / "lista.txt").write_text("".join(f"file '{s.name}'\n" for s in segs))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(tmp / "lista.txt"),
                    "-c", "copy", str(tmp / "video.mp4")], check=True)
    build_audio(T, tmp / "voz.wav")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(tmp / "video.mp4"), "-i", str(tmp / "voz.wav"),
                    "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
                    "-movflags", "+faststart", "-shortest", str(out / "como-reservar.mp4")], check=True)
    write_vtt(T, out / "como-reservar.vtt")
    Renderer(T).frame(2.6).save(out / "como-reservar-poster.jpg", quality=90)
    print("listo:", out / "como-reservar.mp4")


if __name__ == "__main__":
    sys.exit(main())
