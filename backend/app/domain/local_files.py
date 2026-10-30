"""Which programs in a folder could be a work's own, judged from names alone. Nothing is opened or
run to find out, and a guess is only ever a suggestion: the first program found is not a choice."""

import os
import re
from dataclasses import dataclass
from pathlib import Path

_MAX_DEPTH = 3
_MAX_ENTRIES = 300
_MAX_VISITED = 20_000
# Programs that come with a game without being the game.
_HELPERS = re.compile(
    r"unins|setup|install|update|patch|crash|report|config|launcher_helper|notification_helper"
    r"|redist|vcredist|dxsetup|dxwebsetup|directx|dotnet|ue4prereq|cefprocess|cefsharp|ffmpeg"
    r"|^7z|^rar|^unrar|winrar|helper|settings|repair",
    re.IGNORECASE,
)
_SKIPPED_FOLDERS = re.compile(
    r"^(redist|_commonredist|redistributable|directx|dotnet|vcredist|__macosx|\$recycle\.bin)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class EntryCandidate:
    path: str  # Relative to the folder, separated by "/".
    helper: bool
    depth: int


def entry_candidates(root: Path) -> list[EntryCandidate]:
    """Shallow and bounded: a folder of a hundred thousand files must not take long to look at.
    Links are not followed, so this cannot wander out of the folder."""
    found: list[EntryCandidate] = []
    visited = 0
    stack: list[tuple[str, str, int]] = [(str(root), "", 0)]
    while stack and len(found) < _MAX_ENTRIES and visited < _MAX_VISITED:
        folder, prefix, depth = stack.pop()
        try:
            with os.scandir(folder) as entries:
                for entry in entries:
                    visited += 1
                    if entry.is_symlink() or entry.is_junction():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        if depth < _MAX_DEPTH and not _SKIPPED_FOLDERS.match(entry.name):
                            stack.append((entry.path, f"{prefix}{entry.name}/", depth + 1))
                    elif entry.name.lower().endswith(".exe"):
                        found.append(
                            EntryCandidate(
                                f"{prefix}{entry.name}", bool(_HELPERS.search(entry.name)), depth
                            )
                        )
        except OSError:
            continue
    return sorted(found, key=lambda item: (item.helper, item.depth, item.path.casefold()))


def single_entry(candidates: list[EntryCandidate]) -> str | None:
    """The program, when exactly one is plausible. Two at the same level is a real question."""
    games = [item for item in candidates if not item.helper]
    if not games:
        return None
    top = games[0].depth
    level = [item for item in games if item.depth == top]
    return level[0].path if len(level) == 1 else None
