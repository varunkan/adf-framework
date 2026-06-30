"""Event bus — port + two adapters (ports & adapters / hexagonal).

``EventBus`` is the port. ``InMemoryEventBus`` is the dev/test adapter: it
dispatches synchronously to in-process subscribers and keeps a published log for
assertions — this is what runs and is tested in the sandbox. ``RedisEventBus``
is the production adapter (Redis Streams); it is import-safe without a live
Redis and only touches the server on first publish/consume.
"""

from __future__ import annotations

from typing import Callable, Protocol

from .events import EventEnvelope

Handler = Callable[[EventEnvelope], None]


class EventBus(Protocol):
    """The bus port every service depends on (never the concrete adapter)."""

    def publish(self, event: EventEnvelope) -> None: ...

    def subscribe(self, event_type: str, handler: Handler) -> None: ...


class InMemoryEventBus:
    """Synchronous, in-process bus for a single service + its tests.

    ``publish`` invokes every handler registered for the event's type right
    away, so a test can publish ``validation.failed`` and immediately assert the
    consumer reacted. ``published`` retains an ordered log of everything sent.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = {}
        self.published: list[EventEnvelope] = []

    def subscribe(self, event_type: str, handler: Handler) -> None:
        """Subscribe to one event type, or to ``"*"`` for every event (the
        wildcard is how the governance/audit service records the whole stream)."""
        self._handlers.setdefault(event_type, []).append(handler)

    def publish(self, event: EventEnvelope) -> None:
        self.published.append(event)
        for handler in list(self._handlers.get(event.type, ())):
            handler(event)
        for handler in list(self._handlers.get("*", ())):
            handler(event)

    # -- test affordance ----------------------------------------------------
    def events_of(self, event_type: str) -> list[EventEnvelope]:
        return [e for e in self.published if e.type == event_type]


class RedisEventBus:
    """Production adapter over Redis Streams (one stream per event type).

    Import-safe without ``redis`` installed or a server reachable; the client is
    created lazily on first use. ``subscribe`` registers a local handler that a
    worker process drains via :meth:`consume` (the API process typically only
    publishes).
    """

    def __init__(self, url: str = "redis://localhost:6379/0",
                 *, group: str = "ands", prefix: str = "events:") -> None:
        self._url = url
        self._group = group
        self._prefix = prefix
        self._client = None
        self._handlers: dict[str, list[Handler]] = {}

    def _redis(self):
        if self._client is None:
            import redis  # lazy: not needed in dev/test
            self._client = redis.Redis.from_url(self._url)
        return self._client

    def _stream(self, event_type: str) -> str:
        return f"{self._prefix}{event_type}"

    def subscribe(self, event_type: str, handler: Handler) -> None:
        self._handlers.setdefault(event_type, []).append(handler)

    def publish(self, event: EventEnvelope) -> None:
        self._redis().xadd(
            self._stream(event.type),
            {"payload": event.model_dump_json()},
        )

    def consume(self, event_type: str, *, block_ms: int = 5000,
                count: int = 10) -> int:
        """Drain pending stream entries to local handlers; returns # handled.

        A worker calls this in a loop. Uses a consumer group so multiple workers
        share the load and acks are tracked.
        """
        client = self._redis()
        stream = self._stream(event_type)
        try:
            client.xgroup_create(stream, self._group, id="0", mkstream=True)
        except Exception:
            pass  # group already exists
        resp = client.xreadgroup(
            self._group, "worker", {stream: ">"}, count=count, block=block_ms)
        handled = 0
        for _stream, entries in resp or []:
            for entry_id, fields in entries:
                payload = fields.get(b"payload") or fields.get("payload")
                if isinstance(payload, bytes):
                    payload = payload.decode("utf-8")
                event = EventEnvelope.model_validate_json(payload)
                for handler in self._handlers.get(event_type, ()):
                    handler(event)
                client.xack(stream, self._group, entry_id)
                handled += 1
        return handled
