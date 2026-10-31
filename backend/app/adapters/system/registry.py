"""The one part of the registry a game's saves can live in: a key of its own under HKCU\\Software.

Unity's PlayerPrefs are kept there, not in a file. Values are turned into a stable text form, so
they can be backed up, compared and uploaded like any save file. What a game writes about its window
each run is left out, or every launch would look like new progress. Nothing outside the game's own
key can be named: system areas are refused however the path is written.
"""

import base64
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

_PREFIX = "HKCU\\Software\\"
_REFUSED = {
    "microsoft",
    "classes",
    "policies",
    "wow6432node",
    "clients",
    "registeredapplications",
    "appdatalow",
}
_VOLATILE = re.compile(r"^(screenmanager |unityselectmonitor|unity\.|unitygraphicsquality)", re.I)
_MAX_VALUES = 20_000
_MAX_BYTES = 64 * 1024 * 1024
_MAX_DEPTH = 8
_SEGMENT = re.compile(r"^[^\\/\x00-\x1f]{1,255}$")
_WINDOWS_EPOCH = datetime(1601, 1, 1, tzinfo=UTC)


class RegistryRefused(Exception):
    pass


class Registry(Protocol):
    def read(self, key: str) -> dict[str, Any] | None: ...
    def write(self, key: str, values: dict[str, Any]) -> None: ...
    def changed_at(self, key: str) -> datetime | None: ...


def subkey_of(path: str) -> str:
    """`Software\\Company\\Game`, or a refusal."""
    if not path.casefold().startswith(_PREFIX.casefold()):
        raise RegistryRefused
    parts = path[len(_PREFIX) :].split("\\")
    if len(parts) < 2 or not all(_SEGMENT.match(part) for part in parts):
        raise RegistryRefused
    if parts[0].casefold() in _REFUSED or any(part in (".", "..") for part in parts):
        raise RegistryRefused
    return "Software\\" + "\\".join(parts)


def canonical(values: dict[str, Any]) -> bytes:
    return json.dumps(values, ensure_ascii=False, sort_keys=True, indent=0).encode("utf-8")


def player_values(values: dict[str, Any] | None) -> int:
    """How many values a game wrote for itself. A key holding only window settings has no saves."""
    if not values:
        return 0
    return len(values.get("values", {})) + sum(
        player_values(child) for child in values.get("keys", {}).values()
    )


class WindowsRegistry:
    def _read_key(self, handle: Any, depth: int, budget: list[int]) -> dict[str, Any]:
        import winreg

        subkeys, count, _changed = winreg.QueryInfoKey(handle)
        values: dict[str, Any] = {}
        for index in range(count):
            name, data, kind = winreg.EnumValue(handle, index)
            if _VOLATILE.match(name):
                continue
            encoded: Any
            if isinstance(data, bytes):
                encoded = {"bytes": base64.b64encode(data).decode()}
            else:
                encoded = data
            budget[0] -= 1
            budget[1] -= len(json.dumps(encoded, ensure_ascii=False))
            if budget[0] < 0 or budget[1] < 0:
                raise RegistryRefused
            values[name] = {"type": kind, "data": encoded}
        children: dict[str, Any] = {}
        if depth < _MAX_DEPTH:
            for index in range(subkeys):
                name = winreg.EnumKey(handle, index)
                with winreg.OpenKey(handle, name) as child:
                    children[name] = self._read_key(child, depth + 1, budget)
        return {"values": values, "keys": children}

    def read(self, key: str) -> dict[str, Any] | None:
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, subkey_of(key)) as handle:
                return self._read_key(handle, 0, [_MAX_VALUES, _MAX_BYTES])
        except FileNotFoundError:
            return None

    def _write_key(self, handle: Any, values: dict[str, Any], depth: int) -> None:
        import winreg

        if depth > _MAX_DEPTH:
            raise RegistryRefused
        for name, value in values.get("values", {}).items():
            data = value["data"]
            if isinstance(data, dict):
                data = base64.b64decode(data["bytes"])
            winreg.SetValueEx(handle, name, 0, int(value["type"]), data)
        for name, child in values.get("keys", {}).items():
            if not _SEGMENT.match(name) or name in (".", ".."):
                raise RegistryRefused
            with winreg.CreateKeyEx(handle, name, 0, winreg.KEY_WRITE | winreg.KEY_READ) as sub:
                self._write_key(sub, child, depth + 1)

    def write(self, key: str, values: dict[str, Any]) -> None:
        """Only what is listed. A value the backup does not hold is left alone, as with files."""
        import winreg

        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, subkey_of(key), 0, winreg.KEY_WRITE | winreg.KEY_READ
        ) as handle:
            self._write_key(handle, values, 0)

    def changed_at(self, key: str) -> datetime | None:
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, subkey_of(key)) as handle:
                ticks = winreg.QueryInfoKey(handle)[2]
        except FileNotFoundError:
            return None
        return _WINDOWS_EPOCH + timedelta(microseconds=ticks / 10)


@dataclass
class FileRegistry:
    """A test library's registry: one file in its own data, so no test can reach the real one."""

    path: Path

    def _all(self) -> dict[str, Any]:
        return json.loads(self.path.read_text(encoding="utf-8")) if self.path.is_file() else {}

    def read(self, key: str) -> dict[str, Any] | None:
        held = self._all().get(subkey_of(key).casefold())
        if held is None:
            return None
        values = {
            name: value for name, value in held["values"].items() if not _VOLATILE.match(name)
        }
        return {"values": values, "keys": held.get("keys", {})}

    def write(self, key: str, values: dict[str, Any]) -> None:
        held = self._all()
        current = held.get(subkey_of(key).casefold(), {"values": {}, "keys": {}})
        current["values"].update(values.get("values", {}))
        current["keys"].update(values.get("keys", {}))
        current["changed"] = datetime.now(UTC).isoformat()
        held[subkey_of(key).casefold()] = current
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(held, ensure_ascii=False), encoding="utf-8")

    def changed_at(self, key: str) -> datetime | None:
        held = self._all().get(subkey_of(key).casefold())
        return datetime.fromisoformat(held["changed"]) if held else None
