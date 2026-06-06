"""Generate Queens puzzles (LinkedIn-style) with z3-verified unique solutions.

Rules:
  * N x N grid split into N contiguous colour regions.
  * Exactly one queen per row, per column, and per colour region.
  * No two queens may touch -- not even diagonally (king-move adjacency).

Pipeline per puzzle:
  1. Draw a random valid solution (a column permutation where consecutive rows
     differ by >= 2, which is sufficient since rows/cols are already unique).
  2. Grow N contiguous regions seeded on the queen cells (randomised multi-source
     flood fill) so each region contains exactly one queen.
  3. Use z3 to prove the region layout admits ONLY that solution; retry otherwise.
  4. Dedupe layouts so every puzzle is distinct.

Outputs PNGs (puzzle + solution) and a JSON record per puzzle.
"""

import os
import json
import random

from z3 import Bool, Solver, Or, Not, PbEq, unsat
from PIL import Image, ImageDraw

# ---------------------------------------------------------------- config
N = 8                # board dimension == number of regions/queens
NUM_PUZZLES = 100    # deterministic: first 24 match an earlier 24-run
SEED = 20260606      # deterministic output
MAX_ATTEMPTS = 200   # per-puzzle restarts if carving gets stuck
MIN_REGION = 3       # preferred minimum cells per colour region

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.join(HERE, "queens")
IMG_PUZ = os.path.join(BASE, "images", "puzzles")
IMG_SOL = os.path.join(BASE, "images", "solutions")
DATA = os.path.join(BASE, "data")
for d in (IMG_PUZ, IMG_SOL, DATA):
    os.makedirs(d, exist_ok=True)

# Distinct, print-friendly region colours (need >= N entries).
PALETTE = [
    (255, 123, 114),  # red
    (255, 184, 107),  # orange
    (255, 230, 109),  # yellow
    (155, 224, 127),  # green
    (126, 200, 227),  # sky
    (179, 157, 219),  # purple
    (244, 143, 177),  # pink
    (188, 170, 164),  # taupe
    (128, 222, 234),  # cyan
    (197, 225, 165),  # lime
]

NEIGHBORS4 = [(-1, 0), (1, 0), (0, -1), (0, 1)]
NEIGHBORS8 = [(-1, -1), (-1, 0), (-1, 1), (0, -1),
              (0, 1), (1, -1), (1, 0), (1, 1)]


# ---------------------------------------------------------------- generation
def random_solution(n, rng):
    """Column permutation with |col[i]-col[i+1]| >= 2 (no diagonal touching)."""
    cols = list(range(n))
    for _ in range(20000):
        rng.shuffle(cols)
        if all(abs(cols[i] - cols[i + 1]) >= 2 for i in range(n - 1)):
            return cols[:]
    raise RuntimeError("could not sample a valid solution")


def grow_regions(n, seeds, rng):
    """Randomised multi-source flood fill. Returns region-id grid (n x n).

    Smaller regions are preferred when expanding, which keeps region sizes
    reasonably balanced. Always fills the whole (connected) board.
    """
    region = [[-1] * n for _ in range(n)]
    frontier = {i: set() for i in range(n)}
    size = {i: 1 for i in range(n)}

    for i, (r, c) in enumerate(seeds):
        region[r][c] = i
    for i, (r, c) in enumerate(seeds):
        for dr, dc in NEIGHBORS4:
            rr, cc = r + dr, c + dc
            if 0 <= rr < n and 0 <= cc < n and region[rr][cc] == -1:
                frontier[i].add((rr, cc))

    remaining = n * n - n
    while remaining:
        active = [i for i in range(n) if frontier[i]]
        weights = [1.0 / size[i] for i in active]
        i = rng.choices(active, weights=weights)[0]
        r, c = rng.choice(tuple(frontier[i]))
        region[r][c] = i
        size[i] += 1
        remaining -= 1
        for j in range(n):
            frontier[j].discard((r, c))
        for dr, dc in NEIGHBORS4:
            rr, cc = r + dr, c + dc
            if 0 <= rr < n and 0 <= cc < n and region[rr][cc] == -1:
                frontier[i].add((rr, cc))
    return region


