"""Versioned prompt loader (A8). Prompts live in app/prompts/*.md as:

    ---
    name: extract
    version: 1
    temperature: 0
    ---
    ## SYSTEM
    ...
    ## USER
    ... {{PLACEHOLDER}} ...

Model IDs are NOT in prompt files (they come from env only).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parent
_PLACEHOLDER = re.compile(r"\{\{([A-Z_]+)\}\}")


@dataclass(frozen=True)
class Prompt:
    name: str
    version: int
    meta: dict[str, str]
    system: str
    user_template: str

    @property
    def label(self) -> str:
        return f"{self.name}_v{self.version}"

    def render_user(self, **values: str | int) -> str:
        """Replace {{NAME}} placeholders. Plain replace (not str.format) because documents contain braces."""
        wanted = set(_PLACEHOLDER.findall(self.user_template))
        given = {k.upper() for k in values}
        if wanted != given:
            raise ValueError(f"{self.label}: placeholders {sorted(wanted)} != provided {sorted(given)}")
        out = self.user_template
        for k, v in values.items():
            out = out.replace("{{" + k.upper() + "}}", str(v))
        return out


@lru_cache
def load_prompt(name: str) -> Prompt:
    path = PROMPT_DIR / f"{name}.md"
    text = path.read_text(encoding="utf-8")
    m = re.match(r"\A---\n(.*?)\n---\n(.*)\Z", text, re.DOTALL)
    if not m:
        raise ValueError(f"{path.name}: missing '---' front matter (name/version)")
    meta = dict(line.split(":", 1) for line in m.group(1).splitlines() if ":" in line)
    meta = {k.strip(): v.strip() for k, v in meta.items()}
    if "version" not in meta or not meta["version"].isdigit():
        raise ValueError(f"{path.name}: front matter needs an integer 'version'")
    body = m.group(2)
    parts = re.split(r"^## (SYSTEM|USER)\s*$", body, flags=re.MULTILINE)
    sections = {parts[i]: parts[i + 1].strip() for i in range(1, len(parts) - 1, 2)}
    if not sections.get("SYSTEM") or not sections.get("USER"):
        raise ValueError(f"{path.name}: needs both '## SYSTEM' and '## USER' sections")
    if not path.stem.endswith(f"_v{meta['version']}"):
        raise ValueError(f"{path.name}: filename suffix must match version {meta['version']}")
    return Prompt(name=meta.get("name", path.stem), version=int(meta["version"]), meta=meta,
                  system=sections["SYSTEM"], user_template=sections["USER"])
