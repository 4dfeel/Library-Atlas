"""What a game's own files say about where it keeps its saves. Suggestions, never conclusions.

Nothing is run, and only names are looked at, apart from Unity's `app.info`: two short lines naming
the company and product, which is exactly where Unity puts the saves. Those lines come from the
game, so they are checked before they become part of any path.
"""

import fnmatch
import os
import re
from dataclasses import dataclass
from pathlib import Path

_MAX_LOOK = 4000
_MAX_APP_INFO = 4096
_UNSAFE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_INSIDE_FOLDERS = ("save", "saves", "savedata", "savedata2", "userdata", "user_data", "savegame")
_RPG_MAKER_FILES = ("Save*.rvdata2", "Save*.rvdata", "Save*.rxdata", "Save*.lsd")


@dataclass(frozen=True)
class KnownFolders:
    local: Path
    local_low: Path
    roaming: Path
    documents: Path
    saved_games: Path

    def roots(self) -> list[Path]:
        return [self.local, self.local_low, self.roaming, self.documents, self.saved_games]


@dataclass(frozen=True)
class Hint:
    kind: str  # inside | outside | registry
    path: str
    reason: str


@dataclass(frozen=True)
class EngineFacts:
    engine: str | None
    company: str | None
    product: str | None
    project: str | None
    hints: tuple[Hint, ...]


def _safe_name(text: str) -> str | None:
    name = text.strip()
    if not name or len(name) > 200 or name in (".", "..") or _UNSAFE.search(name):
        return None
    return name


def _names(root: Path, depth: int = 3) -> dict[str, str]:
    """Lowercased relative path to the real one, a few levels down, within a budget."""
    found: dict[str, str] = {}
    stack: list[tuple[str, str, int]] = [(str(root), "", 0)]
    while stack and len(found) < _MAX_LOOK:
        folder, prefix, level = stack.pop()
        try:
            with os.scandir(folder) as entries:
                for entry in entries:
                    if entry.is_symlink() or entry.is_junction():
                        continue
                    relative = f"{prefix}{entry.name}"
                    found[relative.casefold()] = relative
                    if entry.is_dir(follow_symlinks=False) and level < depth:
                        stack.append((entry.path, f"{relative}/", level + 1))
        except OSError:
            continue
    return found


def _app_info(root: Path, names: dict[str, str]) -> tuple[str | None, str | None]:
    for lowered, real in names.items():
        if lowered.endswith("_data/app.info") and lowered.count("/") == 1:
            try:
                with (root / real).open("rb") as stream:
                    raw = stream.read(_MAX_APP_INFO)
            except OSError:
                return None, None
            lines = raw.decode("utf-8", errors="replace").splitlines()
            if len(lines) >= 2:
                return _safe_name(lines[0]), _safe_name(lines[1])
            return None, None
    return None, None


def _first_folder(names: dict[str, str], candidates: tuple[str, ...]) -> list[str]:
    return [names[item] for item in candidates if item in names]


def read_facts(root: Path, folders: KnownFolders) -> EngineFacts:
    names = _names(root)
    hints: list[Hint] = []
    engine: str | None = None
    company = product = project = None
    tails = {lowered.rsplit("/", 1)[-1] for lowered in names}

    if any(lowered.endswith("js/rmmz_core.js") for lowered in names):
        engine = "RPG Maker MZ"
    elif any(lowered.endswith("js/rpg_core.js") for lowered in names):
        engine = "RPG Maker MV"
    elif any(tail.endswith((".rgss3a", ".rgss2a", ".rgssad")) for tail in tails) or any(
        tail.startswith("rgss") and tail.endswith(".dll") for tail in tails
    ):
        engine = "RPG Maker VX/XP"
    elif any(lowered.endswith("_data/app.info") for lowered in names) or (
        "unityplayer.dll" in tails
    ):
        engine = "Unity"
    elif any("/binaries/win64" in lowered for lowered in names):
        engine = "Unreal"
    elif "renpy" in names or any(tail.endswith(".rpa") for tail in tails):
        engine = "Ren'Py"
    elif any(tail.endswith(".xp3") for tail in tails):
        engine = "KiriKiri"
    elif any(tail.endswith(".wolf") for tail in tails):
        engine = "Wolf RPG"
    elif any(tail.endswith(".pck") for tail in tails):
        engine = "Godot"

    if engine == "Unity":
        company, product = _app_info(root, names)
        if company and product:
            hints.append(
                Hint(
                    "outside",
                    str(folders.local_low / company / product),
                    "Unity 游戏默认把存档放在这里",
                )
            )
            hints.append(
                Hint(
                    "registry",
                    f"HKCU\\Software\\{company}\\{product}",
                    "Unity 的 PlayerPrefs 存档放在注册表",
                )
            )
    elif engine == "Unreal":
        for lowered, real in names.items():
            if lowered.endswith("/binaries") and lowered.count("/") == 1:
                project = real.split("/")[0]
                break
        if project and project.casefold() != "engine":
            hints.append(
                Hint("inside", f"{project}/Saved/SaveGames", "Unreal 游戏可能把存档放在游戏目录")
            )
            hints.append(
                Hint(
                    "outside",
                    str(folders.local / project / "Saved" / "SaveGames"),
                    "Unreal 游戏默认把存档放在这里",
                )
            )
    elif engine == "Ren'Py":
        hints.append(Hint("inside", "game/saves", "Ren'Py 会在游戏目录保留一份存档"))

    # Folders named for the purpose, in the places engines commonly use.
    prefixes = ("", "www/", "game/", "data/")
    wanted = tuple(f"{prefix}{name}" for prefix in prefixes for name in _INSIDE_FOLDERS)
    seen = {hint.path.casefold() for hint in hints}
    for real in _first_folder(names, wanted):
        if real.casefold() not in seen and (root / real).is_dir():
            seen.add(real.casefold())
            hints.append(Hint("inside", real, "游戏目录里有存档文件夹"))
    if engine in ("RPG Maker VX/XP", None):
        for pattern in _RPG_MAKER_FILES:
            if fnmatch.filter(tails, pattern.casefold()):
                hints.append(Hint("inside", pattern, "这种文件是 RPG Maker 的存档"))
    return EngineFacts(engine, company, product, project, tuple(hints))
