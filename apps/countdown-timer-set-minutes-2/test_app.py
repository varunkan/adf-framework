#!/usr/bin/env python3
"""Test suite for the countdown timer (server.py) — standard library only.

Run with:  python3 -m unittest -v

Covers three layers:
  * normalize_duration + the pure Timer domain model (clock-injected, deterministic)
  * the Store persistence layer (against a throwaway temp SQLite file)
  * the HTTP API end-to-end (a real server on an ephemeral port + a fake clock)
"""

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import server
from server import MAX_SECONDS, Store, Timer, TimerError, make_handler, normalize_duration


class FakeClock:
    """A controllable wall-clock: call it to read, set `.t` to advance."""

    def __init__(self, t=1000.0):
        self.t = float(t)

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


# --------------------------------------------------------------------------- #
# normalize_duration                                                          #
# --------------------------------------------------------------------------- #


class NormalizeDurationTests(unittest.TestCase):
    def test_folds_minutes_and_seconds(self):
        self.assertEqual(normalize_duration(2, 30), 150)

    def test_accepts_string_integers(self):
        self.assertEqual(normalize_duration("1", "5"), 65)

    def test_only_seconds(self):
        self.assertEqual(normalize_duration(0, 45), 45)

    def test_only_minutes(self):
        self.assertEqual(normalize_duration(3, 0), 180)

    def test_ceiling_is_accepted(self):
        self.assertEqual(normalize_duration(99, 59), MAX_SECONDS)

    def test_zero_duration_rejected(self):
        with self.assertRaises(TimerError):
            normalize_duration(0, 0)

    def test_negative_rejected(self):
        with self.assertRaises(TimerError):
            normalize_duration(-1, 0)
        with self.assertRaises(TimerError):
            normalize_duration(0, -5)

    def test_seconds_over_59_rejected(self):
        with self.assertRaises(TimerError):
            normalize_duration(0, 60)

    def test_over_ceiling_rejected(self):
        with self.assertRaises(TimerError):
            normalize_duration(100, 0)

    def test_non_integer_rejected(self):
        with self.assertRaises(TimerError):
            normalize_duration("abc", 0)
        with self.assertRaises(TimerError):
            normalize_duration(None, None)


# --------------------------------------------------------------------------- #
# Timer domain model                                                          #
# --------------------------------------------------------------------------- #


class TimerDomainTests(unittest.TestCase):
    def test_new_timer_is_idle_full_remaining(self):
        t = Timer(duration=120)
        self.assertEqual(t.status, "idle")
        self.assertEqual(t.remaining(now=0), 120)
        self.assertEqual(t.effective_status(now=0), "idle")

    def test_set_duration_resets_to_idle(self):
        t = Timer(duration=60)
        t.set_duration(1, 30)
        self.assertEqual(t.duration, 90)
        self.assertEqual(t.remaining(now=0), 90)
        self.assertEqual(t.status, "idle")

    def test_set_duration_validates(self):
        t = Timer(duration=60)
        with self.assertRaises(TimerError):
            t.set_duration(0, 0)

    def test_start_anchors_deadline(self):
        t = Timer(duration=100)
        t.start(now=500.0)
        self.assertEqual(t.status, "running")
        self.assertEqual(t.deadline, 600.0)
        self.assertEqual(t.remaining(now=500.0), 100)

    def test_running_counts_down_with_clock(self):
        t = Timer(duration=100)
        t.start(now=0.0)
        self.assertEqual(t.remaining(now=40.0), 60)
        self.assertEqual(t.remaining(now=99.5), 1)

    def test_start_twice_rejected(self):
        t = Timer(duration=100)
        t.start(now=0.0)
        with self.assertRaises(TimerError):
            t.start(now=10.0)

    def test_pause_freezes_remaining(self):
        t = Timer(duration=100)
        t.start(now=0.0)
        t.pause(now=30.0)
        self.assertEqual(t.status, "paused")
        self.assertEqual(t.remaining(now=999.0), 70)  # clock no longer matters

    def test_pause_when_not_running_rejected(self):
        t = Timer(duration=100)
        with self.assertRaises(TimerError):
            t.pause(now=0.0)

    def test_resume_from_pause(self):
        t = Timer(duration=100)
        t.start(now=0.0)
        t.pause(now=30.0)  # 70 left
        t.start(now=200.0)
        self.assertEqual(t.status, "running")
        self.assertEqual(t.remaining(now=200.0), 70)
        self.assertEqual(t.remaining(now=250.0), 20)

    def test_running_past_deadline_is_finished(self):
        t = Timer(duration=10)
        t.start(now=0.0)
        self.assertEqual(t.effective_status(now=20.0), "finished")
        self.assertEqual(t.remaining(now=20.0), 0)

    def test_reset_returns_to_full_idle(self):
        t = Timer(duration=100)
        t.start(now=0.0)
        t.pause(now=30.0)
        t.reset(now=40.0)
        self.assertEqual(t.status, "idle")
        self.assertEqual(t.remaining(now=999.0), 100)

    def test_start_after_finished_uses_full_duration(self):
        t = Timer(duration=10)
        t.start(now=0.0)
        # elapsed -> finished
        self.assertEqual(t.effective_status(now=50.0), "finished")
        t.start(now=50.0)
        self.assertEqual(t.remaining(now=50.0), 10)

    def test_to_dict_labels(self):
        t = Timer(id=7, name="Tea", duration=125)
        d = t.to_dict(now=0)
        self.assertEqual(d["id"], 7)
        self.assertEqual(d["name"], "Tea")
        self.assertEqual(d["duration"], 125)
        self.assertEqual(d["remaining"], 125)
        self.assertEqual(d["remaining_label"], "02:05")
        self.assertEqual(d["duration_label"], "02:05")
        self.assertEqual(d["status"], "idle")


