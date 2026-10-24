"""
Renders examples/demo.gif: two real commands, `greenlight tail` and
`greenlight check`, typed into a terminal window.

Nothing on screen is hand-written. The text comes from the same functions
the CLI calls (print_banner + tail_file, check_session + print_findings),
captured with colors from a Rich console, run over two recorded session
logs in this directory. Before drawing, the script runs the real CLI and
asserts its plain output is identical to what it captured, so the GIF
can't quietly drift from what the tool prints.

Only the *rendering* is a stand-in for a screen recording: frames are
drawn with Pillow because vhs's headless-browser pipeline hung here (see
notes/day4.md). Pillow is not a dependency of greenlight; it's only
needed to rebuild this file.

Usage:
    .venv\\Scripts\\python.exe examples\\make_demo_gif.py [--out PATH]

Refreshing examples/bad-session.jsonl (a session recorded through the real
proxy against tests/bad_fixture_server.py) is documented in examples/README.md.
"""
import argparse
import io
import os
import re
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from rich.console import Console

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import greenlight.render as render  # noqa: E402
from greenlight.banner import print_banner  # noqa: E402
from greenlight.check import check_session, print_findings  # noqa: E402

TAIL_ARG = "examples/demo-session.jsonl"
CHECK_ARG = "examples/bad-session.jsonl"

COLS = 100
FONT_PX = 20
S = 2  # draw at 2x and scale down, for smooth text
FONT_REGULAR = r"C:\Windows\Fonts\consola.ttf"
FONT_BOLD = r"C:\Windows\Fonts\consolab.ttf"

OUTER = (24, 27, 42)
WINDOW = (13, 17, 23)
TITLEBAR = (22, 27, 34)
BORDER = (48, 54, 61)
FG = (230, 237, 243)
DIM = (125, 133, 144)
RED, YELLOW, GREEN = (255, 123, 114), (227, 179, 65), (63, 185, 80)
BLUE, MAGENTA, CYAN = (121, 192, 255), (210, 168, 255), (86, 212, 221)
PROMPT = (121, 192, 255)
CURSOR = (201, 209, 217)
ANSI_COLORS = {1: RED, 2: GREEN, 3: YELLOW, 4: BLUE, 5: MAGENTA, 6: CYAN}

Run = tuple  # (text, rgb, bold)


def _real_env() -> dict:
    env = dict(os.environ, COLUMNS=str(COLS), PYTHONIOENCODING="utf-8", NO_COLOR="1")
    env.pop("FORCE_COLOR", None)
    return env


def real_console_width() -> int:
    """The width a real `greenlight` run wraps at with COLUMNS=COLS. Rich
    wraps one column narrower on Windows, so ask it rather than assume."""
    out = subprocess.run([sys.executable, "-c", "from rich.console import Console; print(Console().width)"],
                         env=_real_env(), capture_output=True, text=True).stdout
    return int(out.strip())


def capture(fn) -> str:
    """Run fn(console) against a console that records ANSI colors."""
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=True, color_system="standard",
                      legacy_windows=False, width=real_console_width(), highlight=False)
    fn(console)
    return buf.getvalue()


def capture_tail() -> str:
    def run(console):
        print_banner(console)
        original, render.console = render.console, console
        try:
            render.tail_file(Path(TAIL_ARG))
        finally:
            render.console = original
    return capture(run)


def capture_check() -> str:
    path = Path(CHECK_ARG)
    return capture(lambda console: print_findings(check_session(path), path, console))


SGR = re.compile(r"\x1b\[([0-9;]*)m")


def strip_ansi(text: str) -> str:
    return SGR.sub("", text)


