#!/usr/bin/env python3
"""Monta el video tutorial a partir de las capturas, la locución y el guion.

    python3 montar_video.py                      # video completo -> salida/como-reservar.mp4
    python3 montar_video.py --frames 3.5,42,97   # solo fotogramas sueltos (PNG) para revisar

Todo se sincroniza con los tiempos por carácter de la locución
(audio/<escena>.json): cada «at» del guion es un trozo del texto narrado, y el
cursor, los resaltados, la escritura en los campos y los subtítulos ocurren
justo cuando la voz lo dice.

Animaciones: desplazamiento real por páginas largas (con la cabecera fija),
transición de navegación con zoom desde el botón pulsado, escritura letra a
letra con cursor de texto, botones que se hunden al pulsarlos, cursor con
trayectoria curva y rebote, zoom lento en las pausas, foco con bordes suaves,
subtítulos tipo karaoke y rótulos/tarjetas con efecto muelle.
"""
import argparse, json, math, pathlib, random, re, subprocess, sys, wave
from functools import lru_cache
from multiprocessing import Pool

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

BASE = pathlib.Path(__file__).resolve().parent.parent
W, H, FPS = 1920, 1080, 30
FULL = (0, 0, W, H)
PINK, PINK_DEEP, INK, CREAM, WHITE = (229, 23, 127), (156, 0, 79), (11, 11, 11), (235, 230, 223), (255, 255, 255)
XFADE, NAV_T, CAM_T = 0.3, 0.5, 0.9
KB = 0.035          # zoom lento máximo en las pausas
HEADER_H = 114      # alto de la cabecera fija de la web en las capturas (1,5x)
SR = 44100


def font(name, size):
    return ImageFont.truetype(str(BASE / "fuentes" / name), size)


ANTON = lambda s: font("anton-latin-400-normal.woff2", s)
FREDOKA = lambda s: font("fredoka-latin-700-normal.woff2", s)
INTER_B = lambda s: font("Inter-Bold.otf", s)
INTER_SB = lambda s: font("Inter-SemiBold.otf", s)


# --------------------------------------------------------------------------- curvas de animación
def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def smooth(x):
    x = clamp(x)
    return x * x * (3 - 2 * x)


def ease_io(x):
    x = clamp(x)
    return 0.5 - 0.5 * math.cos(math.pi * x)


def ease_out(x):  # cúbica
    x = clamp(x)
    return 1 - (1 - x) ** 3


def back_out(x, k=1.70158):  # sobrepasa un poco y vuelve
    x = clamp(x)
    return 1 + (k + 1) * (x - 1) ** 3 + k * (x - 1) ** 2


def spring(x, f=2.2, d=6.5):  # muelle amortiguado 0 -> 1
    x = max(0.0, x)
    return 1 - math.exp(-d * x) * math.cos(2 * math.pi * f * x)


def fade(t, a, b, fin=0.25, fout=0.25):
    if t < a or t > b:
        return 0.0
    return min(1.0, (t - a) / fin if fin else 1.0, (b - t) / fout if fout else 1.0)


def with_alpha(im, a):
    if a >= 1:
        return im
    im = im.copy()
    im.putalpha(im.getchannel("A").point(lambda v: int(v * a)))
    return im


def duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return float(out)


