"""Adapter parity — Postgres must expose the same surface as SQLite.

The dev deployment runs on the SQLite adapter (ANDS_DB_BACKEND default), so a
method added there but forgotten on the Postgres adapter only fails in
production. This suite pins the three surfaces to each other:

  ports.DossierRepository  ==  SqliteDossierRepository  ==  PostgresDossierRepository

Introspection is class-level on purpose: the Postgres adapter needs a live
server to instantiate, which the sandbox doesn't have. Names and parameter
lists (with defaults) are compared; annotations are not, since the adapters
annotate inconsistently.
"""

import inspect

from app.ports import DossierRepository
from app.repository_postgres import PostgresDossierRepository
from app.repository_sqlite import SqliteDossierRepository


def _surface(cls) -> dict:
    """Public method name -> ordered (param, default) list."""
    return {
        name: [(p.name, p.default) for p in
               inspect.signature(fn).parameters.values()]
        for name, fn in inspect.getmembers(cls, inspect.isfunction)
        if not name.startswith("_")
    }


PORT = _surface(DossierRepository)
SQLITE = _surface(SqliteDossierRepository)
POSTGRES = _surface(PostgresDossierRepository)


def test_postgres_has_every_sqlite_method():
    missing = sorted(set(SQLITE) - set(POSTGRES))
    assert not missing, f"PostgresDossierRepository is missing: {missing}"


def test_sqlite_has_every_postgres_method():
    missing = sorted(set(POSTGRES) - set(SQLITE))
    assert not missing, f"SqliteDossierRepository is missing: {missing}"


def test_port_is_the_full_surface():
    # every adapter method is declared on the port, and vice versa — the
    # Protocol stays the single place to look up the repository contract
    for label, impl in (("sqlite", SQLITE), ("postgres", POSTGRES)):
        undeclared = sorted(set(impl) - set(PORT))
        assert not undeclared, f"{label} methods missing from port: {undeclared}"
        unimplemented = sorted(set(PORT) - set(impl))
        assert not unimplemented, f"{label} does not implement: {unimplemented}"


def test_signatures_match():
    for name in sorted(set(SQLITE) & set(POSTGRES) & set(PORT)):
        assert SQLITE[name] == POSTGRES[name] == PORT[name], (
            f"{name}: parameter lists diverge\n"
            f"  port:     {PORT[name]}\n"
            f"  sqlite:   {SQLITE[name]}\n"
            f"  postgres: {POSTGRES[name]}")
