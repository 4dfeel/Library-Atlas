"""The drives on this computer, so the user can choose which to look through."""

import ctypes
import os
import string
from dataclasses import dataclass

_KINDS = {2: "removable", 3: "fixed", 4: "network", 5: "optical", 6: "ram"}


@dataclass(frozen=True)
class Volume:
    letter: str
    kind: str
    available: bool


def list_volumes() -> list[Volume]:
    get_type = ctypes.windll.kernel32.GetDriveTypeW
    volumes = []
    for letter in string.ascii_uppercase:
        root = f"{letter}:\\"
        kind = _KINDS.get(get_type(root))
        if kind is None or kind == "optical":
            continue
        # A network drive is listed but not touched: even looking at one can hang.
        volumes.append(Volume(letter, kind, kind != "network" and os.path.isdir(root)))
    return volumes
