"""Collaboration service — comments, tasks, notifications (REQ-109).

The first ANDS microservice and the pattern other services follow: a pure
``domain`` core, an application ``service`` orchestrating ports, swappable
``repository_*``/event-bus adapters, and a thin FastAPI ``api``. See ADR-0001.
"""
