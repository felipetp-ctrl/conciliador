"""Gera o sprite SVG dos ícones Lucide (local, CSP estrita).

Lê os SVGs de ``lucide-static@0.460.0`` (cache em ``/tmp/lucide`` ou, se ausente,
baixa da unpkg) e escreve ``app/static/icons/lucide-sprite.svg`` com um
``<symbol id="nome">`` por ícone. Não edite o sprite à mão.
"""

from __future__ import annotations

import re
import urllib.request
from pathlib import Path

VERSION = "0.460.0"
BASE = f"https://unpkg.com/lucide-static@{VERSION}/icons"
CACHE = Path("/tmp/lucide")

ICONS = [
    "check",
    "arrow-left-right",
    "equal-not",
    "clock",
    "clock-alert",
    "circle-help",
    "circle-check",
    "circle-alert",
    "triangle-alert",
    "info",
    "x",
    "upload",
    "download",
    "file-down",
    "file-x",
    "file-spreadsheet",
    "loader",
    "link",
    "unlink",
    "pen-line",
    "shield-check",
    "lock",
    "eye-off",
    "scale",
    "chevron-right",
    "chevron-down",
    "arrow-left",
    "arrow-right",
]

_OUT = Path(__file__).resolve().parent.parent / "app" / "static" / "icons" / "lucide-sprite.svg"


def _fetch(name: str) -> str:
    cache = CACHE / f"{name}.svg"
    if not cache.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(urllib.request.urlopen(f"{BASE}/{name}.svg").read())
    return cache.read_text()


def main() -> None:
    symbols = []
    for name in ICONS:
        svg = _fetch(name)
        inner = re.search(r"<svg.*?>(.*)</svg>", svg, re.S).group(1).strip()
        symbols.append(f'<symbol id="{name}" viewBox="0 0 24 24">{inner}</symbol>')
    _OUT.parent.mkdir(parents=True, exist_ok=True)
    _OUT.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg">\n' + "\n".join(symbols) + "\n</svg>\n"
    )
    print(f"gerado {_OUT} com {len(ICONS)} ícones")


if __name__ == "__main__":
    main()
