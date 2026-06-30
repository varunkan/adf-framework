"""Cross-service integration harness — many services on ONE in-memory bus.

Each service ships its code under a top-level ``app`` package, so they collide
if naively imported together. ``_load`` imports one service's modules, captures
the classes we need, then purges ``app*`` from ``sys.modules`` before the next —
the captured classes keep working via their live module references. This lets us
wire the real services onto a single shared :class:`InMemoryEventBus` and prove
the event mesh end-to-end in one process (what Redis/compose does in prod).
"""

import importlib
import os
import sys
from types import SimpleNamespace

import pytest

from ands_shared import InMemoryEventBus, SqliteDb

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _purge_app():
    for mod in [k for k in sys.modules if k == "app" or k.startswith("app.")]:
        del sys.modules[mod]


def _load(service: str, modnames):
    svc_dir = os.path.join(_BASE, "services", service)
    _purge_app()
    sys.path.insert(0, svc_dir)
    try:
        out = {n: importlib.import_module(n) for n in modnames}
    finally:
        sys.path.remove(svc_dir)
    _purge_app()
    return out


def _mem(repo_cls):
    return repo_cls(SqliteDb(":memory:"))


@pytest.fixture
def mesh():
    bus = InMemoryEventBus()

    v = _load("validation", ["app.service", "app.repository_sqlite"])
    validation = v["app.service"].ValidationService(
        _mem(v["app.repository_sqlite"].SqliteValidationRepository), bus).register()

    t = _load("transmission", ["app.service", "app.repository_sqlite"])
    transmission = t["app.service"].TransmissionService(
        _mem(t["app.repository_sqlite"].SqliteTransmissionRepository),
        bus).register()

    c = _load("collaboration", ["app.service", "app.repository_sqlite"])
    collaboration = c["app.service"].CollaborationService(
        _mem(c["app.repository_sqlite"].SqliteCollaborationRepository),
        bus).register()

    r = _load("readiness", ["app.service", "app.repository_sqlite"])
    readiness = r["app.service"].ReadinessService(
        _mem(r["app.repository_sqlite"].SqliteProjectionRepository), bus).register()

    g = _load("governance", ["app.service", "app.repository_sqlite"])
    governance = g["app.service"].GovernanceService(
        _mem(g["app.repository_sqlite"].SqliteAuditRepository), bus).register()

    i = _load("identity", ["app.service", "app.repository_sqlite"])
    identity = i["app.service"].IdentityService(
        _mem(i["app.repository_sqlite"].SqliteIdentityRepository), bus).register()

    d = _load("dossier", ["app.service", "app.repository_sqlite"])
    dossier = d["app.service"].DossierService(
        _mem(d["app.repository_sqlite"].SqliteDossierRepository), bus).register()

    lc = _load("lifecycle", ["app.service", "app.repository_sqlite"])
    lifecycle = lc["app.service"].LifecycleService(
        _mem(lc["app.repository_sqlite"].SqliteLifecycleRepository),
        bus).register()

    rg = _load("registry", ["app.service", "app.repository_sqlite"])
    registry = rg["app.service"].RegistryService(
        _mem(rg["app.repository_sqlite"].SqliteRegistrationRepository),
        bus).register()

    f = _load("fees", ["app.service"])
    fees = f["app.service"].FeesService()   # stateless — no repo/bus

    return SimpleNamespace(bus=bus, validation=validation,
                           transmission=transmission, collaboration=collaboration,
                           readiness=readiness, governance=governance,
                           identity=identity, dossier=dossier,
                           lifecycle=lifecycle, registry=registry, fees=fees)
