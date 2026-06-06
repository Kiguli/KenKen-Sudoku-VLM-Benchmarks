"""Build printable Queens puzzle sheets (versioned multi-page PDFs).

Reuses the page layout from make_print_sheets.py (6 puzzles/page, US Letter)
and the same v1-v4 slicing, so the Queens sheets match the other puzzle sets.
"""

import os
import sys

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import make_print_sheets as mps  # noqa: E402  (path set above)

N = 8
IMG_DIR = os.path.join(HERE, "queens", "images", "puzzles")
OUT_DIR = mps.OUT_DIR  # puzzles/print_sheets


def build_version(label, start, count):
    boards = []
    for idx in range(start, start + count):
        path = os.path.join(IMG_DIR, f"board{N}_{idx}.png")
        if not os.path.exists(path):
            raise FileNotFoundError(path)
        boards.append((f"#{idx + 1}", Image.open(path).convert("RGB")))

    title = f"Queens {N}x{N} - {label.upper()}"
    pages = [mps.build_page(title, boards[i:i + mps.PER_PAGE])
             for i in range(0, len(boards), mps.PER_PAGE)]

    vdir = os.path.join(OUT_DIR, label)
    os.makedirs(vdir, exist_ok=True)
    out_path = os.path.join(vdir, f"queens_8x8_{label}.pdf")
    pages[0].save(out_path, "PDF", resolution=mps.DPI, save_all=True,
                  append_images=pages[1:])
    print(f"  queens_8x8_{label}.pdf  {len(pages)} pages, "
          f"puzzles #{start + 1}-{start + count}")


if __name__ == "__main__":
    print(f"Output -> {OUT_DIR}")
    for label, start, count in mps.VERSIONS:
        build_version(label, start, count)
    print("Done.")