# --------------------------------------------------------------------------- línea de tiempo
def build_timeline():
    g = json.loads((BASE / "guion/guion.json").read_text())
    cajas = json.loads((BASE / "capturas/cajas.json").read_text())
    repl = g.get("subtitle_replacements", {})
    T = dict(scenes=[], shots=[], clicks=[], highs=[], caps=[], overlays=[], badges=[], cursor_vis=[], types=[])
    d_lead, d_tail = (0.0, 0.0) if "pista" in g["voice"] else (0.35, 0.55)
    t = 0.0
    for s in g["scenes"]:
        if s.get("skip"):
            continue
        al = json.loads((BASE / f"audio/{s['id']}.json").read_text())["alignment"]
        text = s["tts"]
        starts, ends = al["character_start_times_seconds"], al["character_end_times_seconds"]
        assert "".join(al["characters"]) == text, f"alineación distinta al guion en {s['id']}"
        lead, tail = s.get("lead", d_lead), s.get("tail", d_tail)
        dur = lead + duration(BASE / f"audio/{s['id']}.mp3") + tail
        t0 = t

        def A(a, t0=t0, lead=lead, dur=dur, text=text, starts=starts):
            if a in (0, None):
                return t0
            if isinstance(a, (int, float)):
                return t0 + a
            if a == "end":
                return t0 + dur
            if a.startswith("@end-"):
                return t0 + dur - float(a[5:])
            m = re.match(r"^(.*?)([+-]\d+(?:\.\d+)?)$", a)  # "frase+0.4"
            off = 0.0
            if m and m.group(1):
                a, off = m.group(1), float(m.group(2))
            i = text.lower().find(a.lower())
            assert i >= 0, (s["id"], a)
            return t0 + lead + starts[i] + off

        T["scenes"].append(dict(id=s["id"], t0=t0, t1=t0 + dur, lead=lead))
        first_shot = len(T["shots"])
        for sh in s["shots"]:
            T["shots"].append(dict(t=A(sh["at"]), img=sh["img"], cam=tuple(sh.get("cam", FULL)), blur=sh.get("blur", False),
                                   tr=sh.get("tr"), header=sh.get("header"), cam_dur=sh.get("cam_dur", CAM_T),
                                   kb=sh.get("kb", True), scene_end=t0 + dur))
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

        T["cursor_vis"].append((t0, 0.0 if s.get("cursor") == "hidden" else 1.0, s.get("cursor_start")))
        scene_clicks = []
        for c in s.get("clicks", []):
            when = A(c["at"])
            box = resolve(c, when)
            T["clicks"].append(dict(t=when, box=box, img=c.get("img") or img_at(when), click=not c.get("noclick"),
                                    input=c.get("noclick", False)))
            scene_clicks.append((when, box))
        for ty in s.get("type", []):
            when = A(ty["at"])
            T["types"].append(dict(t=when, img=ty["img"], box=tuple(resolve(dict(ty, pad=0), when)), dur=ty.get("dur", 0.75)))

        def inside(box, hb):
            cx, cy = box[0] + box[2] / 2, box[1] + box[3] / 2
            return hb[0] <= cx <= hb[0] + hb[2] and hb[1] <= cy <= hb[1] + hb[3]

        hs = sorted(s.get("highlights", []), key=lambda h: A(h["at"]))
        for k, h in enumerate(hs):
            a = A(h["at"])
            hb = resolve(h, a)
            ends_ = [a + h.get("max", 4.0), t0 + dur]
            if "to" in h:
                ends_.append(A(h["to"]))
            if k + 1 < len(hs):
                ends_.append(A(hs[k + 1]["at"]))
            ends_ += [max(a + 0.6, ct - 0.85) for ct, cb in scene_clicks if ct > a and not inside(cb, hb)]
            T["highs"].append(dict(t=a, end=min(ends_), box=hb))
        for o in s.get("overlays", []):
            ov = dict(o, t=A(o["from"]), end=A(o["to"]))
            if "screens" in o and any("at" in sc for sc in o["screens"]):
                # pantallas del celular ancladas a la voz: cada una dura hasta la siguiente
                scr = [dict(sc) for sc in o["screens"]]
                s_st = [A(sc["at"]) - ov["t"] for sc in scr] + [ov["end"] - ov["t"]]
                for k_, sc in enumerate(scr):
                    sc["dur"] = s_st[k_ + 1] - s_st[k_]
                    if "tap_text" in sc:
                        sc["tap_at"] = A(sc["tap_text"]) - ov["t"] - s_st[k_]
                    if "callout" in sc and "at_text" in sc["callout"]:
                        sc["callout"] = dict(sc["callout"], at=A(sc["callout"]["at_text"]) - ov["t"] - s_st[k_])
                ov["screens"] = scr
            T["overlays"].append(ov)
        for b in s.get("badges", []):
            T["badges"].append(dict(b, t=A(b["at"]), end=A(b.get("to", "end"))))
        for (i, j) in caption_spans(text):
            k0 = next(k for k in range(i, j) if not text[k].isspace())
            orig = text[i:j].strip()
            o0 = text.index(orig, i)
            line = orig
            for a_, b_ in repl.items():
                line = line.replace(a_, b_)
            # tiempo de cada palabra mostrada (proporcional si hubo reemplazos)
            wt = []
            for m in re.finditer(r"\S+", line):
                q = round(m.start() * len(orig) / max(1, len(line)))
                q = min(len(orig) - 1, q)
                while q < len(orig) - 1 and orig[q].isspace():
                    q += 1
                wt.append(t0 + lead + starts[o0 + q])
            T["caps"].append(dict(t=t0 + lead + starts[k0], end=t0 + lead + ends[j - 1] + 0.35, text=line, words=wt))
        t += dur
    for a, b in zip(T["caps"], T["caps"][1:]):
        if b["t"] - a["end"] < 0.25:
            a["end"] = b["t"] - 0.02
    T["total"] = t
    return T


def caption_spans(text, maxlen=66):
    spans, i = [], 0
    for m in re.finditer(r"[.!?:;](?=\s|$)", text):
        if m.group() == ":" and len(text[i:m.end()].strip()) <= 10:
            continue  # «Uno:» va con su frase
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
@lru_cache(maxsize=48)
def load_img(name, blur=False):
    im = Image.open(BASE / f"capturas/{name}.jpg").convert("RGB")
    if blur:
        im = im.crop((0, 0, W, H)).filter(ImageFilter.GaussianBlur(14))
        im = Image.blend(im, Image.new("RGB", im.size, INK), 0.55)
    return im


@lru_cache(maxsize=128)
def field_text_box(name, box):
    """Zona del texto escrito dentro de un campo: (x0, y0, x1, y1, color de fondo)."""
    im = np.asarray(load_img(name)).astype(int)
    x, y, w, h = box
    m = 12
    inner = im[y + m:y + h - m, x + m:x + w - m]
    bg = np.median(inner.reshape(-1, 3), axis=0)
    diff = np.abs(inner - bg).max(axis=2) > 60
    ys, xs = np.nonzero(diff)
    if len(xs) == 0:
        return None
    return (x + m + xs.min(), y + m + ys.min(), x + m + xs.max() + 1, y + m + ys.max() + 1, tuple(int(v) for v in bg))


