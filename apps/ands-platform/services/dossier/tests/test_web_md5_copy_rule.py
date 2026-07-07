"""Round-9 validate_export item 16 — the md5 copy-rule LINT (consultant_ex_hc).

The ask: enforce with a real lint check that the md5 checksum is always
labeled "document control" and is NEVER rendered adjacent to the word
"validated" in any validate/export screen or exported report. The web tree has
no test infra, so the dossier service suite (the CI home of the validation
engine) hosts the lint over the validate/export web surfaces.

Rules enforced over the explicit surface list below:
  (a) any file that renders an md5 value/column/label must also carry a
      "document control" label somewhere in the file;
  (b) no single line places the word "validated" together with md5/checksum
      ("not validation" / "NOT validation" phrasing is allowed — the rule
      targets the word "validated" specifically, per the persona ask).
"""
import re
from pathlib import Path

# services/dossier/tests/… → apps/ands-platform
PLATFORM_ROOT = Path(__file__).resolve().parents[3]
WEB = PLATFORM_ROOT / "web"

# The validate/export surfaces owned by this flow (explicit, auditable list).
SURFACES = [
    WEB / "components/dossier/ValidationCard.tsx",
    WEB / "components/dossier/SequencePanel.tsx",
    WEB / "components/dossier/EvalidatorHandoff.tsx",
    WEB / "components/dossier/RuleCatalogue.tsx",
    WEB / "components/dossier/PreflightReport.tsx",
    WEB / "components/dossier/ShadowRun.tsx",
    WEB / "components/dossier/ValidationTour.tsx",
    WEB / "components/dossier/PathToFiling.tsx",
    WEB / "components/dossier/ChipLegend.tsx",
    WEB / "app/dossiers/[dossierId]/viewer/page.tsx",
]

VALIDATED_WORD = re.compile(r"\bvalidated\b", re.IGNORECASE)
CHECKSUM_WORD = re.compile(r"\bmd5\b|\bchecksum", re.IGNORECASE)


def test_surface_list_exists():
    missing = [str(p) for p in SURFACES if not p.is_file()]
    assert not missing, f"validate/export surfaces missing: {missing}"


def test_md5_renders_carry_document_control_label():
    offenders = []
    for p in SURFACES:
        if not p.is_file():
            continue
        text = p.read_text(encoding="utf-8")
        if re.search(r"\bmd5\b", text, re.IGNORECASE):
            if "document control" not in text.lower():
                offenders.append(p.name)
    assert not offenders, (
        "files rendering md5 without a 'document control' label: "
        f"{offenders}")


def test_checksum_never_on_the_same_line_as_validated():
    offenders = []
    for p in SURFACES:
        if not p.is_file():
            continue
        for i, line in enumerate(
                p.read_text(encoding="utf-8").splitlines(), start=1):
            if CHECKSUM_WORD.search(line) and VALIDATED_WORD.search(line):
                offenders.append(f"{p.name}:{i}: {line.strip()[:100]}")
    assert not offenders, (
        "md5/checksum rendered on the same line as 'validated': "
        f"{offenders}")
