"""Event emissions — transmission.sent + transmission.hc_ack (→ collaboration)."""

from ands_shared import EventType


def test_submit_emits_sent(ctx):
    ctx.service.submit({"dossier_id": "e1", "sequence": "0000", "size_gb": 1})
    sent = ctx.bus.events_of(EventType.TRANSMISSION_SENT)
    assert len(sent) == 1 and sent[0].data["sequence"] == "0000"


def test_hc_ack_emits_event_with_core_id_and_recipients(ctx):
    ctx.service.submit({"dossier_id": "e1", "sequence": "0000", "size_gb": 1})
    ctx.service.ack({"dossier_id": "e1", "kind": "fda", "sequence": "0000",
                     "core_id": "CORE-1"})
    ctx.service.ack({"dossier_id": "e1", "kind": "hc", "core_id": "CORE-1",
                     "notify": ["ra"]})
    acked = ctx.bus.events_of(EventType.TRANSMISSION_HC_ACK)
    assert len(acked) == 1
    assert acked[0].data["core_id"] == "CORE-1"
    assert acked[0].data["recipients"] == ["ra"]
