"""
Turns the contribution grid drawn by Platane/snk into coffee cups.

snk draws each day of the contribution calendar as
    <rect class="c c3" x="34" y="18" rx="2" ry="2"/>
sized by the `.c{width:..;height:..}` CSS rule, colored by its classes and
animated by CSS keyframes that switch the fill to the empty color once the
snake has passed. Every such cell is replaced with a <use> of one shared cup
shape at the same position and with the same attributes, so the classes, the
fill color and the "eaten" animation keep working: full cups take the
contribution color and fade to the empty color as the snake drinks them, and
days without contributions are faint cups from the start.

The snake body (class "s") and the progress bar (class "u") are left as they are.

The conversion is deterministic and runs at most once per file: a file that
already contains the cup shape is not changed again. If the SVG does not have
the expected structure, the file is left untouched and a warning is printed,
so a format change in snk never breaks the workflow.

Usage: python scripts/coffee_snake.py [file.svg ...]
Standard library only.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FILES = [ROOT / "icons" / "snake-dark.svg", ROOT / "icons" / "snake-light.svg"]

CUP_ID = "coffee-cup"

# Cell size declared in snk's stylesheet, e.g. .c{...;width:12px;height:12px}.
CELL_RULE = re.compile(r"\.c\{[^}]*?width:([0-9.]+)px;height:([0-9.]+)px")

# A contribution cell: a self-closing <rect> whose class list starts with "c".
CELL = re.compile(r'<rect(?P<attrs>\s+class="c(?:\s[^"]*)?"[^>]*?)\s*/>')

# Corner radii only make sense on a rect; everything else is kept on the cup.
RECT_ONLY = re.compile(r'\s+(?:rx|ry|width|height)="[^"]*"')

# Cup drawn in a 12 x 12 box: a saucer, a rounded cup and a ring-shaped handle.
# Every part is a filled shape, so it takes the cell's fill color.
CUP_12 = [
    ("M", 0.5, 11), ("H", 10.5), ("V", 12), ("H", 0.5), ("Z",),
    ("M", 1, 3), ("H", 9), ("V", 7), ("A", 3, 3, 0, 0, 1, 6, 10), ("H", 4),
    ("A", 3, 3, 0, 0, 1, 1, 7), ("Z",),
    ("M", 9, 4), ("H", 9.6), ("A", 2, 2, 0, 0, 1, 9.6, 8), ("H", 9), ("V", 6.8), ("H", 9.6),
    ("A", 0.8, 0.8, 0, 0, 0, 9.6, 5.2), ("H", 9), ("Z",),
]


def num(value: float) -> str:
    """Shortest stable text for a coordinate."""
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text if text not in ("", "-0") else "0"


def cup_path(width: float, height: float) -> str:
    """The cup scaled to the cell size. Arc flags are copied, not scaled."""
    sx, sy = width / 12, height / 12
    parts = []
    for cmd, *args in CUP_12:
        if cmd == "A":
            rx, ry, rot, large, sweep, x, y = args
            values = [rx * sx, ry * sy, rot, large, sweep, x * sx, y * sy]
        elif cmd == "H":
            values = [args[0] * sx]
        elif cmd == "V":
            values = [args[0] * sy]
        elif cmd == "M":
            values = [args[0] * sx, args[1] * sy]
        else:
            values = []
        parts.append(cmd + " ".join(num(v) for v in values))
    return "".join(parts)


def convert(svg: str) -> tuple[str | None, str]:
    """Returns (new SVG or None when nothing should be written, status message)."""
    if f'id="{CUP_ID}"' in svg:
        return None, "already converted"
    size = CELL_RULE.search(svg)
    if not size:
        return None, "warning: no cell size rule found, snk output format not recognized"
    cells = CELL.findall(svg)
    if not cells:
        return None, "warning: no contribution cells found, snk output format not recognized"
    if any(not (re.search(r'\sx="', a) and re.search(r'\sy="', a)) for a in cells):
        return None, "warning: a cell has no x/y position, snk output format not recognized"

    defs = f'<defs><path id="{CUP_ID}" d="{cup_path(float(size.group(1)), float(size.group(2)))}"/></defs>'
    first = CELL.search(svg).start()
    svg = svg[:first] + defs + svg[first:]
    svg = CELL.sub(lambda m: f'<use href="#{CUP_ID}"{RECT_ONLY.sub("", m.group("attrs"))}/>', svg)
    return svg, f"{len(cells)} cells turned into cups"


def main(paths: list[Path]) -> None:
    for path in paths:
        if not path.is_file():
            print(f"{path.name}: warning: file not found, skipped", file=sys.stderr)
            continue
        new, status = convert(path.read_text(encoding="utf-8"))
        if new is not None:
            path.write_text(new, encoding="utf-8")
        print(f"{path.name}: {status}", file=sys.stderr)


if __name__ == "__main__":
    main([Path(p) for p in sys.argv[1:]] or DEFAULT_FILES)
