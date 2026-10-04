#!/usr/bin/env python3
"""Source of dev_board.svg: where Pypeline generated code sits on an FPGA dev board.

Used by docs/README.md (Getting Started on a Dev Board). Edit the shapes below, then
re-render from this directory:

    python3 dev_board.py    # writes dev_board.svg

Coordinates are SVG pixels on a 900x630 canvas, origin top left.
"""

import os

WIDTH, HEIGHT = 900, 630
FONT = "Helvetica, Arial, sans-serif"

# Colors
BG = "#161616"
TEXT = "#e6e6e6"
TEXT_DIM = "#bdbdbd"
BOARD = ("#1d2e1d", "#4f7f4f")  # (fill, stroke)
FPGA = ("#121212", "#8a8a8a")
WRAPPER = ("#3a2120", "#c97a6d")
IP = ("#3b2a12", "#d49a3a")
PART = ("#2a2a2a", "#9a9a9a")
TOP = ("#1b2840", "#6f9bdc")
MAIN = ("#243656", "#6f9bdc")
TOP_DIM = "#a9c2e8"

out = []


def rect(x, y, w, h, colors, rx=0, sw=2):
    fill, stroke = colors
    out.append(
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" '
        f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>'
    )


def text(x, y, s, size=15, fill=TEXT, anchor="start", bold=False):
    weight = ' font-weight="bold"' if bold else ""
    out.append(
        f'<text x="{x}" y="{y}" font-size="{size}" fill="{fill}" '
        f'text-anchor="{anchor}"{weight}>{s}</text>'
    )


def box(x, y, w, h, colors, lines, size=15, rx=6, sw=1.5, line_h=21):
    """A rounded box with lines of text centered in it."""
    rect(x, y, w, h, colors, rx=rx, sw=sw)
    first = y + h / 2 - (len(lines) - 1) * line_h / 2 + size / 3
    for i, (s, s_size, s_fill) in enumerate(lines):
        text(x + w / 2, first + i * line_h, s, s_size or size, s_fill or TEXT, "middle")


def arrow(d, start=False, dashed=False):
    """A path with an arrowhead at its end (and optionally its start)."""
    dash = ' stroke-dasharray="7,5"' if dashed else ""
    head = ' marker-start="url(#arrow-start)"' if start else ""
    out.append(f'<path d="{d}"{dash}{head} marker-end="url(#arrow-end)"/>')


# ---- Containers --------------------------------------------------------------------
out.append(f'<rect x="0" y="0" width="{WIDTH}" height="{HEIGHT}" fill="{BG}"/>')
rect(10, 10, 880, 610, BOARD)
text(28, 42, "Your dev board", 20)
rect(215, 30, 660, 575, FPGA)
text(235, 62, "Your FPGA", 19)
rect(235, 80, 620, 505, WRAPPER)
text(255, 108, "Your top level wrapper: board.vhd / top.sv", 17)
text(255, 130, "plus pin constraints: .xdc / .pcf", 14, "#d9b8b2")

# ---- Board parts -------------------------------------------------------------------
box(
    35,
    170,
    135,
    60,
    PART,
    [("Clock source", 15, None), ("(oscillator)", 13, TEXT_DIM)],
    rx=8,
    line_h=20,
)

# Push button symbol
out.append(f'<g stroke="{TEXT}" stroke-width="2" fill="none">')
out.append('<line x1="40" y1="310" x2="65" y2="310"/>')
out.append('<circle cx="70" cy="310" r="5"/>')
out.append('<circle cx="130" cy="310" r="5"/>')
out.append('<line x1="135" y1="310" x2="170" y2="310"/>')
out.append('<line x1="62" y1="296" x2="138" y2="296"/>')
out.append('<line x1="100" y1="296" x2="100" y2="282"/>')
out.append("</g>")
text(100, 337, "Button", 13, TEXT_DIM, "middle")

