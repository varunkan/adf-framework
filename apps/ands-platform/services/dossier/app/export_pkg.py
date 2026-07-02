"""eCTD sequence export — the transmissible package (pure zip builder).

Produces the folder tree a sponsor actually uploads through CESG WebTrader:

    <dossier_id>/<seq>/index.xml            eCTD backbone for the sequence
    <dossier_id>/<seq>/index-md5.txt        md5 of index.xml (3.2.2 convention)
    <dossier_id>/<seq>/rt.xml               REP Regulatory Transaction XML —
                                            REP guidance: the RT template
                                            travels INSIDE every transaction
    <dossier_id>/<seq>/m1/ca/ca-regional.xml
    <dossier_id>/<seq>/<leaf href>          every live leaf of the sequence,
                                            bytes verbatim from the store

The builder is pure: callers supply the dossier model, the target sequence,
a ``leaf_id -> bytes`` resolver, and the REP RT XML bytes. Missing leaf bytes
are reported, not silently skipped — an incomplete package must be visible.
"""

from __future__ import annotations

import io
import zipfile

from . import assembly


def sequence_leaves(model: dict, sequence: str) -> list[dict]:
    """Live leaves that belong to ``sequence`` (an eCTD sequence folder holds
    only that transaction's files)."""
    seq = str(sequence or "").strip() or "0000"
    view = assembly.current_view(model)
    return [lf for lf in view["live"] if lf.get("sequence") == seq]


def build_package(model: dict, sequence: str, resolve_bytes, rt_xml: bytes,
                  *, ca_regional_extra: dict | None = None) -> dict:
    """Build the zip. ``resolve_bytes(leaf_id) -> bytes | None``.

    Returns {filename, content_type, body, files[], missing[]}."""
    dossier_id = str(model.get("dossier_id") or "").strip()
    seq = str(sequence or "").strip() or "0000"
    outline = assembly.build_outline_view(model, seq)
    index_xml = outline["backbone"]["index.xml"].encode("utf-8")
    ca_xml = outline["backbone"]["ca-regional.xml"].encode("utf-8")

    root = f"{dossier_id}/{seq}"
    files: list[dict] = []
    missing: list[dict] = []
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        def put(path: str, data: bytes) -> None:
            z.writestr(path, data)
            files.append({"path": path, "size": len(data),
                          "md5": assembly.md5_hex(data)})

        put(f"{root}/index.xml", index_xml)
        put(f"{root}/index-md5.txt",
            (assembly.md5_hex(index_xml) + "\n").encode("ascii"))
        put(f"{root}/rt.xml", rt_xml)
        put(f"{root}/m1/ca/ca-regional.xml", ca_xml)
        for lf in sequence_leaves(model, seq):
            body = resolve_bytes(lf["leaf_id"])
            if body is None:
                missing.append({"leaf_id": lf["leaf_id"], "href": lf["href"]})
                continue
            put(f"{root}/{lf['href']}", body)

    return {"filename": f"{dossier_id}-seq-{seq}-ectd.zip",
            "content_type": "application/zip",
            "body": buf.getvalue(), "files": files, "missing": missing}
