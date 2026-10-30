"""The Windows folder chooser, as its own process: a page cannot ask for a real path, and a
window toolkit should not run inside the service. Reads the starting folder from stdin and
prints the choice as JSON; an empty result means the user cancelled.

The service side only starts this module and reads its answer.
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import Protocol

_BACKEND_DIR = Path(__file__).parents[3]
_NO_WINDOW = 0x08000000


class FolderPicker(Protocol):
    def pick(self, initial: Path | None) -> Path | None: ...


class FolderOpener(Protocol):
    def open(self, path: Path) -> None: ...


class DialogFolderPicker:
    def pick(self, initial: Path | None) -> Path | None:
        result = subprocess.run(  # noqa: S603 - fixed module; the path goes through stdin.
            [sys.executable, "-m", "app.adapters.system.folder_dialog"],
            input=json.dumps({"initial": str(initial) if initial else ""}).encode(),
            capture_output=True,
            cwd=_BACKEND_DIR,
            creationflags=_NO_WINDOW,
            check=False,
        )
        if result.returncode != 0:
            raise OSError("folder dialog failed")
        chosen = json.loads(result.stdout or b"{}").get("path")
        return Path(chosen) if chosen else None


class ExplorerFolderOpener:
    def open(self, path: Path) -> None:
        import os

        os.startfile(path)  # type: ignore[attr-defined,unused-ignore]  # noqa: S606


def main() -> int:
    from tkinter import Tk, filedialog

    request = json.loads(sys.stdin.read() or "{}")
    root = Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    chosen = filedialog.askdirectory(
        parent=root,
        title="选择文件夹 · Library Atlas",
        initialdir=request.get("initial") or None,
        mustexist=True,
    )
    root.destroy()
    sys.stdout.write(json.dumps({"path": str(Path(chosen)) if chosen else ""}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
