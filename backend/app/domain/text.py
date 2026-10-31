"""Normalized text used for search and ordering."""

import re
import unicodedata

_DIGITS = re.compile(r"\d+")


def normalize(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def search_text(*parts: str | None) -> str:
    return normalize(" ".join(part for part in parts if part))


def sort_title(title: str) -> str:
    """Case- and width-insensitive; numbers compare by value, so 第2卷 sorts before 第10卷.

    Order is by Unicode code point after normalization. It is stable and predictable but
    is not pinyin or gojūon order, which would need a collation library.
    """
    return _DIGITS.sub(lambda match: match.group().rjust(12, "0"), normalize(title))