# --------------------------------------------------------------------------- #
# add_time feature (new)                                                       #
# --------------------------------------------------------------------------- #


class AddTimeTests(unittest.TestCase):
    def test_add_to_idle_grows_remaining(self):
        t = Timer(duration=60)
        t.add_time(0, 30, now=0.0)
        self.assertEqual(t.status, "idle")
        self.assertEqual(t.remaining(now=0.0), 90)

    def test_add_to_paused_grows_remaining(self):
        t = Timer(duration=100)
        t.start(now=0.0)
        t.pause(now=40.0)  # 60 left
        t.add_time(0, 15, now=40.0)
        self.assertEqual(t.status, "paused")
        self.assertEqual(t.remaining(now=999.0), 75)

    def test_add_to_running_pushes_deadline(self):
        t = Timer(duration=100)
        t.start(now=0.0)
        t.add_time(1, 0, now=20.0)  # was 80 left -> 140
        self.assertEqual(t.status, "running")
        self.assertEqual(t.remaining(now=20.0), 140)
        self.assertEqual(t.remaining(now=120.0), 40)

    def test_add_to_finished_restarts_with_delta(self):
        t = Timer(duration=10)
        t.start(now=0.0)  # finishes at 10
        self.assertEqual(t.effective_status(now=50.0), "finished")
        t.add_time(0, 30, now=50.0)
        self.assertEqual(t.effective_status(now=50.0), "running")
        self.assertEqual(t.remaining(now=50.0), 30)

    def test_add_is_capped_at_ceiling(self):
        t = Timer(duration=MAX_SECONDS)
        t.add_time(5, 0, now=0.0)
        self.assertEqual(t.remaining(now=0.0), MAX_SECONDS)

    def test_add_zero_rejected(self):
        t = Timer(duration=60)
        with self.assertRaises(TimerError):
            t.add_time(0, 0, now=0.0)

    def test_add_invalid_seconds_rejected(self):
        t = Timer(duration=60)
        with self.assertRaises(TimerError):
            t.add_time(0, 75, now=0.0)


# --------------------------------------------------------------------------- #
# Store persistence                                                           #
# --------------------------------------------------------------------------- #


