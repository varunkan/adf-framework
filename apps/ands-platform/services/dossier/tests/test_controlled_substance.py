"""Controlled-substance CDSA/OCS obligations must be surfaced (swarm gap #19).

A scheduled drug carries Office of Controlled Substances (OCS) obligations under
the Controlled Drugs and Substances Act (CDSA) — dealer's licence, security,
reporting — BEYOND the drug submission. The tool never surfaced this. A dossier
flagged controlled_substance now carries an honest advisory on content_state.
"""

_P = "/api/dossier"


def test_controlled_substance_note_is_surfaced_when_flagged(client):
    client.post(f"{_P}/dossiers", json={"dossier_id": "e930301", "title": "opioid",
                "submission_type": "NDS", "controlled_substance": True})
    st = client.get(f"{_P}/dossiers/e930301/content").json()
    assert st["controlled_substance"] is True
    note = st.get("controlled_substance_note") or ""
    assert "CDSA" in note or "Controlled Drugs and Substances Act" in note
    assert "OCS" in note or "Office of Controlled Substances" in note


def test_no_note_for_a_normal_drug(client):
    client.post(f"{_P}/dossiers", json={"dossier_id": "e930302", "title": "plain",
                "submission_type": "NDS"})
    st = client.get(f"{_P}/dossiers/e930302/content").json()
    assert st["controlled_substance"] is False
    assert st.get("controlled_substance_note") in (None, "")
