"""eCTD sequence export — the transmissible package (pure zip builder).

Produces the folder tree a sponsor actually uploads through CESG WebTrader,
as a genuine ICH eCTD 3.2.2 / CA Module 1 v2.2 sequence:

    <dossier_id>/<seq>/index.xml            ICH eCTD 3.2.2 backbone —
                                            <ectd:ectd> root, DOCTYPE →
                                            util/dtd/ich-ectd-3-2.dtd, one
                                            <leaf> per operation OF THIS
                                            SEQUENCE (operation + checksum +
                                            xlink:href + modified-file back-
                                            pointer for replace/append/delete)
    <dossier_id>/<seq>/index-md5.txt        md5 of index.xml (3.2.2 convention)
    <dossier_id>/<seq>/rt.xml               REP Regulatory Transaction XML —
                                            REP guidance: the RT template
                                            travels INSIDE every transaction
    <dossier_id>/<seq>/util/dtd/*.dtd       the HC util set, so both DOCTYPEs
                                            resolve offline
    <dossier_id>/<seq>/m1/ca/ca-regional.xml
                                            CA Module 1 v2.2 <ca:ectd-ca>
                                            regional backbone
    <dossier_id>/<seq>/<leaf href>          every leaf SUBMITTED IN this
                                            sequence, bytes verbatim

Because the backbone lists only the sequence's own leaves, its hrefs never
dangle: sequence 0001 references 0001's replaced/appended leaves (plus a
``../0000/…`` modified-file back-pointer), not the whole cumulative view.

The builder is pure: callers supply the dossier model, the target sequence,
a ``leaf_id -> bytes`` resolver, and the REP RT XML bytes. Missing leaf bytes
are reported, not silently skipped — an incomplete package must be visible.
"""

from __future__ import annotations

import io
import zipfile

from . import assembly


def sequence_leaves(model: dict, sequence: str) -> list[dict]:
    """Leaves *submitted in* ``sequence`` — this transaction's own operations
    (a sequence folder holds only that sequence's files, so a replace lands as
    the sole leaf of the later sequence, not the whole cumulative view)."""
    seq = str(sequence or "").strip() or "0000"
    return assembly.sequence_leaves(model, seq)


def build_package(model: dict, sequence: str, resolve_bytes, rt_xml: bytes,
                  *, ca_regional_extra: dict | None = None) -> dict:
    """Build the zip. ``resolve_bytes(leaf_id) -> bytes | None``.

    Returns {filename, content_type, body, files[], missing[]}. ``missing`` is
    truly empty for a complete, valid sequence (every leaf's bytes resolved)."""
    dossier_id = str(model.get("dossier_id") or "").strip()
    seq = str(sequence or "").strip() or "0000"
    backbone = assembly.build_sequence_backbone(model, seq,
                                                extra=ca_regional_extra)
    index_xml = backbone["index_xml"].encode("utf-8")
    ca_xml = backbone["ca_regional_xml"].encode("utf-8")

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
        # the HC util set (DTDs) so both DOCTYPEs resolve inside the sequence
        for rel_path, text in backbone["util_files"].items():
            put(f"{root}/{rel_path}", text.encode("utf-8"))
        put(f"{root}/m1/ca/ca-regional.xml", ca_xml)
        for lf in sequence_leaves(model, seq):
            if assembly._s(lf.get("operation")) == "delete":
                # a delete carries no bytes — it only retires a prior leaf
                continue
            body = resolve_bytes(lf["leaf_id"])
            if body is None:
                missing.append({"leaf_id": lf["leaf_id"], "href": lf["href"]})
                continue
            put(f"{root}/{lf['href']}", body)

    return {"filename": f"{dossier_id}-seq-{seq}-ectd.zip",
            "content_type": "application/zip",
            "body": buf.getvalue(), "files": files, "missing": missing}
