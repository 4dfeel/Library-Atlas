"""Stores one session in the credential store, split to fit its per-entry limit.

A generation is written in full before its manifest is written, so a failure part way
leaves the previous session readable and no half session is ever accepted. Reading
checks the length and hash; anything else counts as no usable session.
"""

import hashlib
import json
from dataclasses import dataclass

from app.core.credentials import MAX_BLOB_BYTES, CredentialStore, CredentialStoreError

_MANIFEST = "manifest"


class SessionCorrupt(Exception):
    """The stored session is incomplete or damaged. Holds no values."""


@dataclass(frozen=True)
class _Manifest:
    generation: int
    parts: int
    length: int
    sha256: str


class SessionVault:
    def __init__(self, store: CredentialStore, name: str) -> None:
        self._store = store
        self._name = name

    def _part(self, generation: int, index: int) -> str:
        return f"{self._name}/{generation}/{index}"

    def _manifest_name(self) -> str:
        return f"{self._name}/{_MANIFEST}"

    def _read_manifest(self) -> _Manifest | None:
        raw = self._store.read(self._manifest_name())
        if raw is None:
            return None
        try:
            data = json.loads(raw)
            return _Manifest(
                generation=int(data["generation"]),
                parts=int(data["parts"]),
                length=int(data["length"]),
                sha256=str(data["sha256"]),
            )
        except (ValueError, KeyError, TypeError):
            raise SessionCorrupt from None

    def _delete_parts(self, manifest: _Manifest) -> None:
        for index in range(manifest.parts):
            self._store.delete(self._part(manifest.generation, index))

    def save(self, secret: bytes) -> None:
        try:
            previous = self._read_manifest()
        except SessionCorrupt:
            previous = None
        generation = (previous.generation + 1) if previous else 1
        chunks = [
            secret[start : start + MAX_BLOB_BYTES]
            for start in range(0, len(secret), MAX_BLOB_BYTES)
        ] or [b""]
        manifest = _Manifest(
            generation, len(chunks), len(secret), hashlib.sha256(secret).hexdigest()
        )
        try:
            for index, chunk in enumerate(chunks):
                self._store.write(self._part(generation, index), chunk)
            self._store.write(
                self._manifest_name(),
                json.dumps(manifest.__dict__, separators=(",", ":")).encode(),
            )
        except CredentialStoreError:
            # Clear this generation's pieces; a failure here is reported by the save error.
            for index in range(len(chunks)):
                try:
                    self._store.delete(self._part(generation, index))
                except CredentialStoreError:
                    break
            raise
        if previous:
            try:
                self._delete_parts(previous)
            except CredentialStoreError:
                pass  # Unreferenced; the next save or delete does not depend on it.

    def load(self) -> bytes | None:
        manifest = self._read_manifest()
        if manifest is None:
            return None
        parts: list[bytes] = []
        for index in range(manifest.parts):
            part = self._store.read(self._part(manifest.generation, index))
            if part is None:
                raise SessionCorrupt
            parts.append(part)
        secret = b"".join(parts)
        if len(secret) != manifest.length or hashlib.sha256(secret).hexdigest() != manifest.sha256:
            raise SessionCorrupt
        return secret

    def delete(self) -> None:
        """The manifest goes first, so a later failure can never leave a readable session."""
        try:
            manifest = self._read_manifest()
        except SessionCorrupt:
            manifest = None
        self._store.delete(self._manifest_name())
        if manifest:
            self._delete_parts(manifest)
