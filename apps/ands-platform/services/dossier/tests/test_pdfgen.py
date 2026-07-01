"""pdfgen — minimal dependency-free single-page PDF writer (pure)."""

from app import pdfgen


def test_starts_with_pdf_header():
    out = pdfgen.text_pdf("Product Monograph", "Body text.")
    assert out.startswith(b"%PDF-")
    assert out.startswith(b"%PDF-1.4")


def test_has_eof_marker():
    out = pdfgen.text_pdf("T", "B")
    assert out.rstrip().endswith(b"%%EOF")
    assert b"%%EOF" in out


def test_contains_catalog_and_font():
    out = pdfgen.text_pdf("T", "B")
    assert b"/Type /Catalog" in out
    assert b"/Type /Pages" in out
    assert b"/Font" in out
    assert b"/BaseFont /Helvetica" in out


def test_letter_mediabox_present():
    out = pdfgen.text_pdf("T", "B")
    assert b"/MediaBox [0 0 612 792]" in out


def test_title_ascii_bytes_appear_in_stream():
    title = "AcmePharmaProductMonograph"
    out = pdfgen.text_pdf(title, "some body")
    assert title.encode("ascii") in out


def test_body_text_appears():
    out = pdfgen.text_pdf("Title", "TheBodyMarkerXYZ")
    assert b"TheBodyMarkerXYZ" in out


def test_xref_trailer_and_startxref_present():
    out = pdfgen.text_pdf("T", "B")
    assert b"\nxref\n" in out
    assert b"trailer" in out
    assert b"startxref" in out
    assert b"/Root 1 0 R" in out


def test_roundtrip_byte_length_over_400():
    out = pdfgen.text_pdf("A reasonably titled document",
                          "A paragraph of body text that says a few things.")
    assert isinstance(out, bytes)
    assert len(out) > 400


def test_escaping_of_parens_in_title():
    out = pdfgen.text_pdf("Dose (mg) \\ note", "b")
    # raw parens/backslash from the title must be escaped in the stream
    assert b"\\(mg\\)" in out
    assert b"\\\\ note" in out
    # the escaped form is present; the naked "(mg)" only ever appears escaped
    assert b"(mg)" not in out


def test_content_operators_present():
    out = pdfgen.text_pdf("Hello", "World")
    for op in (b"BT", b"ET", b"Tf", b"Tj", b"T*", b" Tm"):
        assert op in out


def test_uses_text_leading_operators():
    out = pdfgen.text_pdf("Hello", "World")
    assert b"14 TL" in out          # 14pt leading
    assert b"18 Tf" in out          # title is larger
    assert b"11 Tf" in out          # body is smaller


def test_long_body_is_wrapped_not_one_line():
    long = "word " * 200
    lines = pdfgen._wrap(long)
    assert len(lines) > 1
    assert all(len(ln) <= 90 for ln in lines)


def test_overlong_word_is_hard_split():
    lines = pdfgen._wrap("x" * 250)
    assert all(len(ln) <= 90 for ln in lines)
    assert "".join(lines) == "x" * 250


def test_deterministic_same_input_same_bytes():
    a = pdfgen.text_pdf("Same", "Input\nover lines")
    b = pdfgen.text_pdf("Same", "Input\nover lines")
    assert a == b


def test_xref_offsets_match_object_positions():
    out = pdfgen.text_pdf("Verify", "offsets")
    # object 1 must actually begin at the offset recorded in the xref table
    idx = out.index(b"xref\n")
    xref_block = out[idx:]
    # first data entry (object 1) is the second line of the xref subsection
    lines = xref_block.split(b"\n")
    # lines: ['xref', '0 6', '0000000000 65535 f ', '<obj1 offset> 00000 n ', ...]
    obj1_off = int(lines[3].split()[0])
    assert out[obj1_off:].startswith(b"1 0 obj")
