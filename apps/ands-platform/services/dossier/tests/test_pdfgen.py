"""pdfgen — dependency-free multi-page PDF writer (pure).

Byte-level conformance tests: header/EOF markers, xref offsets that
really point at their objects, exact stream /Length values, multi-page
pagination with a consistent /Kids array, per-page header/footer text,
the page-1 bold title, and the outline (bookmark) to page 1.
"""

import re

from app import ectd_validation, pdfgen


# ------------------------------------------------------------------ helpers

def _streams(out: bytes) -> list[bytes]:
    """Every PAGE content stream's raw bytes, in document order.

    The PDF/A-1b marker objects (the XMP /Metadata packet and the embedded
    output-profile stream) are also ``stream``s, but they are not page content
    — a page content stream always carries text operators (``BT``). Filter to
    those so page-oriented assertions count pages, not markers.
    """
    return [m.group(1) for m in
            re.finditer(rb"stream\n(.*?)\nendstream", out, re.DOTALL)
            if b"BT" in m.group(1)]


def _pages_object(out: bytes):
    """(kids object numbers, /Count) from the page-tree root."""
    m = re.search(rb"/Type /Pages /Kids \[([^\]]*)\] /Count (\d+)", out)
    assert m, "page-tree root not found"
    kids = [int(k) for k in re.findall(rb"(\d+) 0 R", m.group(1))]
    return kids, int(m.group(2))


def _parse_xref(out: bytes):
    """(xref position, entry count, entry lines) via startxref."""
    tail = out[out.rindex(b"startxref"):].split(b"\n")
    xref_pos = int(tail[1])
    assert out[xref_pos:xref_pos + 5] == b"xref\n"
    lines = out[xref_pos:].split(b"\n")
    start, count = (int(x) for x in lines[1].split())
    assert start == 0
    return xref_pos, count, lines[2:2 + count]


# ------------------------------------------------------- basic conformance

def test_starts_with_pdf_header():
    out = pdfgen.text_pdf("Product Monograph", "Body text.")
    assert out.startswith(b"%PDF-")
    assert out.startswith(b"%PDF-1.4")


def test_has_eof_marker():
    out = pdfgen.text_pdf("T", "B")
    assert out.rstrip().endswith(b"%%EOF")


def test_never_encrypted():
    out = pdfgen.text_pdf("T", "B")
    assert b"/Encrypt" not in out


def test_contains_catalog_pages_and_fonts():
    out = pdfgen.text_pdf("T", "B")
    assert b"/Type /Catalog" in out
    assert b"/Type /Pages" in out
    assert b"/BaseFont /Helvetica" in out
    assert b"/BaseFont /Helvetica-Bold" in out


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


def test_escaping_of_parens_in_title():
    out = pdfgen.text_pdf("Dose (mg) \\ note", "b")
    # raw parens/backslash from the title must be escaped in the stream
    assert b"\\(mg\\)" in out
    assert b"\\\\ note" in out
    # the escaped form is present; the naked "(mg)" only ever appears escaped
    assert b"(mg)" not in out


def test_non_latin1_input_still_renders():
    out = pdfgen.text_pdf("Café ✓", "naïve — em")
    assert out.startswith(b"%PDF-1.4")
    assert out.rstrip().endswith(b"%%EOF")


def test_deterministic_same_input_same_bytes():
    a = pdfgen.text_pdf("Same", "Input\nover lines")
    b = pdfgen.text_pdf("Same", "Input\nover lines")
    assert a == b


# ---------------------------------------------------------------- wrapping

def test_wrap_width_fits_letter_with_one_inch_margins():
    # monospaced-safe: a Courier-like 0.6em advance at body size must
    # keep every full line inside the 612 - 2*72 = 468pt text width
    assert pdfgen._WRAP * 0.6 * pdfgen._BODY_SIZE <= 468


def test_long_body_is_wrapped_not_one_line():
    long = "word " * 200
    lines = pdfgen._wrap(long)
    assert len(lines) > 1
    assert all(len(ln) <= pdfgen._WRAP for ln in lines)


def test_overlong_word_is_hard_split():
    lines = pdfgen._wrap("x" * 250)
    assert all(len(ln) <= pdfgen._WRAP for ln in lines)
    assert "".join(lines) == "x" * 250


def test_blank_lines_preserved():
    lines = pdfgen._wrap("para one\n\npara two")
    assert lines[1] == ""


