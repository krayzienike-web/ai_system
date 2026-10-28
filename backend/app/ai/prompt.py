"""Prompts are files with a version (CLAUDE.md: `backend/app/ai/prompts/`, a change → an eval run).

A prompt is `prompts/<name>.v<N>.md`. A change is a new file with the next number, never an edit of an old
one: every call in `ai_runs` names the version it ran with, so an answer can be explained later.
"""

import hashlib
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

PROMPTS = Path(__file__).parent / "prompts"
FILE = re.compile(r"^(?P<name>[a-z_]+)\.v(?P<version>\d+)\.md$")


@dataclass(frozen=True)
class Prompt:
    name: str
    version: int
    text: str

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.text.encode()).hexdigest()


def versions(name: str) -> dict[int, Path]:
    found = {}
    for path in PROMPTS.glob(f"{name}.v*.md"):
        m = FILE.match(path.name)
        if m and m["name"] == name:
            found[int(m["version"])] = path
    return found


@cache
def load(name: str, version: int | None = None) -> Prompt:
    """The given version, or the latest one."""
    found = versions(name)
    if not found:
        raise LookupError(f"no prompt {name!r} in {PROMPTS}")
    v = max(found) if version is None else version
    if v not in found:
        raise LookupError(f"no version {v} of prompt {name!r}")
    return Prompt(name, v, found[v].read_text(encoding="utf-8").strip())
