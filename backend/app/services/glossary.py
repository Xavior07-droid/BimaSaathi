"""Glossary loader (A15/A16). Source: app/data/glossary.json.

`glossary_block()` renders the term table that is injected into summary_v1's {{GLOSSARY}}.
Only term names are injected (not definitions): the model needs the wording, the app shows
the definition when the reader taps the word.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

GLOSSARY_PATH = Path(__file__).resolve().parents[1] / "data" / "glossary.json"
LANGS = ("en", "hi", "mr")


@lru_cache
def load_glossary() -> list[dict[str, Any]]:
    return json.loads(GLOSSARY_PATH.read_text(encoding="utf-8"))["terms"]


def glossary_block() -> str:
    """One line per term: `English | Hindi | Marathi`."""
    return "\n".join(
        " | ".join(t["term"][lang] for lang in LANGS) for t in load_glossary()
    )
