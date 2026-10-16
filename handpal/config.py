"""User settings, stored as JSON in %APPDATA%\\Handpal\\config.json."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

CONFIG_PATH = Path(os.environ.get("APPDATA", Path.home())) / "Handpal" / "config.json"


@dataclass
class Snippet:
    text: str
    hotkey: str = ""
    target: str = "cursor"      # "cursor" (write where the mouse is) | "box" (ask for a box)
    letter_height: float = 0.0  # 0 = use the general letter height


@dataclass
class Config:
    font: str = "EMS Readability"
    letter_height: float = 28.0
    line_spacing: float = 1.7
    letter_spacing: float = 0.0
    size_mode: str = "shrink"
    continuous: bool = False
    speed: float = 600.0
    stroke_pause_ms: float = 8.0
    hotkey_box: str = "Ctrl+Shift+E"
    hotkey_cursor: str = "Ctrl+Shift+M"
    text: str = "Hello! Handpal wrote this."
    snippets: list[Snippet] = field(default_factory=lambda: [
        Snippet("Checked ✓", "Ctrl+Shift+1"),
        Snippet("See comment →", "Ctrl+Shift+2"),
        Snippet("OK", "Ctrl+Shift+3"),
    ])

    @classmethod
    def load(cls) -> "Config":
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        known = {f.name for f in fields(cls)}
        cfg = cls(**{k: v for k, v in data.items() if k in known and k != "snippets"})
        if isinstance(data.get("snippets"), list):
            snip_fields = {f.name for f in fields(Snippet)}
            cfg.snippets = [Snippet(**{k: v for k, v in s.items() if k in snip_fields})
                            for s in data["snippets"] if isinstance(s, dict) and "text" in s]
        return cfg

    def save(self) -> None:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = CONFIG_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(CONFIG_PATH)
