import pytest
from pypdf import PdfWriter
from reportlab.pdfgen import canvas
from app.errors import AppError
from app.parser import PDFParser, ParsedPage, TABLE_START, TABLE_END
from app.chunking import chunk_pages
from app.tokens import count_tokens


def pdf(path, texts):
    c = canvas.Canvas(str(path))
    for text in texts:
        obj = c.beginText(40, 790)
        for line in text.splitlines():
            obj.textLine(line)
        c.drawText(obj)
        c.showPage()
    c.save()
    return path


def test_page_numbers_and_mixed_text(tmp_path):
    path = pdf(tmp_path / "mixed.pdf", ["Beginning fact is twelve.", "", "End fact is forty."])
    with PDFParser(path) as parser:
        pages = list(parser.pages())
        assert parser.page_count == 3
        assert [p.number for p in pages] == [1, 2, 3]
        assert [p.has_text for p in pages] == [True, False, True]
        assert [p.number for p in parser.pages(3)] == [3]
    assert parser._file is None


@pytest.mark.parametrize(
    "payload,code", [(b"", "invalid_pdf"), (b"not PDF", "invalid_pdf"), (b"%PDF-1.7\ntruncated", "corrupt_pdf")]
)
def test_corrupt_pdf(tmp_path, payload, code):
    path = tmp_path / "bad.pdf"
    path.write_bytes(payload)
    with pytest.raises(AppError) as caught:
        PDFParser(path)
    assert caught.value.code == code


def test_encrypted_and_page_limit(tmp_path):
    path = tmp_path / "locked.pdf"
    writer = PdfWriter()
    writer.add_blank_page(100, 100)
    writer.encrypt("password")
    writer.write(path)
    with pytest.raises(AppError, match="mã hóa") as caught:
        PDFParser(path)
    assert caught.value.code == "encrypted_pdf"
    pdf(path, ["Page one", "Page two"])
    with pytest.raises(AppError) as caught:
        PDFParser(path, max_pages=1)
    assert caught.value.code == "too_many_pages"


def test_page_content_guard(tmp_path):
    path = pdf(tmp_path / "big.pdf", ["A considerable amount of text on one page."])
    with PDFParser(path, max_page_chars=10) as parser:
        with pytest.raises(AppError) as caught:
            list(parser.pages())
    assert caught.value.code == "page_too_large"


def test_header_footer_requires_repetition_at_edges(tmp_path):
    texts = [
        f"Course handbook\nTopic {i}\nFirst content {i}\nCourse handbook\nSecond content {i}\nConfidential copy"
        for i in range(10)
    ]
    path = pdf(tmp_path / "headers.pdf", texts)
    with PDFParser(path) as parser:
        pages = list(parser.pages())
    # Header also appears in the body, so conservative rule retains it.
    assert pages[0].text.count("Course handbook") == 2
    assert "Confidential copy" not in pages[0].text
    assert "Second content 0" in pages[0].text


def test_chunk_provenance_and_token_budget():
    pages = [ParsedPage(i, ("A paragraph about topic number " + str(i) + ". ") * 45, True) for i in range(1, 5)]
    chunks = list(chunk_pages(pages, target_tokens=100, overlap_tokens=15))
    assert len(chunks) > 4
    assert [c.ordinal for c in chunks] == list(range(len(chunks)))
    assert all(c.token_count == count_tokens(c.text) <= 100 for c in chunks)
    assert all(c.page_start == min(c.pages) and c.page_end == max(c.pages) for c in chunks)
    assert set(n for c in chunks for n in c.pages) == {1, 2, 3, 4}
    assert all(c.content_hash for c in chunks)
    assert list(chunk_pages(pages, target_tokens=100, overlap_tokens=15)) == chunks


def test_short_pages_keep_citations_on_the_supporting_page(tmp_path):
    path = pdf(tmp_path / "specific.pdf", ["Training batch size is 32.", "", "Test F1 is 0.88.", "Unrelated appendix."])
    with PDFParser(path) as parser:
        chunks = list(chunk_pages(parser.pages(), page_boundaries=True))
    evidence = next(c for c in chunks if "F1 is 0.88" in c.text)
    assert evidence.pages == [3]
    assert evidence.page_start == evidence.page_end == 3
    assert "Training" not in evidence.text and "appendix" not in evidence.text
    assert [c.ordinal for c in chunks] == list(range(len(chunks)))


def test_vietnamese_unicode_survives_long_paragraph():
    original = "Học máy có giám sát sử dụng dữ liệu được gán nhãn. " * 100
    chunks = list(chunk_pages([ParsedPage(1, original, True)], target_tokens=80, overlap_tokens=0))
    assert "\ufffd" not in "".join(c.text for c in chunks)
    assert "".join(c.text.replace(" ", "").replace("\n", "") for c in chunks) == original.replace(" ", "")
    assert all(c.token_count <= 80 for c in chunks)


def test_tables_are_atomic_when_larger_than_target():
    table = TABLE_START + "\nName | Value\n" + "\n".join(f"row-{i} | value-{i}" for i in range(50)) + "\n" + TABLE_END
    chunks = list(chunk_pages([ParsedPage(4, "Heading\n\n" + table + "\n\nClosing note", True)], target_tokens=100))
    matches = [c for c in chunks if TABLE_START in c.text]
    assert len(matches) == 1
    assert matches[0].text == table
    assert matches[0].pages == [4]


def test_ruled_table_is_detected(tmp_path):
    path = tmp_path / "table.pdf"
    c = canvas.Canvas(str(path))
    for y in [750, 720, 690, 660]:
        c.line(40, y, 300, y)
    for x in [40, 170, 300]:
        c.line(x, 660, x, 750)
    for row, values in enumerate([("Name", "Value"), ("Solar", "42"), ("Wind", "17")]):
        for col, value in enumerate(values):
            c.drawString(45 + col * 130, 730 - row * 30, value)
    c.showPage()
    c.save()
    with PDFParser(path) as parser:
        page = next(parser.pages())
    assert TABLE_START in page.text
    assert "Solar | 42" in page.text
