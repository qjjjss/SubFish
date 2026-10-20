"""生成 Chrome 扩展图标（纯标准库，不需要 Pillow）。

设计：深蓝底圆角方块 + 三根青绿色声波竖条（跟小窗配色一致）。
输出：extension/icons/icon{16,48,128}.png
"""
import math
import struct
import zlib
from pathlib import Path

BG = (0x12, 0x16, 0x1F)
BAR = (0x4A, 0xDE, 0x80)
SS = 4  # 超采样倍数，保证边缘平滑


def sdf_round_rect(x, y, cx, cy, hw, hh, r):
    dx = abs(x - cx) - (hw - r)
    dy = abs(y - cy) - (hh - r)
    dx = max(dx, 0.0)
    dy = max(dy, 0.0)
    return math.hypot(dx, dy) - r


def coverage(d):
    return max(0.0, min(1.0, 0.5 - d))


def blend(dst, src, a):
    return tuple(d * (1 - a) + s * a for d, s in zip(dst, src))


def render(size):
    cx = cy = size / 2
    radius = size * 0.22
    half = size / 2 - 0.5

    # 三根声波条
    bw = size * 0.13
    gap = size * 0.10
    total = 3 * bw + 2 * gap
    fracs = (0.45, 1.0, 0.62)
    bars = []
    left = cx - total / 2
    for i, f in enumerate(fracs):
        bh = (size * 0.52) * f
        bcx = left + bw / 2 + i * (bw + gap)
        bars.append((bcx, cy, bw / 2, bh / 2, min(bw / 2, bh / 2)))

    rows = []
    for py in range(size):
        row = bytearray()
        for px in range(size):
            acc = [0.0, 0.0, 0.0, 0.0]
            for sy in range(SS):
                for sx in range(SS):
                    x = px + (sx + 0.5) / SS
                    y = py + (sy + 0.5) / SS
                    a_bg = coverage(sdf_round_rect(x, y, cx, cy, half, half, radius))
                    if a_bg <= 0:
                        acc[3] += 0.0
                        continue
                    col = BG
                    for bcx, bcy, bhw, bhh, br in bars:
                        a_bar = coverage(sdf_round_rect(x, y, bcx, bcy, bhw, bhh, br))
                        if a_bar > 0:
                            col = blend(col, BAR, a_bar)
                    acc[0] += col[0] * a_bg
                    acc[1] += col[1] * a_bg
                    acc[2] += col[2] * a_bg
                    acc[3] += a_bg
            n = SS * SS
            if acc[3] <= 0:
                row += bytes((0, 0, 0, 0))
            else:
                a = acc[3] / n
                # 预乘还原
                row += bytes(
                    (
                        int(round(acc[0] / acc[3])),
                        int(round(acc[1] / acc[3])),
                        int(round(acc[2] / acc[3])),
                        int(round(a * 255)),
                    )
                )
        rows.append(bytes(row))
    return rows


def write_png(path, size, rows):
    raw = b"".join(b"\x00" + r for r in rows)
    comp = zlib.compress(raw, 9)

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", comp) + chunk(b"IEND", b"")
    path.write_bytes(png)


def main():
    out = Path(__file__).resolve().parent.parent / "extension" / "icons"
    out.mkdir(parents=True, exist_ok=True)
    for size in (16, 48, 128):
        rows = render(size)
        p = out / f"icon{size}.png"
        write_png(p, size, rows)
        print(f"{p.name}: {size}x{size}, {p.stat().st_size} bytes")


if __name__ == "__main__":
    main()
