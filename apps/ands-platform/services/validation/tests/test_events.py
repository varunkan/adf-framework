"""Event emissions — validation.completed always, validation.failed on block.

``validation.failed`` is the event the collaboration service consumes to notify
owners; here we assert it is emitted with the shape that handler needs. The full
cross-service loop is exercised by docker-compose in CI.
"""

from ands_shared import EventType

from tests.conftest import clean_context


def test_clean_run_emits_completed_only(ctx):
    ctx.service.validate({"context": clean_context(), "dossier_id": "e1"})
    assert len(ctx.bus.events_of(EventType.VALIDATION_COMPLETED)) == 1
    assert ctx.bus.events_of(EventType.VALIDATION_FAILED) == []


def test_blocking_run_emits_failed_with_finding_and_recipients(ctx):
    c = clean_context()
    c["files"][0]["encrypted"] = True
    ctx.service.validate({"context": c, "dossier_id": "e1",
                          "notify": ["alice", "bob"]})
    failed = ctx.bus.events_of(EventType.VALIDATION_FAILED)
    assert len(failed) == 1
    assert failed[0].dossier_id == "e1"
    assert failed[0].data["finding"]["rule"] == "A09"
    assert failed[0].data["recipients"] == ["alice", "bob"]


def test_failed_event_payload_satisfies_collaboration_consumer(ctx):
    # A local stand-in for collaboration's on_validation_failed: it needs a
    # finding {rule, message} and recipients. Prove the emitted event supplies
    # exactly that (the contract the consumer depends on).
    seen = []
    ctx.bus.subscribe(EventType.VALIDATION_FAILED,
                      lambda e: seen.append(e.data))
    c = clean_context()
    c["files"][0]["encrypted"] = True
    ctx.service.validate({"context": c, "dossier_id": "e1",
                          "notify": ["qa"]})
    assert seen and seen[0]["finding"].get("rule") and \
        seen[0]["finding"].get("message") and seen[0]["recipients"] == ["qa"]
