"""What a file says it is, from its first bytes, before anything tries to decode it.

The extension decides nothing: a page is served as an image only if its header agrees, and a header
declaring an absurd size is refused here rather than handed to a browser to allocate.
"""

import struct
from dataclasses import dataclass

HEAD_BYTES = 1024 * 1024
MAX_SIDE = 65_535
MAX_PIXELS = 400_000_000


@dataclass(frozen=True)
class ImageHeader:
    media_type: str
    width: int | None  # None where the header could not say; only the file size bounds those.
    height: int | None


def _jpeg_size(head: bytes) -> tuple[int, int] | None:
    position = 2
    while position + 9 < len(head):
        if head[position] != 0xFF:
            return None
        marker = head[position + 1]
        if marker == 0xFF:
            position += 1
            continue
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            height, width = struct.unpack(">HH", head[position + 5 : position + 9])
            return width, height
        position += 2 + struct.unpack(">H", head[position + 2 : position + 4])[0]
    return None


def _webp_size(head: bytes) -> tuple[int, int] | None:
    chunk = head[12:16]
    if chunk == b"VP8X" and len(head) >= 30:
        width = int.from_bytes(head[24:27], "little") + 1
        return width, int.from_bytes(head[27:30], "little") + 1
    if chunk == b"VP8 " and len(head) >= 30:
        width, height = struct.unpack("<HH", head[26:30])
        return width & 0x3FFF, height & 0x3FFF
    if chunk == b"VP8L" and len(head) >= 25:
        bits = int.from_bytes(head[21:25], "little")
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    return None


def read_header(head: bytes) -> ImageHeader | None:
    """None when this is not an image of a known type."""
    size: tuple[int, int] | None
    if head.startswith(b"\x89PNG\r\n\x1a\n") and len(head) >= 24:
        media_type, size = "image/png", struct.unpack(">II", head[16:24])
    elif head[:6] in (b"GIF87a", b"GIF89a") and len(head) >= 10:
        media_type, size = "image/gif", struct.unpack("<HH", head[6:10])
    elif head.startswith(b"\xff\xd8\xff"):
        media_type, size = "image/jpeg", _jpeg_size(head)
    elif head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        media_type, size = "image/webp", _webp_size(head)
    elif head[:2] == b"BM" and len(head) >= 26:
        width, height = struct.unpack("<ii", head[18:26])
        media_type, size = "image/bmp", (width, abs(height))
    elif head[4:8] == b"ftyp" and head[8:12] in (b"avif", b"avis"):
        media_type, size = "image/avif", None
    else:
        return None
    return ImageHeader(media_type, *(size or (None, None)))


def acceptable(header: ImageHeader) -> bool:
    if header.width is None or header.height is None:
        return True
    return (
        0 < header.width <= MAX_SIDE
        and 0 < header.height <= MAX_SIDE
        and header.width * header.height <= MAX_PIXELS
    )
