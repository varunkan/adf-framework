#!/usr/bin/env python3
"""ADF audio (ASR) ingest — turn an uploaded voice note / audio file into extracted,
structured requirement text for the crew's Wave-1 ingestion. A spoken requirement is a
user-STATED requirement, so (like an uploaded doc) it is weighted above web research.

Dependency-light + graceful-degrade discipline, mirroring `doc_ingest.py`: a missing
transcriber backend yields a NOTE, never a crash. The TESTED contract in CI is the
DEGRADE path (no backend), not live transcription.

Transcription backends are tried in order (all OPTIONAL):
  1. `ADF_ASR_CMD` env override — a command template with a `{path}` placeholder, e.g.
     `whisper {path} --output_format txt`. Parsed with `shlex.split`, the audio path is
     substituted as a single (quoted) list element and invoked with `shell=False`.
  2. `faster_whisper` (lazy import) if installed.
  3. `whisper` (lazy import) if installed.
  4. None available -> degrade note, text='' (the headline CI case).

Public API (structurally identical to `doc_ingest`'s surface):
  transcribe(path)         -> {kind, text, note}            (text='' + note on degrade)
  ingest(path, complete)   -> {source, kind, requirements, raw, note}

SECURITY: paths are validated for `..` traversal BEFORE any file-read or subprocess
call; all subprocess invocations use `shell=False` with a pre-split command list — the
user-controlled path is NEVER interpolated into a shell string. Only the transcript text
(never the audio bytes) is sent to the model.
"""
import os
import shlex
import subprocess

_ASR_TIMEOUT = 600  # seconds; transcription can be slow, but bounded.


def _path_rejected(path):
    """Return a rejection reason string if the path is unsafe, else None. Rejects
    traversal (`..` components) before any file/subprocess access (R8)."""
    if not path or not isinstance(path, str):
        return "rejected: empty or non-string path"
    # Normalize and look for traversal components in the ORIGINAL (pre-resolve) path so
    # `../../../etc/passwd` is caught before we ever touch the filesystem.
    parts = path.replace("\\", "/").split("/")
    if ".." in parts:
        return "rejected: path traversal ('..') component not allowed"
    return None


def _asr_cmd_transcribe(path):
    """Run the explicit `ADF_ASR_CMD` override (shell=False, path as a quoted list
    element). Returns (text, note). Caught failures fall through to library probes."""
    tmpl = os.environ.get("ADF_ASR_CMD")
    if not tmpl:
        return "", ""
    try:
        # Substitute {path} with a shell-quoted path, then split into a list. Because we
        # quote first and run with shell=False, the path cannot break out into argv.
        cmd = shlex.split(tmpl.replace("{path}", shlex.quote(path)))
        if not cmd:
            return "", ""
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=_ASR_TIMEOUT, shell=False)
        out = (proc.stdout or "").strip()
        if out:
            return out, ""
        return "", "ADF_ASR_CMD produced no transcript"
    except Exception as e:  # noqa: BLE001
        return "", f"ADF_ASR_CMD failed: {e}"


def _faster_whisper_transcribe(path):
    try:
        from faster_whisper import WhisperModel  # noqa: F401
    except Exception:
        return "", ""
    try:
        from faster_whisper import WhisperModel
        model = WhisperModel(os.environ.get("ADF_ASR_MODEL", "base"))
        segments, _info = model.transcribe(path)
        return " ".join(seg.text for seg in segments).strip(), ""
    except Exception as e:  # noqa: BLE001
        return "", f"faster-whisper failed: {e}"


def _whisper_transcribe(path):
    try:
        import whisper  # noqa: F401
    except Exception:
        return "", ""
    try:
        import whisper
        model = whisper.load_model(os.environ.get("ADF_ASR_MODEL", "base"))
        res = model.transcribe(path)
        return (res.get("text") or "").strip(), ""
    except Exception as e:  # noqa: BLE001
        return "", f"whisper failed: {e}"


def transcribe(path):
    """Transcribe an audio file to text (+ a `kind` and a `note` on any degrade).

    Tries ADF_ASR_CMD, then faster-whisper, then whisper; degrades to a note if none are
    available. Never raises."""
    rej = _path_rejected(path)
    if rej:
        return {"kind": "audio", "text": "", "note": rej}
    if not os.path.isfile(path):
        return {"kind": "audio", "text": "", "note": f"missing file: {path}"}

    notes = []
    for fn in (_asr_cmd_transcribe, _faster_whisper_transcribe, _whisper_transcribe):
        try:
            text, note = fn(path)
        except Exception as e:  # noqa: BLE001  (defensive — backends must never crash us)
            text, note = "", f"{fn.__name__} errored: {e}"
        if text:
            return {"kind": "audio", "text": text, "note": ""}
        if note:
            notes.append(note)

    degrade = ("audio ingest needs a local transcriber (faster-whisper/whisper) or an "
               "ADF_ASR_CMD env override — skipped")
    if notes:
        degrade += " [" + "; ".join(notes) + "]"
    return {"kind": "audio", "text": "", "note": degrade}


def ingest(path, complete=None):
    """Ingest an audio file into structured requirement text. With a model `complete`,
    it extracts the explicit requirements; otherwise returns the raw transcript. Always
    returns a dict (with a `note` on degrade) — never crashes the stage.

    Returns the same shape `doc_ingest.ingest` returns:
        {source, kind, requirements, raw, note}
    """
    name = os.path.basename(path) if isinstance(path, str) else str(path)
    try:
        doc = transcribe(path)
    except Exception as e:  # noqa: BLE001
        return {"source": name, "kind": "audio", "requirements": "",
                "raw": "", "note": f"audio ingest failed: {e}"}
    raw = (doc["text"] or "").strip()
    if not raw:
        return {"source": name, "kind": "audio", "requirements": "",
                "raw": "", "note": doc["note"]}
    requirements = raw[:8000]
    if complete is not None:
        try:
            prompt = (
                "This is a user-provided requirements source (a transcribed voice note) "
                "— extract the EXPLICIT requirements, constraints, and acceptance "
                "criteria it states, as terse bullet points (these are AUTHORITATIVE). "
                f"Source: {name}\n\n{raw[:8000]}")
            res = complete(prompt, "extract")
            if res and res[0] and res[0].strip():
                requirements = res[0].strip()
        except Exception:  # noqa: BLE001  (extraction is best-effort; keep the raw text)
            pass
    return {"source": name, "kind": "audio", "requirements": requirements,
            "raw": raw[:8000], "note": doc["note"]}