def _base_solver(n, region):
    """Solver enforcing the Queens rules for a given region layout."""
    s = Solver()
    q = [[Bool(f"q_{r}_{c}") for c in range(n)] for r in range(n)]
    for r in range(n):                                    # one per row
        s.add(PbEq([(q[r][c], 1) for c in range(n)], 1))
    for c in range(n):                                    # one per column
        s.add(PbEq([(q[r][c], 1) for r in range(n)], 1))
    cells = {i: [] for i in range(n)}                    # one per region
    for r in range(n):
        for c in range(n):
            cells[region[r][c]].append(q[r][c])
    for i in range(n):
        s.add(PbEq([(x, 1) for x in cells[i]], 1))
    for r in range(n):                                   # no touching (8-dir)
        for c in range(n):
            for dr, dc in ((0, 1), (1, -1), (1, 0), (1, 1)):
                rr, cc = r + dr, c + dc
                if 0 <= rr < n and 0 <= cc < n:
                    s.add(Or(Not(q[r][c]), Not(q[rr][cc])))
    return s, q


def find_alt_solution(n, region, known):
    """Return some valid placement != `known`, or None if `known` is unique."""
    s, q = _base_solver(n, region)
    s.add(Or([Not(q[r][known[r]]) for r in range(n)]))   # forbid `known`
    if s.check() != unsat:
        m = s.model()
        return [(r, c) for r in range(n) for c in range(n)
                if m.eval(q[r][c])]
    return None


def has_unique_solution(n, region, known):
    return find_alt_solution(n, region, known) is None


def _region_connected_without(n, region, rid, drop):
    """True if region `rid` stays connected after removing cell `drop`."""
    cells = {(r, c) for r in range(n) for c in range(n)
             if region[r][c] == rid and (r, c) != drop}
    if not cells:
        return False
    start = next(iter(cells))
    seen, stack = {start}, [start]
    while stack:
        r, c = stack.pop()
        for dr, dc in NEIGHBORS4:
            nb = (r + dr, c + dc)
            if nb in cells and nb not in seen:
                seen.add(nb)
                stack.append(nb)
    return len(seen) == len(cells)


def carve_to_unique(n, region, sol, rng, max_steps=400):
    """Recolour cells to eliminate alternative solutions while preserving `sol`.

    Each step: find an alternative solution, then move one of its (non-`sol`)
    queen cells into a neighbouring region. That destroys the alternative (its
    donor region loses a queen) without touching any `sol` queen cell, and keeps
    every region contiguous. Returns the unique-solution layout, or None if it
    gets stuck (caller retries with a fresh seed).
    """
    region = [row[:] for row in region]
    sol_cells = {(r, sol[r]) for r in range(n)}
    for _ in range(max_steps):
        alt = find_alt_solution(n, region, sol)
        if alt is None:
            return region
        cands = [cell for cell in alt if cell not in sol_cells]
        rng.shuffle(cands)
        moves = []           # (r, c, receiver_regions, donor_size_after_move)
        for (r, c) in cands:
            donor = region[r][c]
            recv = {region[r + dr][c + dc]
                    for dr, dc in NEIGHBORS4
                    if 0 <= r + dr < n and 0 <= c + dc < n
                    and region[r + dr][c + dc] != donor}
            if not recv:
                continue
            if not _region_connected_without(n, region, donor, (r, c)):
                continue
            donor_after = sum(row.count(donor) for row in region) - 1
            moves.append((r, c, tuple(recv), donor_after))
        if not moves:
            return None      # no usable move this round
        # prefer moves that keep the donor region from getting tiny
        good = [m for m in moves if m[3] >= MIN_REGION]
        r, c, recv, _ = rng.choice(good if good else moves)
        region[r][c] = rng.choice(recv)
    return None              # didn't converge