@lru_cache(maxsize=1)
def cursor_sprite():
    s = 4
    pts = [(0, 0), (0, 34), (9, 26.5), (15, 40), (21.5, 37.5), (15.5, 24.5), (27, 24.5)]
    big = Image.new("RGBA", (40 * s, 48 * s), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    d.polygon([((x + 2.5) * s + 8, (y + 3) * s + 8) for x, y in pts], fill=(0, 0, 0, 110))
    big = big.filter(ImageFilter.GaussianBlur(2 * s))
    d = ImageDraw.Draw(big)
    d.polygon([(x * s + 8, y * s + 8) for x, y in pts], fill=WHITE + (255,), outline=INK + (255,), width=int(2.2 * s))
    return big.resize((int(big.width / s * 1.55), int(big.height / s * 1.55)), Image.LANCZOS)


def wrap(text, f, maxw):
    words, lines, cur = text.split(), [], []
    for w_ in words:
        if cur and f.getlength(" ".join(cur + [w_])) > maxw:
            lines.append(cur)
            cur = [w_]
        else:
            cur.append(w_)
    lines.append(cur)
    return lines


@lru_cache(maxsize=1024)
def caption_img(text, k=10 ** 6):
    """Subtítulo; las palabras ya dichas en blanco, la actual en rosa y las que faltan atenuadas."""
    f = INTER_SB(44)
    lines = wrap(text, f, 1480)
    lh = 58
    tw = int(max(f.getlength(" ".join(l)) for l in lines))
    bw, bh = tw + 64, lh * len(lines) + 30
    im = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((0, 0, bw - 1, bh - 1), radius=18, fill=(11, 11, 11, 220))
    n = 0
    sp = f.getlength(" ")
    for li, l in enumerate(lines):
        x = (bw - f.getlength(" ".join(l))) / 2
        y = 15 + lh * li + lh / 2
        for w_ in l:
            col = (255, 255, 255, 255) if n < k - 1 else (PINK + (255,) if n == k - 1 else (255, 255, 255, 150))
            d.text((x, y), w_, font=f, fill=col, anchor="lm")
            x += f.getlength(w_) + sp
            n += 1
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


@lru_cache(maxsize=64)
def text_img(text, fname, size, fill, spacing=0):
    f = font(fname, size)
    asc, desc = f.getmetrics()
    w = int(f.getlength(text) + spacing * len(text)) + 8
    im = Image.new("RGBA", (w, asc + desc + 8), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    x = 4
    for ch in text if spacing else [text]:
        d.text((x, 4), ch, font=f, fill=fill + (255,))
        x += f.getlength(ch) + spacing
    return im


# --------------------------------------------------------------------------- render
class Renderer:
    def __init__(self, T):
        self.T = T
        self.shot_t = [s["t"] for s in T["shots"]]
        self.place_captions()

    # ------------------------------------------------------------- disposición
    def place_captions(self):
        for c in self.T["caps"]:
            cw, chh = caption_img(c["text"]).size
            band = H - 56 - chh - 8  # borde superior del subtítulo abajo
            cx0, cx1 = (W - cw) / 2, (W + cw) / 2
            targets = [(k["t"], k["box"]) for k in self.T["clicks"] if c["t"] - 0.9 <= k["t"] <= c["end"] + 0.3]
            targets += [(h["t"], h["box"]) for h in self.T["highs"] if h["t"] < c["end"] and h["end"] > c["t"]]
            c["top"] = False
            for when, box in targets:
                x0, y0, x1, y1 = self.box_screen(self.cam(when), box)
                if y1 > band and y0 < H - 40 and x1 > cx0 and x0 < cx1:
                    c["top"] = True
            c["below_badge"] = any(b["t"] < c["end"] and b["end"] > c["t"] for b in self.T["badges"])

    def shot_index(self, t):
        k = 0
        for i, st in enumerate(self.shot_t):
            if st <= t + 1e-9:
                k = i
        return k

    def same(self, a, b):
        return (a["img"], a["blur"]) == (b["img"], b["blur"])

    # ------------------------------------------------------------- cámara
    def focus_of(self, k):
        """Punto hacia el que se acerca el zoom lento de un plano: su próximo clic o resaltado."""
        s = self.T["shots"][k]
        t_end = self.shot_t[k + 1] if k + 1 < len(self.shot_t) else s["scene_end"]
        for c in self.T["clicks"]:
            if s["t"] <= c["t"] <= t_end and c["img"] == s["img"]:
                x, y, w, h = c["box"]
                return x + w / 2, y + h / 2
        for h in self.T["highs"]:
            if s["t"] <= h["t"] <= t_end:
                x, y, w, h_ = h["box"]
                return x + w / 2, y + h_ / 2
        x, y, w, h = s["cam"]
        return x + w / 2, y + h / 2

    def cam(self, t, with_kb=True):
        shots = self.T["shots"]
        k = self.shot_index(t)
        s = shots[k]
        if k == 0 or not self.same(s, shots[k - 1]):
            c = s["cam"]
        else:
            prev = self.cam(s["t"] - 1e-4)
            e = ease_io((t - s["t"]) / s["cam_dur"])
            c = tuple(p + (q - p) * e for p, q in zip(prev, s["cam"]))
        if not (with_kb and s["kb"]) or s.get("header"):
            return c
        t_end = self.shot_t[k + 1] if k + 1 < len(self.shot_t) else s["scene_end"]
        span = max(0.5, t_end - s["t"])
        f = 1 + KB * smooth((t - s["t"]) / span) * min(1.0, span / 3.0)
        fx, fy = self.focus_of(k)
        x, y, w, h = c
        fx, fy = clamp(fx, x, x + w), clamp(fy, y, y + h)
        return (fx - (fx - x) / f, fy - (fy - y) / f, w / f, h / f)

    def to_screen(self, cam, x, y):
        cx, cy, cw, ch = cam
        return (x - cx) * W / cw, (y - cy) * H / ch

    def box_screen(self, cam, box):
        x, y, w, h = box
        x0, y0 = self.to_screen(cam, x, y)
        x1, y1 = self.to_screen(cam, x + w, y + h)
        return x0, y0, x1, y1

    # ------------------------------------------------------------- imagen de un plano
    def shot_image(self, s, t):
        """La captura del plano con la escritura en curso y los botones pulsados."""
        im = load_img(s["img"], s["blur"])
        types = [ty for ty in self.T["types"] if ty["img"] == s["img"]]
        presses = [c for c in self.T["clicks"] if c["click"] and c["img"] == s["img"] and -0.03 <= t - c["t"] <= 0.26]
        if not types and not presses:
            return im
        im = im.copy()
        d = ImageDraw.Draw(im)
        for ty in types:
            tb = field_text_box(s["img"], ty["box"])
            if not tb:
                continue
            x0, y0, x1, y1, bg = tb
            u = (t - ty["t"]) / ty["dur"]
            if u >= 1:
                if u * ty["dur"] < ty["dur"] + 0.7 and int((t - ty["t"]) * 3) % 2 == 0:
                    d.rectangle((x1 + 3, y0 - 2, x1 + 6, y1 + 2), fill=INK)
                continue
            n = max(4, int((x1 - x0) / 17))  # nº aproximado de letras
            rx = x0 if u <= 0 else x0 + (x1 - x0) * math.floor(clamp(u) * n) / n
            d.rectangle((rx, y0 - 3, x1 + 8, y1 + 3), fill=bg)
            if u > 0:
                d.rectangle((rx + 2, y0 - 2, rx + 5, y1 + 2), fill=INK)
        for c in presses:
            p = math.sin(math.pi * clamp((t - c["t"] + 0.03) / 0.29))
            x, y, w, h = c["box"]
            sc = 1 - 0.07 * p
            reg = im.crop((x, y, x + w, y + h))
            sw, sh_ = max(1, int(w * sc)), max(1, int(h * sc))
            reg = reg.resize((sw, sh_), Image.BICUBIC)
            edge = im.getpixel((max(0, x - 6), min(im.height - 1, y + h // 2)))
            d.rectangle((x, y, x + w, y + h), fill=edge)
            im.paste(reg, (int(x + (w - sw) / 2 + 3 * p), int(y + (h - sh_) / 2 + 3 * p)))
        return im

    def render_shot(self, s, cam, t, extra=1.0, focus=None):
        """Recorta y escala el plano según la cámara (extra > 1 acerca hacia focus)."""
        im = self.shot_image(s, t)
        x, y, w, h = cam
        if extra != 1.0:
            fx, fy = focus or (x + w / 2, y + h / 2)
            x, y, w, h = fx - (fx - x) / extra, fy - (fy - y) / extra, w / extra, h / extra
        if (round(w), round(h)) == (W, H) and abs(x - round(x)) < 1e-3 and abs(y - round(y)) < 1e-3:
            out = im.crop((round(x), round(y), round(x) + W, round(y) + H))
        else:
            out = im.resize((W, H), Image.BICUBIC, box=(x, y, x + w, y + h))
        if s.get("header"):
            out.paste(load_img(s["header"]).crop((0, 0, W, HEADER_H)), (0, 0))
        return out

    def base(self, t, cam):
        shots = self.T["shots"]
        k = self.shot_index(t)
        s = shots[k]
        if k == 0 or self.same(s, shots[k - 1]):
            return self.render_shot(s, cam, t)
        p = shots[k - 1]
        tr = s["tr"]
        recent = [c for c in self.T["clicks"] if c["click"] and s["t"] - 1.2 <= c["t"] <= s["t"] + 0.05]
        if tr is None:
            tr = "nav" if recent and not s["blur"] and not p["blur"] else "fade"
        dt = t - s["t"]
        pcam = self.cam(s["t"] - 1e-4)
        if tr == "cut":
            return self.render_shot(s, cam, t)
        if tr == "nav" and dt < NAV_T:
            u = dt / NAV_T
            if recent:
                x, y, w, h = recent[-1]["box"]
                focus = (x + w / 2, y + h / 2)
            else:
                focus = None
            old = self.render_shot(p, pcam, t, extra=1 + 0.22 * ease_out(u), focus=focus)
            new = self.render_shot(s, cam, t, extra=1.05 - 0.05 * ease_out(u))
            return Image.blend(old, new, smooth((u - 0.1) / 0.55))
        if tr == "fade" and dt < XFADE:
            return Image.blend(self.render_shot(p, pcam, t), self.render_shot(s, cam, t), smooth(dt / XFADE))
        return self.render_shot(s, cam, t)

    # ------------------------------------------------------------- cursor
    def cursor_state(self, t):
        T = self.T
        vis_keys = T["cursor_vis"]
        pos = (W * 0.5, H * 0.62)
        vis_prev, vis_cur, vis_t = 0.0, 0.0, 0.0
        for (st, v, start) in vis_keys:
            if st <= t:
                vis_prev, vis_cur, vis_t = vis_cur, v, st
        vis = vis_prev + (vis_cur - vis_prev) * smooth((t - vis_t) / 0.35)
        scene_t0 = max([st for (st, _, _) in vis_keys if st <= t] or [0])
        for (st, v, start) in vis_keys:
            if st == scene_t0 and start:
                pos = tuple(start)
        last_arrive, ring, press, sign = -9, None, 0.0, 1
        for c in T["clicks"]:
            x, y, w, h = c["box"]
            tgt = (x + min(w * 0.18, 70), y + h * 0.55) if c["input"] else (x + w * 0.5, y + h * 0.55)
            arrive = c["t"]
            if arrive < scene_t0:
                pos, last_arrive = tgt, arrive
                continue
            start_move = min(max(last_arrive + 0.25, arrive - 0.85), arrive - 0.3)
            sign = -sign
            if t < start_move:
                break
            if t < arrive:
                u = (t - start_move) / (arrive - start_move)
                e = back_out(ease_io(u) if u < 0.5 else ease_io(u), 1.1)
                mx, my = (pos[0] + tgt[0]) / 2, (pos[1] + tgt[1]) / 2
                dx, dy = tgt[0] - pos[0], tgt[1] - pos[1]
                cx, cy = mx - dy * 0.16 * sign, my + dx * 0.16 * sign  # punto de control: curva suave
                pe = clamp(e, 0, 1)
                bx = (1 - pe) ** 2 * pos[0] + 2 * (1 - pe) * pe * cx + pe ** 2 * tgt[0]
                by = (1 - pe) ** 2 * pos[1] + 2 * (1 - pe) * pe * cy + pe ** 2 * tgt[1]
                over = e - pe  # rebote al llegar
                pos = (bx + dx * over, by + dy * over)
                break
            pos, last_arrive = tgt, arrive
            if c["click"]:
                dt = t - arrive
                if 0 <= dt < 0.65:
                    ring = dt / 0.65
                if 0 <= dt < 0.24:
                    press = math.sin(math.pi * dt / 0.24)
        return pos, vis, ring, press

    def phone_dim(self, t):
        a = 0.0
        for o in self.T["overlays"]:
            if o["type"] == "phone" and o["t"] <= t <= o["end"]:
                a = max(a, clamp((t - o["t"]) / 0.35) * clamp((o["end"] - t) / 0.35))
        return a

    def draw_cursor(self, layer, cam, t):
        pos, vis, ring, press = self.cursor_state(t)
        vis *= 1 - self.phone_dim(t)
        if vis <= 0.01:
            return
        sx, sy = self.to_screen(cam, *pos)
        if ring is not None:
            d = ImageDraw.Draw(layer)
            for k, (r0, r1, wd) in enumerate([(12, 70, 6), (8, 42, 4)]):
                u = clamp(ring * (1.25 if k else 1))
                r = r0 + (r1 - r0) * ease_out(u)
                al = int(230 * (1 - u) * vis)
                if al > 0:
                    d.ellipse((sx - r, sy - r, sx + r, sy + r), outline=PINK + (al,), width=wd)
        spr = cursor_sprite()
        sc = (1 - 0.16 * press) * (0.6 + 0.4 * back_out(vis))
        if abs(sc - 1) > 0.01:
            spr = spr.resize((max(1, int(spr.width * sc)), max(1, int(spr.height * sc))), Image.BILINEAR)
        layer.alpha_composite(with_alpha(spr, vis), (int(sx - 12 * sc), int(sy - 12 * sc)))

    # ------------------------------------------------------------- resaltados
    def draw_highlight(self, layer, cam, t):
        for h in self.T["highs"]:
            a = fade(t, h["t"], h["end"], 0.3, 0.3)
            if a <= 0:
                continue
            x0, y0, x1, y1 = self.box_screen(cam, h["box"])
            bw, bh = x1 - x0, y1 - y0
            snap = 1 + 0.18 * (1 - back_out((t - h["t"]) / 0.4, 2.2))  # el marco «encaja» sobre el elemento
            pad = min(10, 0.1 * min(bw, bh)) + 2 * math.sin((t - h["t"]) * 2 * math.pi * 1.1)
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            hw, hh = (bw / 2 + pad) * snap, (bh / 2 + pad) * snap
            X0, Y0, X1, Y1 = cx - hw, cy - hh, cx + hw, cy + hh
            q = 4  # foco con bordes suaves, calculado a 1/4 de resolución
            m = Image.new("L", (W // q, H // q), int(125 * a))
            ImageDraw.Draw(m).rounded_rectangle((X0 / q, Y0 / q, X1 / q, Y1 / q), radius=5, fill=0)
            m = m.filter(ImageFilter.GaussianBlur(3)).resize((W, H), Image.BILINEAR)
            dim = Image.new("RGBA", (W, H), INK + (0,))
            dim.putalpha(m)
            layer.alpha_composite(dim)
            d = ImageDraw.Draw(layer)
            d.rounded_rectangle((X0 - 7, Y0 - 7, X1 + 7, Y1 + 7), radius=24, outline=PINK + (int(70 * a),), width=12)
            d.rounded_rectangle((X0, Y0, X1, Y1), radius=18, outline=PINK + (int(255 * a),), width=6)

    # ------------------------------------------------------------- subtítulos y rótulos
    def draw_captions(self, layer, t):
        for c in self.T["caps"]:
            a = fade(t, c["t"], c["end"], 0.15, 0.12)
            if a <= 0:
                continue
            k = sum(1 for wt in c["words"] if wt <= t + 0.04)
            im = with_alpha(caption_img(c["text"], k), a)
            dy = int(10 * (1 - ease_out((t - c["t"]) / 0.2)))
            y = (232 if c.get("below_badge") else 130) if c.get("top") else H - 56 - im.height
            layer.alpha_composite(im, (int((W - im.width) / 2), int(y + dy)))

    def draw_badges(self, layer, t):
        for b in self.T["badges"]:
            a = fade(t, b["t"], b["end"], 0.15, 0.3)
            if a <= 0:
                continue
            im = badge_img(b["text"], b.get("big", False))
            sc = 0.55 + 0.45 * spring((t - b["t"]) / 0.9)
            im = im.resize((max(1, int(im.width * sc)), max(1, int(im.height * sc))), Image.BICUBIC)
            layer.alpha_composite(with_alpha(im, a), (int((W - im.width) / 2), int(158 - im.height / 2)))

    def draw_overlays(self, layer, t):
        for o in self.T["overlays"]:
            if o["t"] <= t <= o["end"]:
                getattr(self, "ov_" + o["type"])(layer, t - o["t"], o["end"] - t, o)

    def reveal(self, layer, im, x, y, el, delay, out_t, anchor_center=False):
        """Texto que sube desde detrás de una máscara (revelado por líneas)."""
        u = ease_out((el - delay) / 0.6)
        a = clamp((el - delay) / 0.25) * clamp(out_t / 0.35)
        if u <= 0 or a <= 0:
            return
        if anchor_center:
            x -= im.width / 2
        hidden = int(im.height * (1 - u))
        vis = im.crop((0, 0, im.width, im.height - hidden))
        layer.alpha_composite(with_alpha(vis, a), (int(x), int(y + hidden)))

    def ov_title(self, layer, el, out, o):
        x = 150
        sp = 6 + 22 * (1 - ease_out(el / 0.9))
        self.reveal(layer, text_img(o["kicker"].upper(), "Inter-Bold.otf", 36, PINK, round(sp)), x, 250, el, 0.1, out)
        l1, l2 = o["title"].upper().split("\n")
        self.reveal(layer, text_img(l1, "anton-latin-400-normal.woff2", 190, WHITE), x - 10, 296, el, 0.25, out)
        self.reveal(layer, text_img(l2, "anton-latin-400-normal.woff2", 190, PINK), x - 10, 516, el, 0.42, out)
        a = clamp((el - 0.7) / 0.2) * clamp(out / 0.35)
        if a > 0:
            sc = 0.62 * spring((el - 0.7) / 1.0)
            lg = logo().resize((max(1, int(442 * sc)), max(1, int(210 * sc))), Image.LANCZOS)
            layer.alpha_composite(with_alpha(lg, a), (x, int(790 + 65 - lg.height / 2)))

    def ov_confirm(self, layer, el, out, o):
        a = clamp(el / 0.2) * clamp(out / 0.3)
        if a <= 0:
            return
        sc = 0.7 + 0.3 * spring(el / 0.9)
        cw, ch = 980, 460
        card = Image.new("RGBA", (cw + 16, ch + 16), (0, 0, 0, 0))
        d = ImageDraw.Draw(card)
        d.rounded_rectangle((16, 16, cw + 15, ch + 15), radius=36, fill=INK + (255,))
        d.rounded_rectangle((0, 0, cw - 1, ch - 1), radius=36, fill=WHITE + (255,), outline=INK + (255,), width=6)
        cx, cy = cw / 2, 140
        r = 72 * back_out((el - 0.15) / 0.4, 2.5) if el > 0.15 else 0
        if r > 1:
            d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=PINK + (255,), outline=INK + (255,), width=6)
        pts = [(cx - 34, cy + 2), (cx - 8, cy + 28), (cx + 38, cy - 26)]  # el check se dibuja
        u = clamp((el - 0.4) / 0.35)
        if u > 0:
            seg1 = min(1, u / 0.35)
            p1 = (pts[0][0] + (pts[1][0] - pts[0][0]) * seg1, pts[0][1] + (pts[1][1] - pts[0][1]) * seg1)
            d.line([pts[0], p1], fill=WHITE + (255,), width=16)
            if u > 0.35:
                seg2 = (u - 0.35) / 0.65
                p2 = (pts[1][0] + (pts[2][0] - pts[1][0]) * seg2, pts[1][1] + (pts[2][1] - pts[1][1]) * seg2)
                d.line([pts[1], p2], fill=WHITE + (255,), width=16, joint="curve")
        d.text((cx, 290), o["title"], font=FREDOKA(76), fill=INK, anchor="mm")
        d.text((cx, 375), o["sub"], font=INTER_SB(40), fill=(107, 93, 102), anchor="mm")
        card = card.resize((int(card.width * sc), int(card.height * sc)), Image.BICUBIC)
        ox, oy = int((W - card.width) / 2), int((H - card.height) / 2 - 40)
        self.confetti(layer, el, a)
        layer.alpha_composite(with_alpha(card, a), (ox, oy))

    def confetti(self, layer, el, a):
        if el > 2.2:
            return
        rnd = random.Random(7)
        d = ImageDraw.Draw(layer)
        cx, cy = W / 2, H / 2 - 60
        for i in range(70):
            ang = rnd.uniform(0, 2 * math.pi)
            sp = rnd.uniform(500, 1100)
            x = cx + math.cos(ang) * sp * el
            y = cy + math.sin(ang) * sp * el * 0.75 + 520 * el * el
            if not (0 <= x < W and 0 <= y < H):
                continue
            col = [PINK, INK, (255, 140, 196), (255, 179, 71)][i % 4]
            al = int(255 * a * clamp(1 - el / 2.2))
            s = rnd.uniform(7, 14)
            rot = ang + el * 6
            pts = [(x + math.cos(rot + q) * s, y + math.sin(rot + q) * s * 0.5) for q in (0, 1.6, math.pi, 4.7)]
            d.polygon(pts, fill=col + (al,))

    def ov_outro(self, layer, el, out, o):
        a = clamp(el / 0.2)
        if a > 0:
            sc = 1.05 * spring(el / 1.0)
            lg = logo().resize((max(1, int(442 * sc)), max(1, int(210 * sc))), Image.LANCZOS)
            layer.alpha_composite(with_alpha(lg, a), (int((W - lg.width) / 2), int(230 - lg.height / 2)))
        l1, l2 = o["title"].split("\n")
        im1 = text_img(l1.upper(), "anton-latin-400-normal.woff2", 96, WHITE)
        self.reveal(layer, im1, W / 2, 470 - im1.height / 2, el, 0.3, 9, anchor_center=True)
        im2 = text_img(l2, "fredoka-latin-700-normal.woff2", 110, PINK)
        self.reveal(layer, im2, W / 2, 590 - im2.height / 2, el, 0.45, 9, anchor_center=True)
        u = ease_out((el - 0.9) / 0.6)  # subrayado que se dibuja bajo la dirección web
        if u > 0:
            d = ImageDraw.Draw(layer)
            x0 = (W - im2.width) / 2 + 10
            d.rounded_rectangle((x0, 590 + im2.height / 2 - 4, x0 + (im2.width - 20) * u, 590 + im2.height / 2 + 6), radius=5, fill=PINK + (255,))
        im3 = text_img(o["sub"], "Inter-SemiBold.otf", 44, CREAM)
        self.reveal(layer, im3, W / 2, 735 - im3.height / 2, el, 0.7, 9, anchor_center=True)

    # ------------------------------------------------------------- paso a paso con el celular
    PH_SH = 930                       # alto de la pantalla del celular en el video
    PH_SC = 930 / 1280                # escala de las capturas del celular (590x1280)
    PH_SW = round(590 * 930 / 1280)
    PH_BEZ = 16

    @staticmethod
    @lru_cache(maxsize=8)
    def phone_screen(name):
        im = Image.open(BASE / f"capturas/{name}.jpg").convert("RGB")
        return im

    @staticmethod
    @lru_cache(maxsize=1)
    def phone_body():
        bz, sw, sh = Renderer.PH_BEZ, Renderer.PH_SW, Renderer.PH_SH
        pw, ph = sw + 2 * bz, sh + 2 * bz
        pad = 40
        im = Image.new("RGBA", (pw + 2 * pad, ph + 2 * pad), (0, 0, 0, 0))
        sh_ = Image.new("L", im.size, 0)
        ImageDraw.Draw(sh_).rounded_rectangle((pad + 10, pad + 18, pad + pw + 10, pad + ph + 18), radius=62, fill=150)
        sh_ = sh_.filter(ImageFilter.GaussianBlur(16))
        shadow = Image.new("RGBA", im.size, (0, 0, 0, 0))
        shadow.putalpha(sh_)
        im.alpha_composite(shadow)
        d = ImageDraw.Draw(im)
        d.rounded_rectangle((pad, pad, pad + pw, pad + ph), radius=60, fill=(18, 18, 22, 255), outline=(70, 70, 80, 255), width=3)
        mask = Image.new("L", (sw, sh), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, sw - 1, sh - 1), radius=46, fill=255)
        return im, mask, pad

    def phone_frame(self, o, el):
        """Pantalla del celular en el instante el (con transición, toque y etiqueta)."""
        sc_list = o["screens"]
        starts, acc = [], 0.0
        for sc in sc_list:
            starts.append(acc)
            acc += sc["dur"]
        idx = max(i for i, st in enumerate(starts) if el >= st) if el >= 0 else 0
        sw, sh, k = self.PH_SW, self.PH_SH, self.PH_SC

        def render(i, se):
            sc = sc_list[i]
            im = self.phone_screen(sc["img"]).copy()
            d = ImageDraw.Draw(im, "RGBA")
            if "tap" in sc:
                tx, ty = sc["tap"]
                dt = se - sc["tap_at"]
                if -0.8 < dt < 0.05:  # aviso: anillo que late sobre lo que se va a tocar
                    r = 62 + 6 * math.sin(se * 10)
                    al = int(220 * clamp((dt + 0.8) / 0.25))
                    d.ellipse((tx - r, ty - r, tx + r, ty + r), outline=PINK + (al,), width=9)
                if 0 <= dt < 0.55:  # el dedo toca
                    u = dt / 0.55
                    r = 34 * (1 - 0.25 * math.sin(math.pi * min(1, u * 2)))
                    d.ellipse((tx - r, ty - r, tx + r, ty + r), fill=(255, 255, 255, int(170 * (1 - u))))
                    rr = 34 + 70 * ease_out(u)
                    d.ellipse((tx - rr, ty - rr, tx + rr, ty + rr), outline=PINK + (int(255 * (1 - u)),), width=8)
            if "callout" in sc and se > sc["callout"].get("at", 0.3):
                x0, y0, x1, y1 = sc["callout"]["box"]
                u = (se - sc["callout"].get("at", 0.3)) / 0.5
                scl = 0.85 + 0.15 * spring(u)
                cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
                hw, hh = (x1 - x0) / 2 * scl, (y1 - y0) / 2 * scl
                d.rounded_rectangle((cx - hw, cy - hh, cx + hw, cy + hh), radius=16, fill=(255, 240, 247, 255), outline=PINK + (255,), width=6)
                f = INTER_B(31)
                d.text((cx, cy), sc["callout"]["text"], font=f, fill=PINK_DEEP, anchor="mm")
            return im.resize((sw, sh), Image.LANCZOS)

        se = el - starts[idx]
        cur = render(idx, se)
        if idx > 0 and se < 0.4:  # transición tipo iOS: la nueva pantalla entra desde la derecha
            u = ease_out(se / 0.4)
            prev = render(idx - 1, sc_list[idx - 1]["dur"])
            canvas = Image.new("RGB", (sw, sh), (0, 0, 0))
            canvas.paste(prev, (int(-sw * 0.3 * u), 0))
            canvas.paste(cur, (int(sw * (1 - u)), 0))
            cur = canvas
        return cur

    def ov_phone(self, layer, el, out, o):
        a = clamp(el / 0.35) * clamp(out / 0.35)
        if a <= 0:
            return
        layer.alpha_composite(Image.new("RGBA", (W, H), INK + (int(175 * a),)))
        body, mask, pad = self.phone_body()
        scr = self.phone_frame(o, el - 0.1).convert("RGBA")
        scr.putalpha(mask)
        ph = body.copy()
        ph.alpha_composite(scr, (pad + self.PH_BEZ, pad + self.PH_BEZ))
        enter = 1 - spring(el / 1.0)
        leave = 1 - ease_out(out / 0.4)
        x = o.get("x", 1180) - pad + 760 * enter + 760 * leave
        y = (H - ph.height) / 2
        layer.alpha_composite(with_alpha(ph, a), (int(x), int(y)))

    @staticmethod
    @lru_cache(maxsize=16)
    def step_card(n, title, sub, w):
        fT, fS, fK, fN = FREDOKA(54 if w > 600 else 42), INTER_SB(32 if w > 600 else 28), INTER_B(26), ANTON(64)
        lines = [" ".join(l) for l in wrap(title, fT, w - 150)]
        lh = fT.size + 8
        hgt = 40 + 34 + lh * len(lines) + (fS.size + 18 if sub else 0) + 30
        im = Image.new("RGBA", (w + 10, hgt + 10), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.rounded_rectangle((10, 10, w + 9, hgt + 9), radius=30, fill=PINK + (255,))
        d.rounded_rectangle((0, 0, w - 1, hgt - 1), radius=30, fill=(17, 12, 16, 245), outline=PINK + (255,), width=4)
        d.ellipse((30, 34, 120, 124), fill=PINK + (255,))
        d.text((75, 80), str(n), font=fN, fill=WHITE, anchor="mm")
        x = 145
        kx = x
        for ch in f"PASO {n}":
            d.text((kx, 40), ch, font=fK, fill=PINK)
            kx += fK.getlength(ch) + 5
        y = 78
        for l in lines:
            d.text((x, y), l, font=fT, fill=WHITE)
            y += lh
        if sub:
            d.text((x, y + 8), sub, font=fS, fill=CREAM)
        return im

    def ov_step(self, layer, el, out, o):
        a = clamp(el / 0.25) * clamp(out / 0.25)
        if a <= 0:
            return
        card = self.step_card(o["n"], o["title"], o.get("sub", ""), o.get("w", 760))
        dx = -50 * (1 - ease_out(el / 0.45))
        sc = 0.9 + 0.1 * spring(el / 0.8)
        if abs(sc - 1) > 0.005:
            card = card.resize((int(card.width * sc), int(card.height * sc)), Image.BICUBIC)
        y = o.get("y", 380) - card.height / 2 + 60
        layer.alpha_composite(with_alpha(card, a), (int(o.get("x", 110) + dx), int(y)))

    # ------------------------------------------------------------- fotograma
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
    R = Renderer(build_timeline())
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
