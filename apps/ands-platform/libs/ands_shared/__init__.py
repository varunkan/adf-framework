"""ands_shared — the platform shared kernel.

Reusable, framework-light building blocks every ANDS microservice depends on:
domain-event envelope + bus (ports & adapters), a thread-safe SQLite base for
dev/test repositories, RFC 9457 problem+json errors, and a FastAPI app factory
that wires health, request-id and error handling identically across services.

Nothing here knows about a specific bounded context — services import these and
add their own domain/ports/adapters on top (see ADR-0001).
"""

from .appfactory import create_app
from .events import EventEnvelope, EventType
from .eventbus import EventBus, InMemoryEventBus, RedisEventBus
from .ids import new_id, utcnow_iso
from .problem import ProblemError, install_problem_handlers
from .sqlite import SqliteDb

__all__ = [
    "create_app",
    "EventEnvelope",
    "EventType",
    "EventBus",
    "InMemoryEventBus",
    "RedisEventBus",
    "new_id",
    "utcnow_iso",
    "ProblemError",
    "install_problem_handlers",
    "SqliteDb",
]