# -------------------------------------------------------------- pagination

def test_short_body_is_a_single_page():
    out = pdfgen.text_pdf("T", "one short line")
    kids, count = _pages_object(out)
    assert count == 1
    assert len(kids) == 1
    assert out.count(b"/Type /Page /") == 1


def test_200_line_body_spans_multiple_pages():
    body = "\n".join(f"body line {i}" for i in range(200))
    out = pdfgen.text_pdf("Long Document", body)
    kids, count = _pages_object(out)
    assert count > 1
    assert 3 <= count <= 7                      # ~44-47 lines per page
    assert len(kids) == count
    assert out.count(b"/Type /Page /") == count
    # every page object must reference its own content stream
    assert len(_streams(out)) == count
    # no body line lost or duplicated across the page break
    for i in range(200):
        assert out.count(b"(body line %d)" % i) == 1


def test_kids_reference_real_page_objects():
    body = "\n".join(f"l{i}" for i in range(200))
    out = pdfgen.text_pdf("T", body)
    kids, _ = _pages_object(out)
    for num in kids:
        assert re.search(rb"\n%d 0 obj\n<< /Type /Page /" % num, out)


# ---------------------------------------------------------- header/footer

def test_footer_page_n_of_m_in_stream():
    body = "\n".join(f"line {i}" for i in range(200))
    out = pdfgen.text_pdf("T", body)
    _, count = _pages_object(out)
    streams = _streams(out)
    assert b"(Page 1 of %d) Tj" % count in streams[0]
    assert b"(Page %d of %d) Tj" % (count, count) in streams[-1]
    # every page carries exactly one page label
    for i, s in enumerate(streams, start=1):
        assert s.count(b"(Page %d of %d) Tj" % (i, count)) == 1


def test_every_page_has_grey_header_with_title():
    body = "\n".join(f"line {i}" for i in range(200))
    out = pdfgen.text_pdf("Running Header Title", body)
    for s in _streams(out):
        assert b"(Running Header Title) Tj" in s
        assert b"0.5 g" in s                    # grey header/footer
        assert b"/F1 8 Tf" in s                 # smaller meta text


def test_generated_on_date_in_footer_when_given():
    out = pdfgen.text_pdf("T", "B", generated_on="2026-07-02")
    assert b"(Generated: 2026-07-02) Tj" in out


def test_generated_on_absent_by_default():
    out = pdfgen.text_pdf("T", "B")
    assert b"Generated:" not in out


def test_generated_on_stamps_every_page():
    body = "\n".join(f"line {i}" for i in range(200))
    out = pdfgen.text_pdf("T", body, generated_on="2026-07-02")
    for s in _streams(out):
        assert b"(Generated: 2026-07-02) Tj" in s


# ------------------------------------------------------------ page-1 title

def test_bold_title_on_first_page_only():
    body = "\n".join(f"line {i}" for i in range(200))
    out = pdfgen.text_pdf("Bold Title Here", body)
    streams = _streams(out)
    assert b"/F2 18 Tf" in streams[0]           # Helvetica-Bold, larger
    for s in streams[1:]:
        assert b"/F2 18 Tf" not in s


def test_body_uses_helvetica_at_14pt_leading():
    out = pdfgen.text_pdf("Hello", "World")
    assert b"14 TL" in out
    assert b"/F1 11 Tf" in out


def test_content_operators_present():
    out = pdfgen.text_pdf("Hello", "World")
    for op in (b"BT", b"ET", b"Tf", b"Tj", b"T*", b" Tm"):
        assert op in out


# ----------------------------------------------------------------- outline

def test_outline_bookmark_to_page_one():
    out = pdfgen.text_pdf("Bookmarked Doc", "body")
    assert b"/Outlines" in out
    assert b"/Type /Outlines" in out
    m = re.search(rb"<< /Title \((.*?)\) /Parent \d+ 0 R "
                  rb"/Dest \[(\d+) 0 R /Fit\] >>", out, re.DOTALL)
    assert m, "outline item with a /Dest not found"
    assert m.group(1) == b"Bookmarked Doc"
    kids, _ = _pages_object(out)
    assert int(m.group(2)) == kids[0]           # dest is page 1


# ----------------------------------------------------- xref / stream sizes

