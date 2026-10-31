"""Stands in for the shell in a test library: no test touches the real desktop or Recycle Bin.

The folder really leaves its place, to a bin inside the test's own data, so tests can see that.
"""

import json
import shutil
import uuid
from pathlib import Path


class FakeShell:
    def __init__(self, data_dir: Path) -> None:
        self._bin = data_dir / "fake-recycle-bin"
        self._desktop = data_dir / "fake-desktop"
        self._refuse = data_dir / "fake-recycle-refuses"

    def recycle(self, path: Path) -> None:
        if self._refuse.exists():
            raise OSError("refused")
        self._bin.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), self._bin / uuid.uuid4().hex)

    def desktop(self) -> Path:
        self._desktop.mkdir(parents=True, exist_ok=True)
        return self._desktop

    def write_shortcut(
        self,
        link: Path,
        target: Path,
        arguments: list[str],
        working: Path | None,
        icon: Path | None,
    ) -> None:
        link.write_text(
            json.dumps(
                {
                    "target": str(target),
                    "arguments": arguments,
                    "working": str(working) if working else None,
                    "icon": str(icon) if icon else None,
                }
            ),
            encoding="utf-8",
        )
