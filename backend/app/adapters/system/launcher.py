"""Hands a program to Windows. An argument list and no shell, so nothing in a path or an argument
can be read as a command. Atlas does not wait for it or raise its rights. It keeps only a way to see
when it has ended; closing Atlas does not close the game.
"""

import subprocess
import uuid
from pathlib import Path

from app.adapters.system.process_job import ProcessWatch

_DETACHED_PROCESS = 0x00000008
_NEW_GROUP = 0x00000200


class ProcessLauncher:
    def launch(self, program: Path, arguments: list[str], working: Path) -> ProcessWatch:
        process = subprocess.Popen(  # noqa: S603 - a saved, re-checked program from the user's click.
            [str(program), *arguments],
            cwd=working,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=_DETACHED_PROCESS | _NEW_GROUP,
        )
        return ProcessWatch.follow(process, f"LibraryAtlas-Play-{uuid.uuid4().hex}")
