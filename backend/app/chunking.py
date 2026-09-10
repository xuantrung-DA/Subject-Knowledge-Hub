"""Streaming paragraph chunks with physical-page provenance and token overlap."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from typing import Iterable, Iterator

from app.parser import TABLE_END, TABLE_START
from app.tokens import count_tokens, count_embedding_tokens, trim_tokens


@dataclass
class TextChunk:
    ordinal: int
    text: str
    token_count: int
    page_start: int
    page_end: int
    pages: list[int]
    content_hash: str


def _split_long(text: str, limit: int) -> Iterator[str]:
    """Tokenizer slices cannot drop Unicode bytes: prefer safe text boundaries."""
    while count_tokens(text) > limit:
        prefix = trim_tokens(text, limit)
        if not prefix:
            raise ValueError("Tokenizer could not produce a nonempty token slice")
        # Prefer paragraph/sentence/word boundaries when they retain >= half.
        boundaries = [prefix.rfind("\n"), prefix.rfind(". "), prefix.rfind(" ")]
        cut = max(boundaries)
        if cut > len(prefix) // 2:
            prefix = prefix[:cut]
        # tiktoken decode can end at partial Unicode; trim to an actual prefix.
        while prefix and not text.startswith(prefix):
            prefix = prefix[:-1]
        if not prefix:
            prefix = text[0]
        yield prefix.strip()
        text = text[len(prefix) :].lstrip()
    if text.strip():
        yield text.strip()


def _blocks(text: str, limit: int) -> Iterator[tuple[str, bool]]:
    for part in re.split(r"(\[\[TABLE\]\].*?\[\[/TABLE\]\])", text, flags=re.DOTALL):
        if not part.strip():
            continue
        if part.startswith(TABLE_START):
            if max(count_tokens(part), count_embedding_tokens(part)) <= 7800:
                yield part, True
            else:
                # Oversized tables must fit the embedding input limit. Split by
                # rows, repeat header, and preserve row contents when possible.
                rows = part.splitlines()[1:-1]
                header = rows[0] if rows else ""
                group = [header]
                for row in rows[1:]:
                    if (
                        max(count_tokens("\n".join(group + [row])), count_embedding_tokens("\n".join(group + [row])))
                        > 7000
                    ):
                        yield TABLE_START + "\n" + "\n".join(group) + "\n" + TABLE_END, True
                        group = [header]
                    if max(count_tokens(row), count_embedding_tokens(row)) > 6000:
                        for fragment in _split_long(row, min(limit, 6000)):
                            yield header + "\n" + fragment, True
                    else:
                        group.append(row)
                if len(group) > 1:
                    yield TABLE_START + "\n" + "\n".join(group) + "\n" + TABLE_END, True
        else:
            for paragraph in re.split(r"\n\s*\n", part):
                if paragraph.strip():
                    for fragment in _split_long(paragraph.strip(), limit):
                        yield fragment, False


def chunk_pages(
    pages: Iterable, *, target_tokens: int = 600, overlap_tokens: int = 80, page_boundaries: bool = False
) -> Iterator[TextChunk]:
    if target_tokens < 32 or overlap_tokens < 0 or overlap_tokens >= target_tokens:
        raise ValueError("Require target_tokens >= 32 and 0 <= overlap_tokens < target_tokens")
    pieces: list[tuple[str, int]] = []
    ordinal = 0

    def make_chunk() -> TextChunk:
        nonlocal ordinal
        text = "\n\n".join(value for value, _ in pieces).strip()
        numbers = sorted({number for _, number in pieces})
        item = TextChunk(
            ordinal,
            text,
            count_tokens(text),
            numbers[0],
            numbers[-1],
            numbers,
            hashlib.sha256(text.encode()).hexdigest(),
        )
        ordinal += 1
        return item

    def overlap() -> list[tuple[str, int]]:
        # Keep only full trailing fragments unless one fragment exceeds budget.
        result: list[tuple[str, int]] = []
        remaining = overlap_tokens
        for value, number in reversed(pieces):
            cost = count_tokens(value)
            if cost <= remaining:
                result.insert(0, (value, number))
                remaining -= cost
            elif remaining > 0:
                # Find a suffix by token-aware binary search on Unicode text.
                lo, hi = 0, len(value)
                while lo < hi:
                    mid = (lo + hi) // 2
                    if count_tokens(value[mid:]) <= remaining:
                        hi = mid
                    else:
                        lo = mid + 1
                suffix = value[lo:].strip()
                if suffix:
                    result.insert(0, (suffix, number))
                break
            else:
                break
        return result

    for page in pages:
        number = getattr(page, "page_number", None) or getattr(page, "number", None)
        if page_boundaries and pieces and pieces[-1][1] != number:
            yield make_chunk()
            pieces = []
        for block, is_table in _blocks(page.text, target_tokens - overlap_tokens):
            if is_table:
                if pieces:
                    yield make_chunk()
                    pieces = []
                pieces = [(block, number)]
                yield make_chunk()
                pieces = []
                continue
            combined = "\n\n".join([p[0] for p in pieces] + [block])
            if pieces and count_tokens(combined) > target_tokens:
                yield make_chunk()
                pieces = overlap()
                # Delimiters count toward budget, not just individual texts.
                while pieces and count_tokens("\n\n".join([p[0] for p in pieces] + [block])) > target_tokens:
                    pieces.pop(0)
            pieces.append((block, number))
    if pieces:
        yield make_chunk()