def generate(n, count, rng):
    puzzles, seen = [], set()
    for idx in range(count):
        for attempt in range(MAX_ATTEMPTS):
            sol = random_solution(n, rng)
            seeds = [(r, sol[r]) for r in range(n)]
            region = grow_regions(n, seeds, rng)
            region = carve_to_unique(n, region, sol, rng)
            if region is None:
                continue
            key = tuple(tuple(row) for row in region)
            if key in seen:
                continue
            assert has_unique_solution(n, region, sol)   # sanity
            seen.add(key)
            puzzles.append({"region": region, "solution": sol,
                            "attempts": attempt + 1})
            break
        else:
            raise RuntimeError(f"puzzle {idx}: no unique layout in "
                               f"{MAX_ATTEMPTS} attempts")
    return puzzles


# ---------------------------------------------------------------- rendering
def render(region, n, solution=None, cell=84, margin=18):
    side = margin * 2 + cell * n
    img = Image.new("RGB", (side, side), "white")
    d = ImageDraw.Draw(img)

    for r in range(n):
        for c in range(n):
            x0, y0 = margin + c * cell, margin + r * cell
            d.rectangle([x0, y0, x0 + cell, y0 + cell],
                        fill=PALETTE[region[r][c]])

    for k in range(n + 1):                               # thin inner grid
        p = margin + k * cell
        d.line([(p, margin), (p, margin + n * cell)], fill=(110, 110, 110))
        d.line([(margin, p), (margin + n * cell, p)], fill=(110, 110, 110))

    tw = 5                                               # thick region borders
    for r in range(n):
        for c in range(n):
            x0, y0 = margin + c * cell, margin + r * cell
            if r == 0 or region[r][c] != region[r - 1][c]:
                d.line([(x0, y0), (x0 + cell, y0)], fill="black", width=tw)
            if r == n - 1 or region[r][c] != region[r + 1][c]:
                d.line([(x0, y0 + cell), (x0 + cell, y0 + cell)], fill="black", width=tw)
            if c == 0 or region[r][c] != region[r][c - 1]:
                d.line([(x0, y0), (x0, y0 + cell)], fill="black", width=tw)
            if c == n - 1 or region[r][c] != region[r][c + 1]:
                d.line([(x0 + cell, y0), (x0 + cell, y0 + cell)], fill="black", width=tw)

    if solution is not None:
        for r in range(n):
            draw_crown(d, margin + solution[r] * cell, margin + r * cell, cell)
    return img


def draw_crown(d, x0, y0, cell):
    """A simple, printer-safe 3-point crown centred in the cell."""
    pad = cell * 0.24
    gx0, gy0 = x0 + pad, y0 + pad
    gw, gh = cell - 2 * pad, cell - 2 * pad
    pts = [(0.0, 0.18), (0.22, 0.62), (0.5, 0.12), (0.78, 0.62),
           (1.0, 0.18), (1.0, 1.0), (0.0, 1.0)]
    poly = [(gx0 + px * gw, gy0 + py * gh) for px, py in pts]
    d.polygon(poly, fill="black")


# ---------------------------------------------------------------- main
def main():
    rng = random.Random(SEED)
    print(f"Generating {NUM_PUZZLES} unique {N}x{N} Queens puzzles "
          f"(seed={SEED})...")
    puzzles = generate(N, NUM_PUZZLES, rng)

    total_attempts = 0
    for idx, p in enumerate(puzzles):
        region, sol = p["region"], p["solution"]
        total_attempts += p["attempts"]
        name = f"board{N}_{idx}"
        render(region, N).save(os.path.join(IMG_PUZ, name + ".png"))
        render(region, N, sol).save(os.path.join(IMG_SOL, name + ".png"))
        with open(os.path.join(DATA, name + ".json"), "w") as f:
            json.dump({"n": N, "region": region, "solution": sol}, f, indent=2)

    print(f"  saved {len(puzzles)} puzzles to {BASE}")
    print(f"  avg layout attempts/puzzle: "
          f"{total_attempts / len(puzzles):.1f}")


if __name__ == "__main__":
    main()