def parse_ansi(text: str) -> list[list[Run]]:
    text = text.replace(TAIL_ARG.replace("/", "\\"), TAIL_ARG).replace(CHECK_ARG.replace("/", "\\"), CHECK_ARG)
    lines: list[list[Run]] = [[]]
    state = {"fg": None, "bold": False, "dim": False}

    def add(chunk: str) -> None:
        chunk = chunk.replace("\r", "")
        for i, part in enumerate(chunk.split("\n")):
            if i:
                lines.append([])
            if part:
                color = DIM if state["dim"] else ANSI_COLORS.get(state["fg"], FG)
                lines[-1].append((part, color, state["bold"]))

    pos = 0
    for m in SGR.finditer(text):
        add(text[pos:m.start()])
        pos = m.end()
        for code in (int(c) if c else 0 for c in m.group(1).split(";")):
            if code == 0:
                state.update(fg=None, bold=False, dim=False)
            elif code == 1:
                state["bold"] = True
            elif code == 2:
                state["dim"] = True
            elif code == 22:
                state.update(bold=False, dim=False)
            elif 30 <= code <= 37:
                state["fg"] = code - 30
            elif code == 39:
                state["fg"] = None
    add(text[pos:])
    # rich pads grid rows with trailing spaces; they only add width
    for line in lines:
        while line and not line[-1][0].strip():
            line.pop()
        if line:
            t, c, b = line[-1]
            line[-1] = (t.rstrip(), c, b)
    while lines and not lines[-1]:
        lines.pop()
    return lines


def _normalize(text: str) -> str:
    return "\n".join(l.rstrip() for l in text.replace("\r\n", "\n").split("\n")).replace("\\", "/").strip()


def assert_matches_real_cli(argv: list[str], captured: str) -> None:
    real = subprocess.run([sys.executable, "-m", "greenlight.cli", *argv], cwd=ROOT, env=_real_env(),
                          capture_output=True, text=True, encoding="utf-8").stdout
    if _normalize(real) != _normalize(strip_ansi(captured)):
        sys.exit(f"the captured output differs from the real `greenlight {' '.join(argv)}`:\n"
                 f"--- real ---\n{_normalize(real)}\n--- captured ---\n{_normalize(strip_ansi(captured))}")


def group_tail(lines: list[list[Run]]) -> list[list[list[Run]]]:
    # banner (7 lines) | watching + legend + blank (3) | one group per trace line
    return [lines[:7], lines[7:10], *[[l] for l in lines[10:]]]


def group_check(lines: list[list[Run]]) -> list[list[list[Run]]]:
    # "session:" + blank | one group per finding (a long message wraps onto
    # continuation lines) | the blank line and the summary under them
    groups: list[list[list[Run]]] = [lines[:2]]
    for line in lines[2:]:
        plain = "".join(t for t, _, _ in line)
        if plain.startswith(("  error", "  warning")) or not plain.strip():
            groups.append([line])
        else:
            groups[-1].append(line)
    return groups