def test_xref_offsets_match_object_positions():
    body = "\n".join(f"line {i}" for i in range(200))
    out = pdfgen.text_pdf("Verify", body)
    xref_pos, count, entries = _parse_xref(out)
    assert entries[0].startswith(b"0000000000 65535 f")
    for i, entry in enumerate(entries[1:], start=1):
        off = int(entry.split()[0])
        assert out[off:].startswith(b"%d 0 obj" % i)
    m = re.search(rb"/Size (\d+)", out)
    assert int(m.group(1)) == count


def test_startxref_points_at_xref_table():
    out = pdfgen.text_pdf("T", "B")
    xref_pos, _, _ = _parse_xref(out)
    assert out[xref_pos:xref_pos + 5] == b"xref\n"


def test_stream_lengths_are_exact():
    body = "\n".join(f"line {i}" for i in range(200))
    out = pdfgen.text_pdf("T", body, generated_on="2026-07-02")
    found = 0
    for m in re.finditer(rb"<< /Length (\d+) >>\nstream\n", out):
        data_start = m.end()
        data_end = out.index(b"\nendstream", data_start)
        assert data_end - data_start == int(m.group(1))
        found += 1
    assert found == len(_streams(out)) > 0


def test_roundtrip_byte_length_over_400():
    out = pdfgen.text_pdf("A reasonably titled document",
                          "A paragraph of body text that says a few things.")
    assert isinstance(out, bytes)
    assert len(out) > 400


# ------------------------------------------------- TIER3-PDFA-GEN markers
# The tool AUTHORS these PDFs, so it must emit the PDF/A-1b STRUCTURAL markers
# the tier-2 checker (ectd_validation._pdfa_check) looks for — an XMP pdfaid
# packet (part 1 / conformance B), a GTS_PDFA1 OutputIntent — on a PDF-1.4 base
# and with NO prohibited constructs. These are real, byte-observable markers;
# they are NOT a claim of full ISO 19005-1 conformance (see ectd_validation).

def _pdfa(out: bytes):
    """Run the tier-2 structural PDF/A check over ``out``; (errors, warnings)."""
    errors: list = []
    warnings: list = []
    ectd_validation._pdfa_check("generated.pdf", out, errors, warnings)
    return errors, warnings


def test_xmp_pdfaid_packet_part1_conformance_b():
    out = pdfgen.text_pdf("T", "B")
    assert b"pdfaid:part" in out
    assert b"pdfaid:conformance" in out
    # part 1 / conformance B (PDF/A-1b) declared in the packet
    assert re.search(rb'pdfaid:part\s*=\s*"1"', out)
    assert re.search(rb'pdfaid:conformance\s*=\s*"B"', out)


def test_gts_pdfa1_outputintent_present():
    out = pdfgen.text_pdf("T", "B")
    assert b"/OutputIntent" in out
    assert b"GTS_PDFA1" in out


def test_generated_pdf_passes_pdfa_check_with_zero_pdfa_warnings():
    # a freshly generated leaf must trip NONE of the PDF/A advisory warnings —
    # the whole point of TIER3-PDFA-GEN (kill the noise the tool created).
    out = pdfgen.text_pdf("Health Canada — Cover Letter", "Body of the letter.")
    errors, warnings = _pdfa(out)
    warn_rules = {w["rule"] for w in warnings}
    for r in ("pdfa_xmp_missing", "pdfa_xmp_part_wrong",
              "pdfa_outputintent_missing", "pdfa_version"):
        assert r not in warn_rules, r
    # and no prohibited-construct errors were introduced by the markers
    err_rules = {e["rule"] for e in errors}
    for r in ("pdfa_javascript", "pdfa_embedded_file", "pdfa_launch_action"):
        assert r not in err_rules, r


def test_markers_introduce_no_prohibited_constructs():
    out = pdfgen.text_pdf("Long", "\n".join(f"line {i}" for i in range(200)))
    # the XMP/OutputIntent additions must not smuggle in any construct the
    # PDF/A prohibited-content regexes (word-boundary anchored) would flag
    assert not re.search(rb"/JavaScript\b|/JS\b", out)
    assert not re.search(rb"/EmbeddedFile\b", out)
    assert not re.search(rb"/Launch\b|/GoToR\b", out)
    assert b"/Encrypt" not in out


def test_pdfa_markers_deterministic():
    a = pdfgen.text_pdf("Same", "Input\nover lines")
    b = pdfgen.text_pdf("Same", "Input\nover lines")
    assert a == b
