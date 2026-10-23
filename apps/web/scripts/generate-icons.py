"""Génère les icônes PWA (PNG) sans dépendance : fond sarcelle, lettre « K » blanche.

Usage : python3 scripts/generate-icons.py  (depuis apps/web)
"""

import struct
import zlib
from pathlib import Path

TEAL = (15, 118, 110)
WHITE = (255, 255, 255)

# « K » en polygones, coordonnées relatives (0..1) dans la zone de dessin.
K_SHAPES = [
    [(0.22, 0.18), (0.36, 0.18), (0.36, 0.82), (0.22, 0.82)],
    [(0.36, 0.46), (0.62, 0.18), (0.80, 0.18), (0.36, 0.64)],
    [(0.44, 0.52), (0.56, 0.42), (0.80, 0.82), (0.62, 0.82)],
]


def inside(x: float, y: float, polygon: list[tuple[float, float]]) -> bool:
    result = False
    for (x1, y1), (x2, y2) in zip(polygon, polygon[1:] + polygon[:1], strict=True):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            result = not result
    return result


def render(size: int, padding: float) -> bytes:
    rows = []
    span = 1 - 2 * padding
    for py in range(size):
        row = bytearray([0])
        for px in range(size):
            # Suréchantillonnage 4x4 pour des bords lissés.
            hits = 0
            for sy in range(4):
                for sx in range(4):
                    x = ((px + (sx + 0.5) / 4) / size - padding) / span
                    y = ((py + (sy + 0.5) / 4) / size - padding) / span
                    hits += any(inside(x, y, shape) for shape in K_SHAPES)
            a = hits / 16
            row += bytes(round(TEAL[i] * (1 - a) + WHITE[i] * a) for i in range(3))
        rows.append(bytes(row))
    raw = zlib.compress(b"".join(rows), 9)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", raw) + chunk(b"IEND", b"")


out = Path("public/icons")
out.mkdir(parents=True, exist_ok=True)
(out / "icon-192.png").write_bytes(render(192, 0.08))
(out / "icon-512.png").write_bytes(render(512, 0.08))
# Icône « maskable » : le motif reste dans la zone sûre (80 % central).
(out / "icon-maskable-512.png").write_bytes(render(512, 0.2))
(out / "apple-touch-icon.png").write_bytes(render(180, 0.1))
print("Icônes générées dans", out)
