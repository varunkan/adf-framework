"""Minimal, dependency-free single-page PDF writer (pure, stdlib only).

So generated dossier documents are *real* PDFs (``application/pdf``) rather than
``text/plain``. ``text_pdf`` emits a valid PDF-1.4 file: Catalog, Pages, one
Letter page (612x792), a Helvetica Type1 font, and a content stream that draws
the title (larger) followed by the body wrapped to ~90 chars/line at 14pt
leading. Deterministic: no network, no wall-clock, no randomness — the same
``(title, body)`` always yields byte-identical output.
"""

from __future__ import annotations

_PAGE_WIDTH = 612
_PAGE_HEIGHT = 792
_LEFT_MARGIN = 72
_TOP = 720
_LEADING = 14
_WRAP = 90
_TITLE_SIZE = 18
_BODY_SIZE = 11
# how many body lines fit under the title before the bottom margin (~72pt)
_MAX_BODY_LINES = int((_TOP - _TITLE_SIZE - 72) / _LEADING)


def _s(v) -> str:
    return str(v if v is not None else "")


def _escape(text: str) -> str:
    """Escape the three PDF string metacharacters: backslash, ( and )."""
    return (_s(text).replace("\\", "\\\\")
            .replace("(", "\\(").replace(")", "\\)"))


def _wrap(text: str, width: int = _WRAP) -> list[str]:
    """Wrap on whitespace to ``width`` chars, hard-splitting overlong words.

    Empty input yields no lines; blank lines in the body are preserved.
    """
    lines: list[str] = []
    for raw in _s(text).replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if not raw.strip():
            lines.append("")
            continue
        cur = ""
        for word in raw.split():
            while len(word) > width:            # hard-split an overlong token
                if cur:
                    lines.append(cur)
                    cur = ""
                lines.append(word[:width])
                word = word[width:]
            if not cur:
                cur = word
            elif len(cur) + 1 + len(word) <= width:
                cur += " " + word
            else:
                lines.append(cur)
                cur = word
        lines.append(cur)
    return lines


def _content_stream(title: str, body: str) -> bytes:
    """The page content stream: title (larger), then wrapped body lines."""
    body_lines = _wrap(body)[:_MAX_BODY_LINES]
    parts = ["BT", f"1 0 0 1 {_LEFT_MARGIN} {_TOP} Tm", f"{_LEADING} TL"]
    parts.append(f"/F1 {_TITLE_SIZE} Tf")
    parts.append(f"({_escape(title)}) Tj")
    parts.append("T*")
    parts.append("T*")                          # gap under the title
    parts.append(f"/F1 {_BODY_SIZE} Tf")
    for line in body_lines:
        parts.append(f"({_escape(line)}) Tj")
        parts.append("T*")
    parts.append("ET")
    return ("\n".join(parts) + "\n").encode("latin-1", "replace")


def text_pdf(title: str, body: str) -> bytes:
    """Render ``title`` + ``body`` as a valid single-page PDF-1.4 (bytes)."""
    stream = _content_stream(title, body)
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] "
         b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
         % (_PAGE_WIDTH, _PAGE_HEIGHT)),
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"endstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")   # binary comment marker
    offsets: list[int] = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + obj + b"\nendobj\n"

    xref_pos = len(out)
    n = len(objects) + 1                        # +1 for the free object 0
    out += b"xref\n"
    out += b"0 %d\n" % n
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n"
    out += b"<< /Size %d /Root 1 0 R >>\n" % n
    out += b"startxref\n%d\n" % xref_pos
    out += b"%%EOF"
    return bytes(out)
