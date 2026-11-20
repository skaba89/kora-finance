#!/usr/bin/env python3
"""Audit WCAG des contrastes de tokens Kora Finance (globals.css).

Convertit les couleurs OKLCH en sRGB, calcule les ratios WCAG 2.1 des paires
usage : texte/fond. Imprime un tableau light et dark avec verdict AA (4.5:1
pour texte normal, 3:1 pour texte large >= 18.66px bold ou 24px).
"""
import math
import os
import re
import sys

CSS_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "apps", "web", "src", "app", "globals.css")

def oklch_to_linear_srgb(L, C, h_deg):
    h = math.radians(h_deg)
    a, b = C * math.cos(h), C * math.sin(h)
    l_ = L + 0.3963377774 * a + 0.2158037573 * b
    m_ = L - 0.1055613458 * a - 0.0638541728 * b
    s_ = L - 0.0894841775 * a - 1.2914855480 * b
    l, m, s = l_ ** 3, m_ ** 3, s_ ** 3
    r = 4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s
    g = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s
    bl = -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s
    return [max(0.0, min(1.0, c)) for c in (r, g, bl)]

def linear_to_relative_lumiance(rgb_lin):
    r, g, b = rgb_lin
    return 0.2126 * r + 0.7152 * g + 0.0722 * b

def oklch_luminance(L, C, h):
    return linear_to_relative_lumiance(oklch_to_linear_srgb(L, C, h))

def contrast(fg_lum, bg_lum):
    lo, hi = sorted((fg_lum, bg_lum))
    return (hi + 0.05) / (lo + 0.05)

def parse_oklch(s):
    m = re.match(r"oklch\(([\d.]+)[ ]*([\d.]+)?[ ]*([\d.]+)?\)", s)
    if not m:
        raise ValueError(f"inattendu : {s!r}")
    L = float(m.group(1))
    C = float(m.group(2)) if m.group(2) else 0.0
    h = float(m.group(3)) if m.group(3) else 0.0
    return L, C, h

def parse_css(path):
    tokens = {"light": {}, "dark": {}}
    section = None
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line.startswith(":root"):
            section = "light"
        elif line.startswith(".dark"):
            section = "dark"
        elif line.startswith("@layer"):
            section = None
        elif section and line.startswith("--"):
            name, _, value = line.partition(":")
            value = value.rstrip(";").strip()
            if value.startswith("oklch(") or re.fullmatch(r"#[0-9a-fA-F]{6}", value):
                tokens[section][name.strip()] = value
            elif "oklch" in value and "/" in value:
                base = value.split("/")[0].strip()
                tokens[section][name.strip()] = base  # alpha ignoré (1% borders)
    return tokens

def linear_rgb(value):
    if value.startswith("#"):
        rgb = [int(value[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        return [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return oklch_to_linear_srgb(*parse_oklch(value))

def lum(tokens, name):
    return linear_to_relative_lumiance(linear_rgb(tokens[f"--{name}"]))

def lum_blend(tokens, fg_name, bg_name, alpha):
    """Lumiance du mélange fg sur bg (approximation sRGB de l'opacité)."""
    lf = linear_rgb(tokens[f"--{fg_name}"])
    lb = linear_rgb(tokens[f"--{bg_name}"])
    mix = [a * alpha + b * (1 - alpha) for a, b in zip(lf, lb)]
    return linear_to_relative_lumiance(mix)

# Paires réellement rendues par les primitives (badge.tsx, alert.tsx, button.tsx).
# Les composants n'utilisent jamais de texte clair sur fond destructive plein :
# ils posent du texte destructive sur fond neutre teinté 10 % (light) / 20 % (dark).
PAIRS = [
    ("foreground", "background"),
    ("muted-foreground", "background"),
    ("muted-foreground", "card"),
    ("primary-foreground", "primary"),
    ("secondary-foreground", "secondary"),
    ("accent-foreground", "accent"),
    ("destructive", "background"),          # badge/button destructive (texte sur neutre)
    ("destructive", "card"),                # alert destructive
    ("foreground", "secondary"),            # badge secondary
    ("sidebar-foreground", "sidebar"),
    ("sidebar-accent-foreground", "sidebar-accent"),
    ("success", "background"),
    ("warning", "background"),
    ("info", "background"),
]
BLENDS = [
    # badge/button destructive : fond teinté /10 en light comme en dark
    # (les primitives ont été alignées pour l'AA), hover /15.
    ("destructive", "background", 0.10, 0.10),
    ("destructive", "card", 0.10, 0.10),
]

def main():
    tokens = parse_css(CSS_PATH)
    print(f"{'paire (texte / fond)':45s} {'light':>7s} {'dark':>7s}  AA normal 4.5   AA large 3.0")
    print("-" * 92)
    problems = []
    for fg, bg in PAIRS:
        try:
            cl = contrast(lum(tokens["light"], fg), lum(tokens["light"], bg))
            cd = contrast(lum(tokens["dark"], fg), lum(tokens["dark"], bg))
        except KeyError as e:
            print(f"{fg+'/'+bg:45s}  n/a ({e})")
            return 1
        ok = "OK" if min(cl, cd) >= 4.5 else ("large OK" if min(cl, cd) >= 3.0 else "INSUFFISANT")
        flags = ""
        if cl < 4.5:
            flags += f" [light {cl:.2f}]"
        if cd < 4.5:
            flags += f" [dark {cd:.2f}]"
        print(f"{fg+' / '+bg:45s} {cl:7.2f} {cd:7.2f}  {ok}{flags}")
        if cl < 4.5 or cd < 4.5:
            problems.append((fg, bg, cl, cd))
    print()
    print("Mélanges (texte destructive sur fond neutre teinté) :")
    for fg, bg, a_light, a_dark in BLENDS:
        cl = contrast(lum_blend(tokens["light"], fg, bg, a_light), lum(tokens["light"], bg))
        cd = contrast(lum_blend(tokens["dark"], fg, bg, a_dark), lum_blend(tokens["dark"], fg, bg, a_dark))
        # fond réel du badge = mélange lui-même ; comparer texte au mélange :
        cl_t = contrast(lum(tokens["light"], fg), lum_blend(tokens["light"], fg, bg, a_light))
        cd_t = contrast(lum(tokens["dark"], fg), lum_blend(tokens["dark"], fg, bg, a_dark))
        ok = "OK" if min(cl_t, cd_t) >= 4.5 else ("large OK" if min(cl_t, cd_t) >= 3.0 else "INSUFFISANT")
        print(f"{fg+'@'+str(int(a_light*100))+'% sur '+bg:45s} {cl_t:7.2f} {cd_t:7.2f}  {ok}")
        if cl_t < 4.5 or cd_t < 4.5:
            problems.append((f"{fg} teinté sur {bg}", bg, cl_t, cd_t))
    print()
    if problems:
        print("Paires sous AA normal :")
        for fg, bg, cl, cd in problems:
            print(f"  - {fg}/{bg} : light={cl:.2f} dark={cd:.2f}")
        return 1
    else:
        print("Toutes les paires atteignent AA normal (4.5:1).")
    return 0

if __name__ == "__main__":
    sys.exit(main())
