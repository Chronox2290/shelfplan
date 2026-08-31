"""Generate the app icons as PNGs, with no image library dependency.

Draws a simple shelf mark on the app's accent green. Pure zlib + struct, so it
works anywhere Python does and adds nothing to the container image.
"""

from pathlib import Path
import struct
import sys
import zlib

BG = (47, 107, 79)      # --accent
INK = (246, 247, 243)   # --ground

OUT = Path(__file__).resolve().parent.parent / "webapp" / "static" / "icons"


def _chunk(tag: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


def write_png(path: Path, size: int, rounded: bool = True) -> None:
    """Solid background with three shelf bars, optionally corner-rounded."""
    r = size * 0.22          # corner radius
    bar_h = max(2, size // 12)
    inset = size * 0.22
    rows = []
    # Three shelves, evenly spaced down the middle band.
    bars = [size * 0.32, size * 0.50, size * 0.68]

    for y in range(size):
        row = bytearray([0])  # filter byte 0 (None) per scanline
        for x in range(size):
            inside = True
            if rounded:
                # Round the corners by testing distance from each arc centre.
                for cx, cy in ((r, r), (size - r, r), (r, size - r),
                               (size - r, size - r)):
                    if ((x < r and cx == r) or (x > size - r and cx == size - r)) and \
                       ((y < r and cy == r) or (y > size - r and cy == size - r)):
                        if (x - cx) ** 2 + (y - cy) ** 2 > r * r:
                            inside = False
                        break
            if not inside:
                # Transparent outside the rounded corner.
                row += bytes((0, 0, 0, 0))
                continue

            on_bar = any(by <= y < by + bar_h for by in bars)
            in_span = inset <= x <= size - inset
            colour = INK if (on_bar and in_span) else BG
            row += bytes(colour + (255,))
        rows.append(bytes(row))

    raw = b"".join(rows)
    png = b"\x89PNG\r\n\x1a\n"
    png += _chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
    png += _chunk(b"IDAT", zlib.compress(raw, 9))
    png += _chunk(b"IEND", b"")
    path.write_bytes(png)
    print(f"  wrote {path.name} ({size}x{size}, {len(png):,} bytes)")


def write_ico(path: Path, sources: list) -> None:
    """Bundle PNGs into a .ico for the Windows shortcut.

    Vista and later accept PNG payloads inside an ICO container, so the images
    go in whole rather than being re-encoded as bitmaps.
    """
    entries = []
    offset = 6 + 16 * len(sources)
    blobs = []
    for src in sources:
        data = src.read_bytes()
        w, h = struct.unpack(">II", data[16:24])
        entries.append((0 if w >= 256 else w, 0 if h >= 256 else h,
                        len(data), offset))
        blobs.append(data)
        offset += len(data)

    out = struct.pack("<HHH", 0, 1, len(sources))
    for (w, h, size, off) in entries:
        out += struct.pack("<BBBBHHII", w, h, 0, 0, 1, 32, size, off)
    out += b"".join(blobs)
    path.write_bytes(out)
    print(f"  wrote {path.name} ({len(sources)} sizes, {len(out):,} bytes)")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    write_png(OUT / "icon-192.png", 192)
    write_png(OUT / "icon-512.png", 512)
    # iOS home-screen icons must be opaque -- it does not honour transparency
    # and will composite the corners against black.
    write_png(OUT / "apple-touch-icon.png", 180, rounded=False)
    # Windows shortcut icon: a few sizes so it stays sharp in the taskbar.
    small = OUT / "icon-48.png"
    write_png(small, 48)
    write_ico(OUT / "shelfplan.ico", [small, OUT / "icon-192.png", OUT / "icon-512.png"])


if __name__ == "__main__":
    main()