class Renderer:
    def __init__(self, max_lines: int):
        self.font = ImageFont.truetype(FONT_REGULAR, FONT_PX * S)
        self.bold = ImageFont.truetype(FONT_BOLD, FONT_PX * S)
        self.small = ImageFont.truetype(FONT_REGULAR, 15 * S)
        self.cw = self.font.getlength("M")
        self.line_h = int(FONT_PX * 1.5 * S)
        self.pad_x, self.pad_y, self.margin, self.titlebar = 30 * S, 24 * S, 34 * S, 44 * S
        win_w = int(COLS * self.cw) + 2 * self.pad_x
        win_h = self.titlebar + max_lines * self.line_h + 2 * self.pad_y
        self.size = ((win_w + 2 * self.margin) // S * S, (win_h + 2 * self.margin) // S * S)
        self.win = (self.margin, self.margin, self.margin + win_w, self.margin + win_h)
        self.base = self._chrome()

    def _chrome(self) -> Image.Image:
        img = Image.new("RGB", self.size, OUTER)
        d = ImageDraw.Draw(img)
        x0, y0, x1, y1 = self.win
        r = 14 * S
        d.rounded_rectangle(self.win, radius=r, fill=TITLEBAR, outline=BORDER, width=S)
        d.rounded_rectangle((x0, y0 + self.titlebar, x1, y1), radius=r, fill=WINDOW,
                            corners=(False, False, True, True))
        d.rectangle((x0 + S, y0 + self.titlebar, x1 - S, y0 + self.titlebar + r // 2), fill=WINDOW)
        d.line((x0, y0 + self.titlebar, x1, y0 + self.titlebar), fill=BORDER, width=S)
        d.rounded_rectangle(self.win, radius=r, outline=BORDER, width=S)
        cy = y0 + self.titlebar // 2
        for i, color in enumerate(((255, 95, 86), (255, 189, 46), (39, 201, 63))):
            cx = x0 + 26 * S + i * 22 * S
            d.ellipse((cx - 6 * S, cy - 6 * S, cx + 6 * S, cy + 6 * S), fill=color)
        title = "greenlight"
        d.text(((x0 + x1) / 2 - self.small.getlength(title) / 2, cy - 9 * S), title, font=self.small, fill=DIM)
        return img

    def frame(self, lines: list[list[Run]], cursor: bool = False) -> Image.Image:
        img = self.base.copy()
        d = ImageDraw.Draw(img)
        x_start = self.win[0] + self.pad_x
        y = self.win[1] + self.titlebar + self.pad_y
        x = x_start
        for line in lines:
            x = x_start
            for text, color, bold in line:
                d.text((x, y), text, font=self.bold if bold else self.font, fill=color)
                x += len(text) * self.cw
            y += self.line_h
        if cursor:
            y -= self.line_h
            d.rectangle((x, y + 3 * S, x + self.cw, y + self.line_h - 5 * S), fill=CURSOR)
        return img.resize((self.size[0] // S, self.size[1] // S), Image.LANCZOS)


def prompt_line(typed: str) -> list[Run]:
    return [("$ ", PROMPT, True), (typed, FG, False)]


def build_scene(r: Renderer, command: str, groups: list[list[list[Run]]], pause) -> list:
    frames = [(r.frame([prompt_line("")], cursor=True), 650)]
    step = 3
    for i in range(step, len(command) + step, step):
        frames.append((r.frame([prompt_line(command[:i])], cursor=True), 55))
    frames.append((r.frame([prompt_line(command)], cursor=True), 380))
    screen: list[list[Run]] = [prompt_line(command)]
    frames.append((r.frame(screen), 220))
    for group in groups:
        screen = screen + group
        frames.append((r.frame(screen), pause(group)))
    return frames


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "examples" / "demo.gif"))
    ap.add_argument("--preview-dir", default=None, help="also write a few still frames here, for review")
    args = ap.parse_args()
    out = Path(args.out).resolve()
    os.chdir(ROOT)  # the commands are shown, and run, with repo-relative paths

    tail_ansi, check_ansi = capture_tail(), capture_check()
    assert_matches_real_cli(["tail", TAIL_ARG], tail_ansi)
    assert_matches_real_cli(["check", CHECK_ARG], check_ansi)
    print("captured output is identical to the real CLI's")

    tail_groups = group_tail(parse_ansi(tail_ansi))
    check_groups = group_check(parse_ansi(check_ansi))
    max_lines = max(1 + sum(len(g) for g in tail_groups), 1 + sum(len(g) for g in check_groups)) + 1
    r = Renderer(max_lines)

    def tail_pause(group):
        plain = "".join(t for line in group for t, _, _ in line)
        if "FAILED" in plain:
            return 2200
        if "slow" in plain:
            return 700
        return 500 if len(group) > 1 else 320

    def check_pause(group):
        plain = "".join(t for line in group for t, _, _ in line)
        return 4000 if "error(s)" in plain else 900

    tail_scene = build_scene(r, "greenlight tail examples/demo-session.jsonl", tail_groups, tail_pause)
    check_scene = build_scene(r, "greenlight check examples/bad-session.jsonl", check_groups, check_pause)
    frames = tail_scene + check_scene

    # one shared palette for every frame (built from each scene's last frame,
    # which together contain every color used): no flicker, small file
    w, h = frames[0][0].size
    palette_src = Image.new("RGB", (w, h * 2))
    palette_src.paste(tail_scene[-1][0], (0, 0))
    palette_src.paste(check_scene[-1][0], (0, h))
    palette = palette_src.quantize(colors=48, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    quantized = [f.quantize(palette=palette, dither=Image.Dither.NONE) for f, _ in frames]
    quantized[0].save(out, save_all=True, append_images=quantized[1:], duration=[ms for _, ms in frames],
                      loop=0, optimize=True, disposal=1)
    print(f"{out}: {len(frames)} frames, {frames[0][0].size[0]}x{frames[0][0].size[1]}, "
          f"{out.stat().st_size / 1024:.0f} KB, {sum(ms for _, ms in frames) / 1000:.1f}s loop")

    if args.preview_dir:
        preview = Path(args.preview_dir)
        preview.mkdir(parents=True, exist_ok=True)
        tail_scene[6][0].save(preview / "typing.png")
        tail_scene[-1][0].save(preview / "tail_end.png")
        check_scene[len(check_scene) // 2][0].save(preview / "check_mid.png")
        check_scene[-1][0].save(preview / "check_end.png")

if __name__ == "__main__":
    main()
