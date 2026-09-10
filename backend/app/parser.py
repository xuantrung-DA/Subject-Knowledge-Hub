"""Page-wise PDF adapter. Physical page numbers are always one based.

pypdf owns metadata/text; pdfplumber is only opened for pages with likely ruled
 tables. Unruled tables and images are outside this adapter's reliable scope.
No document-wide text collection is retained in memory.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Iterator

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.errors import AppError

TABLE_START = "[[TABLE]]"
TABLE_END = "[[/TABLE]]"


@dataclass
class ParsedPage:
    number: int
    text: str
    has_text: bool
    warnings: list[str] = field(default_factory=list)


def normalize_text(text: str) -> str:
    text = text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


class PDFParser:
    def __init__(
        self, path: str | Path, *, max_pages: int = 1200, max_page_chars: int = 300_000, extract_tables: bool = True
    ):
        self.path = Path(path)
        self.max_page_chars = max_page_chars
        self.extract_tables = extract_tables
        self._file = None
        self._plumber = None
        try:
            self._file = self.path.open("rb")
            if b"%PDF-" not in self._file.read(1024):
                raise AppError("invalid_pdf", "Tệp không có định dạng PDF hợp lệ.")
            self._file.seek(0)
            self.reader = PdfReader(self._file, strict=False)
            # Encrypted PDFs are explicitly rejected even with an empty password.
            if self.reader.is_encrypted:
                raise AppError("encrypted_pdf", "PDF được mã hóa. Hãy tải bản PDF không có mật khẩu.")
            self.page_count = len(self.reader.pages)
            if self.page_count == 0:
                raise AppError("empty_pdf", "PDF không có trang nào.")
            if self.page_count > max_pages:
                raise AppError("too_many_pages", f"PDF có {self.page_count} trang, vượt giới hạn {max_pages} trang.")
            self.repeated_edges = self._detect_repeated_edges()
        except AppError:
            self.close()
            raise
        except (OSError, PdfReadError, ValueError, KeyError, TypeError) as exc:
            self.close()
            raise AppError("corrupt_pdf", "Không đọc được PDF. Tệp có thể bị hỏng hoặc không hoàn chỉnh.") from exc

    def _extract_text(self, index: int) -> str:
        try:
            text = normalize_text(self.reader.pages[index].extract_text() or "")
            if len(text) > self.max_page_chars:
                raise AppError(
                    "page_too_large", f"Trang {index + 1} vượt giới hạn nội dung an toàn ({self.max_page_chars} ký tự)."
                )
            return text
        except AppError:
            raise
        except Exception as exc:
            raise AppError("page_parse_error", f"Không thể đọc trang PDF {index + 1}.") from exc

    def _detect_repeated_edges(self) -> set[tuple[str, str]]:
        # Only exact short edge strings present in >=80% of >=5 sampled pages.
        # Strings occurring inside a page are retained. Numeric-only folios are
        # left alone: broad digit removal can silently destroy legitimate data.
        if self.page_count < 5:
            return set()
        indices = sorted({round(i * (self.page_count - 1) / 11) for i in range(min(12, self.page_count))})
        # With fewer than 12 pages use all, not an uneven truncated stride.
        if self.page_count < 12:
            indices = list(range(self.page_count))
        counts: Counter[tuple[str, str]] = Counter()
        for i in indices:
            lines = [line.strip() for line in self._extract_text(i).splitlines() if line.strip()]
            if len(lines) < 5:
                continue
            for side, line in (("first", lines[0]), ("last", lines[-1])):
                if 3 <= len(line) <= 100 and not line.isdecimal() and lines.count(line) == 1:
                    counts[(side, line)] += 1
        return {key for key, count in counts.items() if count >= max(5, len(indices) * 0.8)}

    def _table_text(self, index: int) -> tuple[list[str], list[str]]:
        if not self.extract_tables:
            return [], []
        page = self.reader.pages[index]
        # Ruled tables generally contain several line/rectangle draw operations.
        # This skips costly pdfplumber layout parsing for ordinary text pages.
        contents = page.get_contents()
        raw = contents.get_data() if contents is not None else b""
        if len(re.findall(rb"(?:\s|^)(?:re|l)\s", raw)) < 4:
            return [], []
        try:
            if self._plumber is None:
                import pdfplumber

                self._plumber = pdfplumber.open(self.path)
            pl_page = self._plumber.pages[index]
            try:
                output = []
                for table in pl_page.extract_tables():
                    rows = [[normalize_text(str(cell or "")).replace("\n", " / ") for cell in row] for row in table]
                    if len(rows) >= 2 and max(map(len, rows), default=0) >= 2:
                        output.append(
                            TABLE_START + "\n" + "\n".join(" | ".join(row) for row in rows) + "\n" + TABLE_END
                        )
                return output, []
            finally:
                pl_page.close()
        except Exception:
            return [], [f"Không nhận diện được bảng tại trang {index + 1}; giữ lại văn bản gốc."]

    def pages(self, start_page: int = 1) -> Iterator[ParsedPage]:
        for index in range(max(1, start_page) - 1, self.page_count):
            text = self._extract_text(index)
            lines = text.splitlines()
            if lines and ("first", lines[0].strip()) in self.repeated_edges:
                lines.pop(0)
            if lines and ("last", lines[-1].strip()) in self.repeated_edges:
                lines.pop()
            text = "\n".join(lines).strip()
            tables, warnings = self._table_text(index)
            # Retaining original page text avoids accidental data loss. Recognized
            # tables are appended as atomic blocks; duplicate lexical text is an
            # explicit V1 trade-off, preferable to guessed bounding-box deletion.
            if tables:
                text += "\n\n" + "\n\n".join(tables)
            if len(text) > self.max_page_chars:
                raise AppError("page_too_large", f"Trang {index + 1} vượt giới hạn nội dung an toàn.")
            yield ParsedPage(index + 1, text, bool(re.search(r"\w", text)), warnings)

    def close(self) -> None:
        if self._plumber is not None:
            self._plumber.close()
            self._plumber = None
        if self._file is not None:
            self._file.close()
            self._file = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