class StoreTests(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.unlink(self.path)  # let sqlite create it fresh
        self.store = Store(self.path)

    def tearDown(self):
        for suffix in ("", "-wal", "-shm"):
            try:
                os.unlink(self.path + suffix)
            except OSError:
                pass

    def test_create_and_get(self):
        t = self.store.create("Pasta", 8, 0)
        self.assertIsNotNone(t.id)
        self.assertEqual(t.name, "Pasta")
        self.assertEqual(t.duration, 480)
        again = self.store.get(t.id)
        self.assertEqual(again.name, "Pasta")
        self.assertEqual(again.duration, 480)

    def test_create_validates_duration(self):
        with self.assertRaises(TimerError):
            self.store.create("Bad", 0, 0)

    def test_create_defaults_name(self):
        t = self.store.create("", 1, 0)
        self.assertEqual(t.name, "Timer")

    def test_get_missing_returns_none(self):
        self.assertIsNone(self.store.get(999))

    def test_list_orders_by_id(self):
        a = self.store.create("A", 1, 0)
        b = self.store.create("B", 2, 0)
        ids = [t.id for t in self.store.list()]
        self.assertEqual(ids, [a.id, b.id])

    def test_save_round_trips_running_state(self):
        t = self.store.create("Run", 2, 0)
        t.start(now=1000.0)
        self.store.save(t)
        loaded = self.store.get(t.id)
        self.assertEqual(loaded.status, "running")
        self.assertEqual(loaded.deadline, 1120.0)
        self.assertEqual(loaded.remaining(now=1000.0), 120)

    def test_delete(self):
        t = self.store.create("Gone", 1, 0)
        self.assertTrue(self.store.delete(t.id))
        self.assertIsNone(self.store.get(t.id))
        self.assertFalse(self.store.delete(t.id))


# --------------------------------------------------------------------------- #
# HTTP API end-to-end                                                         #
# --------------------------------------------------------------------------- #


class HttpApiTests(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.unlink(self.path)
        self.store = Store(self.path)
        self.clock = FakeClock(1000.0)
        self.server = ThreadingHTTPServer(
            ("127.0.0.1", 0), make_handler(self.store, clock=self.clock)
        )
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        for suffix in ("", "-wal", "-shm"):
            try:
                os.unlink(self.path + suffix)
            except OSError:
                pass

    # -- helpers ---------------------------------------------------------- #
    def _url(self, path):
        return "http://127.0.0.1:%d%s" % (self.port, path)

    def request(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self._url(path), data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read() or b"null")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"null")

    def create(self, minutes=5, seconds=0, name="Timer"):
        status, body = self.request(
            "POST", "/api/timers", {"name": name, "minutes": minutes, "seconds": seconds}
        )
        self.assertEqual(status, 201)
        return body

    # -- tests ------------------------------------------------------------ #
    def test_index_served(self):
        req = urllib.request.Request(self._url("/"))
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            html = resp.read().decode()
        self.assertIn("Countdown Timer", html)
        self.assertIn("<!DOCTYPE html>", html)

    def test_create_returns_timer(self):
        t = self.create(2, 30, name="Eggs")
        self.assertEqual(t["name"], "Eggs")
        self.assertEqual(t["duration"], 150)
        self.assertEqual(t["remaining_label"], "02:30")
        self.assertEqual(t["status"], "idle")

    def test_create_invalid_returns_400(self):
        status, body = self.request("POST", "/api/timers", {"minutes": 0, "seconds": 0})
        self.assertEqual(status, 400)
        self.assertIn("error", body)

    def test_list_endpoint(self):
        self.create(1, 0)
        self.create(2, 0)
        status, body = self.request("GET", "/api/timers")
        self.assertEqual(status, 200)
        self.assertEqual(len(body), 2)

    def test_get_single(self):
        t = self.create(1, 0)
        status, body = self.request("GET", "/api/timers/%d" % t["id"])
        self.assertEqual(status, 200)
        self.assertEqual(body["id"], t["id"])

    def test_get_missing_404(self):
        status, body = self.request("GET", "/api/timers/9999")
        self.assertEqual(status, 404)

    def test_start_then_clock_counts_down(self):
        t = self.create(2, 0)
        status, body = self.request("POST", "/api/timers/%d/start" % t["id"])
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "running")
        self.clock.advance(30)
        status, body = self.request("GET", "/api/timers/%d" % t["id"])
        self.assertEqual(body["remaining"], 90)

    def test_pause_freezes(self):
        t = self.create(2, 0)
        self.request("POST", "/api/timers/%d/start" % t["id"])
        self.clock.advance(20)
        status, body = self.request("POST", "/api/timers/%d/pause" % t["id"])
        self.assertEqual(body["status"], "paused")
        self.assertEqual(body["remaining"], 100)
        self.clock.advance(500)  # paused: should not move
        status, body = self.request("GET", "/api/timers/%d" % t["id"])
        self.assertEqual(body["remaining"], 100)

    def test_finished_after_deadline(self):
        t = self.create(0, 10)
        self.request("POST", "/api/timers/%d/start" % t["id"])
        self.clock.advance(15)
        status, body = self.request("GET", "/api/timers/%d" % t["id"])
        self.assertEqual(body["status"], "finished")
        self.assertEqual(body["remaining"], 0)

    def test_reset_endpoint(self):
        t = self.create(2, 0)
        self.request("POST", "/api/timers/%d/start" % t["id"])
        self.clock.advance(60)
        status, body = self.request("POST", "/api/timers/%d/reset" % t["id"])
        self.assertEqual(body["status"], "idle")
        self.assertEqual(body["remaining"], 120)

    def test_set_endpoint(self):
        t = self.create(1, 0)
        status, body = self.request(
            "POST", "/api/timers/%d/set" % t["id"], {"minutes": 3, "seconds": 15}
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["duration"], 195)
        self.assertEqual(body["remaining_label"], "03:15")

    def test_add_endpoint_running(self):
        t = self.create(1, 0)
        self.request("POST", "/api/timers/%d/start" % t["id"])
        self.clock.advance(20)  # 40 left
        status, body = self.request(
            "POST", "/api/timers/%d/add" % t["id"], {"minutes": 1, "seconds": 0}
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "running")
        self.assertEqual(body["remaining"], 100)

    def test_add_endpoint_idle(self):
        t = self.create(1, 0)
        status, body = self.request(
            "POST", "/api/timers/%d/add" % t["id"], {"minutes": 0, "seconds": 30}
        )
        self.assertEqual(body["remaining"], 90)

    def test_add_invalid_returns_400(self):
        t = self.create(1, 0)
        status, body = self.request(
            "POST", "/api/timers/%d/add" % t["id"], {"minutes": 0, "seconds": 0}
        )
        self.assertEqual(status, 400)

    def test_unknown_action_404(self):
        t = self.create(1, 0)
        status, body = self.request("POST", "/api/timers/%d/frobnicate" % t["id"])
        self.assertEqual(status, 404)

    def test_action_on_missing_timer_404(self):
        status, body = self.request("POST", "/api/timers/9999/start")
        self.assertEqual(status, 404)

    def test_delete_endpoint(self):
        t = self.create(1, 0)
        status, body = self.request("DELETE", "/api/timers/%d" % t["id"])
        self.assertEqual(status, 200)
        self.assertTrue(body["deleted"])
        status, _ = self.request("GET", "/api/timers/%d" % t["id"])
        self.assertEqual(status, 404)

    def test_delete_missing_404(self):
        status, body = self.request("DELETE", "/api/timers/9999")
        self.assertEqual(status, 404)

    def test_invalid_id_400(self):
        status, body = self.request("GET", "/api/timers/notanint")
        self.assertEqual(status, 400)

    def test_unknown_path_404(self):
        status, body = self.request("GET", "/api/nope")
        self.assertEqual(status, 404)

    def test_full_lifecycle(self):
        t = self.create(0, 50, name="Brew")
        self.request("POST", "/api/timers/%d/start" % t["id"])
        self.clock.advance(10)
        _, body = self.request("POST", "/api/timers/%d/add" % t["id"], {"minutes": 0, "seconds": 20})
        self.assertEqual(body["remaining"], 60)
        _, body = self.request("POST", "/api/timers/%d/pause" % t["id"])
        self.assertEqual(body["status"], "paused")
        _, body = self.request("POST", "/api/timers/%d/start" % t["id"])
        self.assertEqual(body["status"], "running")
        _, body = self.request("POST", "/api/timers/%d/reset" % t["id"])
        self.assertEqual(body["remaining"], 50)


if __name__ == "__main__":
    unittest.main()
