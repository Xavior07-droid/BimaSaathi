"""Prompt registry + lint + version lock (A26). Standard library only.

Why: prompts are code. Once a prompt version has an eval score (docs/eval.md) it must not change in place, so
`prompts.lock.json` stores a SHA-256 of every prompt file. Editing a prompt without bumping its version (or
re-locking on purpose) fails the tests.

CLI:  python scripts/prompt_versions.py [--check | --update]
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

from app.prompts import PROMPT_DIR, load_prompt

APP_DIR = PROMPT_DIR.parent
SERVICES_DIR = APP_DIR / "services"
SCHEMA_DIR = APP_DIR / "data" / "schemas"
LOCK_PATH = PROMPT_DIR / "prompts.lock.json"

# Prompts that exist but no service calls yet. Remove the name from this set when the service is wired
# (a test fails if a listed prompt IS in use, so the list cannot go stale).
PLANNED_UNUSED: frozenset[str] = frozenset({"summary_v1"})

_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*_v[1-9][0-9]*$")
_PLACEHOLDER = re.compile(r"\{\{([^{}]*)\}\}")
_SCHEMA_REF = re.compile(r"app/data/schemas/([A-Za-z0-9_.]+\.json)")
_PROMPT_NAME = re.compile(r'^PROMPT_NAME\s*=\s*"([^"]+)"', re.MULTILINE)
_FORBIDDEN = ("gemini" + "-", "flash", "api_key", "aiza", "bearer ", "private_key")   # model IDs and secrets never live in prompts


@dataclass(frozen=True)
class PromptInfo:
    label: str
    version: int
    temperature: float
    fingerprint: str
    used_by: tuple[str, ...]


def prompt_names() -> list[str]:
    """Every prompt file stem (x_v1, ...). Non-prompt files in the folder are ignored."""
    return sorted(p.stem for p in PROMPT_DIR.glob("*_v*.md"))


def fingerprint(name: str) -> str:
    """SHA-256 of the file with line endings normalised (Windows CRLF and Linux LF give the same hash)."""
    text = (PROMPT_DIR / f"{name}.md").read_bytes().decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def prompt_users() -> dict[str, list[str]]:
    """Which services/*.py declare PROMPT_NAME = "<prompt>"."""
    users: dict[str, list[str]] = {}
    for path in sorted(SERVICES_DIR.glob("*.py")):
        for name in _PROMPT_NAME.findall(path.read_text(encoding="utf-8")):
            users.setdefault(name, []).append(path.stem)
    return users


def lint(name: str) -> list[str]:
    """Problems with one prompt file (empty list = clean)."""
    problems: list[str] = []
    if not _NAME_RE.match(name):
        return [f"{name}: file name must look like <name>_v<N> (lowercase, N >= 1)"]
    try:
        p = load_prompt(name)
    except (ValueError, OSError) as e:                       # loader already checks front matter, sections, suffix
        return [f"{name}: {e}"]
    if f"{p.name}_v{p.version}" != name:
        problems.append(f"{name}: front matter says {p.name}_v{p.version}")
    try:
        t = float(p.meta.get("temperature", ""))
        if not 0.0 <= t <= 1.0:
            problems.append(f"{name}: temperature {t} outside 0..1")
    except ValueError:
        problems.append(f"{name}: front matter needs a numeric 'temperature'")
    ref = _SCHEMA_REF.search(p.meta.get("response", ""))
    if not ref:
        problems.append(f"{name}: front matter 'response' must name its schema file under app/data/schemas/")
    elif not (SCHEMA_DIR / ref.group(1)).is_file():
        problems.append(f"{name}: schema file {ref.group(1)} does not exist")
    low = (p.system + "\n" + p.user_template).lower()
    for bad in _FORBIDDEN:
        if bad in low:
            problems.append(f"{name}: contains '{bad}' (no model IDs or secrets in prompts)")
    if "DATA" not in p.system:
        problems.append(f"{name}: system prompt must tell the model that supplied text is DATA (injection guard)")
    if "ONLY" not in p.system:
        problems.append(f"{name}: system prompt must demand JSON-only output")
    for ph in _PLACEHOLDER.findall(p.user_template):
        if not re.fullmatch(r"[A-Z][A-Z_]*", ph):
            problems.append(f"{name}: bad placeholder {{{{{ph}}}}} (use UPPER_SNAKE)")
    filled = set(_PLACEHOLDER.findall(p.user_template))
    stray = set(_PLACEHOLDER.findall(p.system)) - filled     # mentioning a USER placeholder in SYSTEM is fine (ask_v1 does)
    if stray:
        problems.append(f"{name}: SYSTEM mentions placeholders {sorted(stray)} that USER never fills (they would reach the model raw)")
    return problems


def lint_all() -> list[str]:
    out: list[str] = []
    for n in prompt_names():
        out += lint(n)
    return out


def current_lock() -> dict[str, str]:
    return {n: fingerprint(n) for n in prompt_names()}


def read_lock() -> dict[str, str]:
    if not LOCK_PATH.is_file():
        return {}
    return json.loads(LOCK_PATH.read_text(encoding="utf-8"))["prompts"]


def write_lock() -> None:
    body = {"_note": "SHA-256 of each prompt file (line endings normalised). Do not edit by hand: run "
                     "`python scripts/prompt_versions.py --update`. Prefer a NEW version file over re-locking a scored prompt.",
            "prompts": current_lock()}
    LOCK_PATH.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def lock_problems() -> list[str]:
    """Differences between the lock file and the prompt files on disk."""
    locked, now = read_lock(), current_lock()
    out = []
    for n in sorted(set(locked) | set(now)):
        if n not in now:
            out.append(f"{n}: in lock file but the prompt file is gone")
        elif n not in locked:
            out.append(f"{n}: new prompt, not locked yet (run scripts/prompt_versions.py --update)")
        elif locked[n] != now[n]:
            out.append(f"{n}: edited in place. Bump the version (copy to _v{int(n.rsplit('_v', 1)[1]) + 1}) "
                       f"or, if it has no eval score yet, run scripts/prompt_versions.py --update")
    return out


def describe() -> list[PromptInfo]:
    users = prompt_users()
    out = []
    for n in prompt_names():
        p = load_prompt(n)
        out.append(PromptInfo(n, p.version, float(p.meta.get("temperature", "nan")), fingerprint(n)[:12],
                              tuple(users.get(n, ()))))
    return out
