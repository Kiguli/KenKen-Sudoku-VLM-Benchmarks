"""Compose printable puzzle sheets (multi-page PDFs) from the benchmark board images.

Lays out 6 puzzles per US-Letter page (2 columns x 3 rows) with a small title and
per-puzzle captions, then saves a multi-page PDF per puzzle type.
"""

import os
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT_DIR = os.path.join(HERE, "print_sheets")
os.makedirs(OUT_DIR, exist_ok=True)

# US Letter @ 150 DPI (portrait)
DPI = 150
PAGE_W = int(8.5 * DPI)   # 1275
PAGE_H = int(11 * DPI)    # 1650

MARGIN = int(0.5 * DPI)   # outer page margin
GUTTER = int(0.3 * DPI)   # space between puzzles
TITLE_H = int(0.45 * DPI) # banner at top of each page
CAPTION_H = 26            # caption strip under each puzzle

COLS, ROWS = 2, 3
PER_PAGE = COLS * ROWS

# Versions: (label, start_index, count). Continuous, non-overlapping coverage of
# the 100 boards so a solver can grab a fresh sheet after finishing one.
VERSIONS = [
    ("v1", 0, 24),
    ("v2", 24, 24),
    ("v3", 48, 24),
    ("v4", 72, 28),
]

JOBS = [
    {
        "title": "Sudoku 9x9",
        "src": os.path.join(ROOT, "benchmarks", "Sudoku", "Computer", "9x9"),
        "pattern": "board9_{}.png",
        "out": "sudoku_9x9.pdf",
    },
    {
        "title": "KenKen 9x9",
        "src": os.path.join(ROOT, "benchmarks", "KenKen", "Computer", "9x9"),
        "pattern": "board9_{}.png",
        "out": "kenken_9x9.pdf",
    },
    {
        "title": "16x16 Sudoku (Numeric 1-16)",
        "src": os.path.join(ROOT, "benchmarks", "HexaSudoku_16x16", "Computer_Numeric"),
        "pattern": "board16_{}.png",
        "out": "sudoku_16x16_numeric.pdf",
    },
    {
        "title": "16x16 Sudoku (Hex 1-9, A-G)",
        "src": os.path.join(ROOT, "benchmarks", "HexaSudoku_16x16", "Computer_Hex_Notation"),
        "pattern": "board16_{}.png",
        "out": "sudoku_16x16_hex.pdf",
    },
]


def load_font(size, bold=False):
    candidates = (
        ["arialbd.ttf", "Arial_Bold.ttf"] if bold else ["arial.ttf", "Arial.ttf"]
    )
    for name in candidates:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


TITLE_FONT = load_font(34, bold=True)
CAPTION_FONT = load_font(18)


def fit_into(img, box_w, box_h):
    """Return a copy of img scaled to fit within (box_w, box_h), preserving aspect."""
    scale = min(box_w / img.width, box_h / img.height)
    w, h = max(1, int(img.width * scale)), max(1, int(img.height * scale))
    return img.resize((w, h), Image.LANCZOS)


def build_page(title, boards):
    """boards: list of (caption, PIL image). Returns an RGB page image."""
    page = Image.new("RGB", (PAGE_W, PAGE_H), "white")
    draw = ImageDraw.Draw(page)

    # Title banner
    tb = draw.textbbox((0, 0), title, font=TITLE_FONT)
    draw.text(((PAGE_W - (tb[2] - tb[0])) // 2, MARGIN // 2), title,
              fill="black", font=TITLE_FONT)

    grid_top = MARGIN + TITLE_H
    cell_w = (PAGE_W - 2 * MARGIN - (COLS - 1) * GUTTER) // COLS
    cell_h = (PAGE_H - grid_top - MARGIN - (ROWS - 1) * GUTTER) // ROWS
    img_box_h = cell_h - CAPTION_H

    for i, (caption, img) in enumerate(boards):
        r, c = divmod(i, COLS)
        cx = MARGIN + c * (cell_w + GUTTER)
        cy = grid_top + r * (cell_h + GUTTER)

        thumb = fit_into(img, cell_w, img_box_h)
        ox = cx + (cell_w - thumb.width) // 2
        oy = cy + (img_box_h - thumb.height) // 2
        page.paste(thumb, (ox, oy))

        cb = draw.textbbox((0, 0), caption, font=CAPTION_FONT)
        draw.text((cx + (cell_w - (cb[2] - cb[0])) // 2, cy + img_box_h + 2),
                  caption, fill="black", font=CAPTION_FONT)

    return page


def build_pdf(job, version_label, start, count, out_dir):
    src, pattern = job["src"], job["pattern"]
    title = f"{job['title']} - {version_label.upper()}"
    boards = []
    for idx in range(start, start + count):
        path = os.path.join(src, pattern.format(idx))
        if not os.path.exists(path):
            raise FileNotFoundError(path)
        img = Image.open(path).convert("RGB")
        boards.append((f"#{idx + 1}", img))  # continuous numbering across versions

    pages = []
    for p in range(0, len(boards), PER_PAGE):
        pages.append(build_page(title, boards[p:p + PER_PAGE]))

    out_name = job["out"].replace(".pdf", f"_{version_label}.pdf")
    out_path = os.path.join(out_dir, out_name)
    pages[0].save(out_path, "PDF", resolution=DPI, save_all=True,
                  append_images=pages[1:])
    print(f"  {out_name:38s} {len(pages)} pages, "
          f"puzzles #{start + 1}-{start + count}")
    return out_path


if __name__ == "__main__":
    print(f"Output -> {OUT_DIR}")
    for label, start, count in VERSIONS:
        vdir = os.path.join(OUT_DIR, label)
        os.makedirs(vdir, exist_ok=True)
        print(f"[{label}]")
        for job in JOBS:
            build_pdf(job, label, start, count, vdir)
    print("Done.")
