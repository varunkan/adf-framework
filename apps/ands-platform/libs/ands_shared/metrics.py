"""In-process metrics — Prometheus text exposition, stdlib only (SAAS-NFR-006).

A tiny thread-safe registry: a request counter (by method/route/status), a
request-duration sum/count (by method/route) and an in-flight gauge. Every
service mounts ``/metrics`` via the shared app factory, so the whole mesh is
scrapeable with zero per-service wiring and no external dependency.
"""

from __future__ import annotations

import threading


def _labels(pairs: dict) -> str:
    inner = ",".join(f'{k}="{_esc(v)}"' for k, v in pairs.items())
    return "{" + inner + "}" if inner else ""


def _esc(value) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


class Metrics:
    def __init__(self, service: str = "") -> None:
        self.service = service
        self._lock = threading.Lock()
        self._requests: dict = {}       # (method, route, status) -> count
        self._dur_sum: dict = {}        # (method, route) -> seconds
        self._dur_count: dict = {}      # (method, route) -> count
        self._in_flight = 0

    def inc_in_flight(self, delta: int) -> None:
        with self._lock:
            self._in_flight += delta

    def observe_request(self, method: str, route: str, status: int,
                        duration: float) -> None:
        rkey = (method, route, str(status))
        dkey = (method, route)
        with self._lock:
            self._requests[rkey] = self._requests.get(rkey, 0) + 1
            self._dur_sum[dkey] = self._dur_sum.get(dkey, 0.0) + duration
            self._dur_count[dkey] = self._dur_count.get(dkey, 0) + 1

    def render(self) -> str:
        with self._lock:
            requests = dict(self._requests)
            dur_sum = dict(self._dur_sum)
            dur_count = dict(self._dur_count)
            in_flight = self._in_flight
        svc = {"service": self.service} if self.service else {}
        lines = [
            "# HELP http_requests_total Total HTTP requests.",
            "# TYPE http_requests_total counter",
        ]
        for (method, route, status), n in sorted(requests.items()):
            lab = _labels({**svc, "method": method, "route": route,
                           "status": status})
            lines.append(f"http_requests_total{lab} {n}")
        lines += ["# HELP http_request_duration_seconds Request duration.",
                  "# TYPE http_request_duration_seconds summary"]
        for (method, route), total in sorted(dur_sum.items()):
            lab = _labels({**svc, "method": method, "route": route})
            lines.append(f"http_request_duration_seconds_sum{lab} {total:.6f}")
            lines.append(f"http_request_duration_seconds_count{lab} "
                         f"{dur_count[(method, route)]}")
        lines += ["# HELP http_requests_in_flight In-flight requests.",
                  "# TYPE http_requests_in_flight gauge",
                  f"http_requests_in_flight{_labels(svc)} {in_flight}"]
        return "\n".join(lines) + "\n"