# LED symbol, driven from the right
out.append(f'<g stroke="{TEXT}" stroke-width="2" fill="none">')
out.append('<line x1="40" y1="400" x2="78" y2="400"/>')
out.append('<line x1="78" y1="386" x2="78" y2="414"/>')
out.append('<line x1="106" y1="400" x2="170" y2="400"/>')
out.append('<line x1="68" y1="418" x2="58" y2="430"/>')
out.append('<line x1="80" y1="420" x2="70" y2="432"/>')
out.append("</g>")
out.append(f'<polygon points="106,386 106,414 78,400" fill="{TEXT}"/>')
out.append(f'<polygon points="56,433 58,425 63,429" fill="{TEXT}"/>')
out.append(f'<polygon points="68,435 70,427 75,431" fill="{TEXT}"/>')
text(100, 452, "LED", 13, TEXT_DIM, "middle")

box(
    35,
    480,
    135,
    65,
    PART,
    [("Network/memory/", 15, None), ("ADC|DAC chips", 15, None)],
    rx=8,
    line_h=20,
)

# ---- Wrapper blocks ----------------------------------------------------------------
box(255, 205, 150, 70, IP, [("Clock gen", None, None), ("PLL IP", None, None)])
box(255, 295, 150, 120, IP, [("Tri-state", None, None), ("buffers", None, None)])
box(255, 455, 150, 100, IP, [("DDR, SERDES,", None, None), ("IP blocks", None, None)])

# ---- Pypeline generated top level --------------------------------------------------
rect(470, 150, 365, 410, TOP, rx=4)
text(488, 182, "Pypeline generated top.vhd", 18, bold=True)
text(488, 206, "@MAIN functions from your .py design", 14, TOP_DIM)
out.append(
    f'<line x1="470" y1="220" x2="835" y2="220" stroke="{TOP[1]}" stroke-width="1"/>'
)
text(488, 246, "Clock ports: clk_25p0, clk_90p0 from", 14)
text(488, 265, "@MAIN rates, or names from make_clock()", 14)
# Port labels where the wrapper's signals connect
for y, label in [
    (349, "Input[T] ports"),
    (389, "Output[T] ports"),
    (483, "Input[T] ports"),
    (523, "Output[T] ports"),
]:
    text(488, y, label, 14)
# Example @MAIN functions, at different clock rates
for y, rate, name in [
    (300, "@MAIN(25.0)", "blinky_main()"),
    (372, "@MAIN(90.0)", "my_pipeline()"),
]:
    box(
        655,
        y,
        160,
        56,
        MAIN,
        [(rate, 13, TOP_DIM), (name, 14, None)],
        rx=6,
        sw=1.2,
        line_h=20,
    )
text(735, 452, "...", 16, TOP_DIM, "middle")

# ---- Connections -------------------------------------------------------------------
out.append(f'<g stroke="{TEXT}" stroke-width="2" fill="none">')
arrow("M170,200 H215 V240 H255")  # clock source to the PLL
arrow("M215,200 V160 H445 V243 H470", dashed=True)  # ...or straight to the top level
arrow("M405,258 H470")  # PLL clocks and locked signal
arrow("M170,310 H255")  # button in
arrow("M405,344 H470")
arrow("M470,384 H405")
arrow("M255,400 H170")  # LED out
arrow("M170,512 H255", start=True)  # chips <-> DDR/SERDES/IP blocks
arrow("M405,478 H470")
arrow("M470,518 H405")
out.append("</g>")
out.append(f'<circle cx="215" cy="200" r="3.5" fill="{TEXT}"/>')
text(252, 152, "or use the board clock directly", 13, "#c8c8c8")
text(408, 278, "clocks,", 12, "#c8c8c8")
text(408, 293, "locked", 12, "#c8c8c8")

svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" font-family="{FONT}">
<!-- Generated by dev_board.py: edit that file and re-render instead of editing this one. -->
<defs>
<marker id="arrow-end" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">
<path d="M0,0 L10,5 L0,10 z" fill="{TEXT}"/>
</marker>
<marker id="arrow-start" viewBox="0 0 10 10" refX="1" refY="5" markerWidth="7" markerHeight="7" orient="auto">
<path d="M10,0 L0,5 L10,10 z" fill="{TEXT}"/>
</marker>
</defs>
{chr(10).join(out)}
</svg>
"""

out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dev_board.svg")
with open(out_path, "w") as f:
    f.write(svg)
print(f"Wrote {out_path}")
