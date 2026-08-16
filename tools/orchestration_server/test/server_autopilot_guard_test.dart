@Timeout(Duration(seconds: 120))
library;

import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:orchestration_server/feature_store.dart';
import 'package:test/test.dart';

/// G05 (AC-6 + AC-7): drives the ACTUAL production seam — the running HTTP server
/// and its `POST /features/<id>/autopilot` route plus the create-time auto-kick
/// (`kickAutopilotBackground`, server.dart:1111), both of which funnel through
/// `runCrewForFeature` and its `crewGate.tryAcquire(id)` guard. This is the
/// teeth-bearing companion to agent_crew_concurrency_test.dart: that file
/// exercises the CrewGate primitive directly; THIS file proves the guard is
/// actually wired into the server seam.
///
/// AC-6 (`main()` group): if `crewGate.tryAcquire(id)` is removed from
/// `runCrewForFeature`, the second concurrent POST no longer returns 409 and that
/// test FAILS (mutation-verified).
///
/// AC-7 (`AC-7 — create-time auto-kick` group): with the create-time auto-kick
/// ENABLED (ORCH_AUTO_AUTOPILOT left at its default), the test creates a feature
/// WITH autopilot:true and, in the SAME `Future.wait`, fires a same-id manual
/// autopilot POST. The server processes create first: `kickAutopilotBackground`
/// schedules the auto-kick, which runs at the microtask checkpoint and claims the
/// crew gate via `runCrewForFeature` BEFORE the queued manual POST is processed.
/// The auto-kick is therefore the gate HOLDER; the racing manual POST sees the
/// marker, `runCrewForFeature` returns the `skipped` sentinel, and the route maps
/// it to 409. A SLOW requirements-crew stub widens the in-flight window so the
/// race is deterministic. The test asserts (a) the manual POST gets 409, (b) the
/// admitted auto-kick run hands off to implement EXACTLY ONCE (phase-6 approval
/// gate set in state.json), and (c) EXACTLY ONE `crew` command is recorded — no
/// duplicate build. Removing `crewGate.tryAcquire` from `runCrewForFeature` makes
/// the manual POST run a duplicate crew body → the 409 flips to 200 and TWO `crew`
/// commands are recorded → the test FAILS (mutation-verified).
///
/// Why this is the right AC-7 target (honesty): `kickAutopilotBackground`'s
/// literal `summary['skipped']==true` early-return (server.dart:628) is reachable
/// only if `runCrewForFeature` returns `skipped` to the auto-kick — i.e. the gate
/// is already held when the auto-kick runs. The `skipped` sentinel and the gate
/// that produces it are the production mechanism AC-7's "no second build / no
/// second enqueue" guarantee depends on; this test exercises that mechanism with
/// the auto-kick as the contended party and asserts the no-duplicate-build
/// outcome directly. The gate guard inside `runCrewForFeature` is the mutation
/// target.
///
/// Boots the real server on an EPHEMERAL port (ORCH_PORT=0) — never a hardcoded
/// port — and reads the actual bound port back from the server's stdout banner.
void main() {
  late String repoRoot;
  late FeatureStore store;
  late Process server;
  late int port;
  final createdIds = <String>[];

  // Resolve the real repo root (walk up to .adf/orchestration).
  String findRepoRoot() {
    var dir = Directory.current.path;
    while (!Directory('$dir/.adf/orchestration').existsSync()) {
      final parent = Directory(dir).parent;
      if (parent.path == dir) throw StateError('repo root not found');
      dir = parent.path;
    }
    return dir;
  }

  setUpAll(() async {
    repoRoot = findRepoRoot();
    store = FeatureStore(repoRoot);
    server = await Process.start(
      'dart',
      ['run', 'bin/server.dart'],
      environment: {
        'ORCH_PORT': '0', // ephemeral — OS picks a free port
        'ORCH_REPO_ROOT': repoRoot,
        'ORCH_AUTO_RUNNER': 'false', // no headless-runner probes
        'ORCH_AUTO_AUTOPILOT': 'false', // create does NOT auto-kick the crew
        // CREW-1: these tests exercise the autopilot in-flight GUARD with the fast
        // deterministic engine; pin the crew off so the server doesn't shell the
        // real (multi-minute) python crew now that it is default-on for M/L/XL.
        'ADF_REQUIREMENTS_CREW': '0',
      },
      workingDirectory: '$repoRoot/tools/orchestration_server',
    );
    // Parse the bound port from the startup banner: "  http://127.0.0.1:<port>".
    final portCompleter = Completer<int>();
    server.stdout.transform(utf8.decoder).transform(const LineSplitter()).listen(
      (line) {
        final m = RegExp(r'http://127\.0\.0\.1:(\d+)').firstMatch(line);
        if (m != null && !portCompleter.isCompleted) {
          portCompleter.complete(int.parse(m.group(1)!));
        }
      },
    );
    // Surface server stderr if the boot fails (helps diagnose a flaky CI box).
    server.stderr.transform(utf8.decoder).listen((_) {});
    port = await portCompleter.future
        .timeout(const Duration(seconds: 60), onTimeout: () {
      throw StateError('server did not print its port within 60s');
    });
  });

  tearDownAll(() async {
    server.kill(ProcessSignal.sigterm);
    await server.exitCode.timeout(const Duration(seconds: 10),
        onTimeout: () => -1);
    for (final id in createdIds) {
      if (store.featureExists(id)) {
        Directory(store.featurePath(id)).deleteSync(recursive: true);
      }
      final specDir = Directory('$repoRoot/specs/$id');
      if (specDir.existsSync()) specDir.deleteSync(recursive: true);
    }
  });

  Future<HttpClientResponse> postJson(String path, Object body) async {
    final client = HttpClient();
    try {
      final req = await client.postUrl(Uri.parse('http://127.0.0.1:$port$path'));
      req.headers.contentType = ContentType.json;
      req.add(utf8.encode(jsonEncode(body)));
      return await req.close();
    } finally {
      client.close(force: false);
    }
  }

  Future<String> createFeature() async {
    final resp = await postJson('/features', {
      'requirement': 'Render a checkout screen. Print a receipt. '
          'Email the receipt to the customer.',
      'track': 'M',
    });
    expect(resp.statusCode, 201, reason: 'feature create should return 201');
    final payload =
        jsonDecode(await resp.transform(utf8.decoder).join()) as Map;
    final id = payload['id'] as String;
    createdIds.add(id);
    return id;
  }

  // AC-6: a second concurrent POST /features/<id>/autopilot while the first
  // crew run is in flight returns HTTP 409 with the exact contract body.
  test('concurrent POST /autopilot → one runs, the second gets HTTP 409',
      () async {
    final id = await createFeature();

    // Fire both POSTs without awaiting between them so they race on the server's
    // event loop. The first handler synchronously claims the gate (tryAcquire
    // runs BEFORE the first await in runCrewForFeature) and holds it across the
    // crew run; the second sees the marker and returns 409.
    final clientA = HttpClient();
    final clientB = HttpClient();
    Future<HttpClientResponse> kick(HttpClient c) async {
      final r = await c
          .postUrl(Uri.parse('http://127.0.0.1:$port/features/$id/autopilot'));
      r.headers.contentType = ContentType.json;
      r.add(utf8.encode('{}'));
      return r.close();
    }

    try {
      final results = await Future.wait([kick(clientA), kick(clientB)]);
      final bodies = await Future.wait(
          results.map((r) => r.transform(utf8.decoder).join()));
      final statuses = results.map((r) => r.statusCode).toList();

      expect(statuses, contains(409),
          reason: 'one of two concurrent autopilot POSTs must be rejected 409 — '
              'if it is not, the crewGate guard is missing from '
              'runCrewForFeature');
      // Exactly one 409 (the other is the admitted run: 200, or a 500 if the
      // deterministic crew body itself errors — but never a second 409).
      expect(statuses.where((s) => s == 409).length, 1,
          reason: 'exactly one concurrent trigger should be rejected');

      // The 409 body matches the documented contract exactly.
      final conflictIdx = statuses.indexOf(409);
      final conflictBody = jsonDecode(bodies[conflictIdx]) as Map;
      expect(conflictBody['error'], 'crew already in flight');
      expect(conflictBody['feature_id'], id);
    } finally {
      clientA.close(force: true);
      clientB.close(force: true);
    }
  });

  // AC-5 (released after completion) + sanity: once the in-flight run has
  // finished, a fresh sequential POST is admitted again (not permanently locked).
  test('a sequential POST /autopilot after completion is admitted (not locked)',
      () async {
    final id = await createFeature();
    final first = await postJson('/features/$id/autopilot', {});
    await first.transform(utf8.decoder).join();
    expect(first.statusCode, anyOf(200, 500),
        reason: 'the single in-flight run is admitted, not 409');

    // Marker released in the finally of runCrewForFeature → a later run is allowed.
    final second = await postJson('/features/$id/autopilot', {});
    final secondBody = await second.transform(utf8.decoder).join();
    expect(second.statusCode, isNot(409),
        reason: 'sequential re-trigger after completion must NOT be locked out: '
            '$secondBody');
  });

  // AC-6 contract: unknown feature id → 404 (the guard is reached only for real
  // features; an unknown id is rejected before the gate).
  test('POST /autopilot for an unknown feature id returns 404', () async {
    final resp =
        await postJson('/features/nope-not-a-real-feature-id/autopilot', {});
    final body = await resp.transform(utf8.decoder).join();
    expect(resp.statusCode, 404, reason: body);
  });

  // AC-7: the create-time auto-kick (kickAutopilotBackground → runCrewForFeature)
  // must not produce a SECOND build when a racing same-id trigger arrives while
  // the auto-kicked crew is in flight. This boots a SEPARATE server with the
  // auto-kick ENABLED (ORCH_AUTO_AUTOPILOT left at default) and a SLOW
  // requirements-crew stub so the in-flight window is wide and deterministic.
  group('AC-7 — create-time auto-kick + concurrent trigger spawns no 2nd build',
      () {
    late String repoRoot7;
    late FeatureStore store7;
    late Process server7;
    late int port7;
    late Directory stubDir;
    late File invocationLog; // one line per crew-stub invocation
    final created7 = <String>[];

    setUpAll(() async {
      repoRoot7 = findRepoRoot();
      store7 = FeatureStore(repoRoot7);

      // A SLOW requirements-crew stub. It records EVERY invocation (so a second
      // crew body is observable as a second 'start' line — the build counter),
      // sleeps to hold the crew gate open across the racing trigger, then exits
      // NON-ZERO. A non-zero exit makes RequirementsCrewRunner.run() return false,
      // so AgentCrew cleanly falls back to its deterministic engine for the spec
      // phase and the run COMPLETES (a zero-exit stub that only wrote a verdict
      // would leave specs/<id>/spec.md missing and BLOCK the crew early, which
      // would release the gate before the racing trigger and defeat the test).
      // argv[1] is the featureId; ADF_REQUIREMENTS_CREW_SCRIPT points the server
      // at this script.
      stubDir = Directory.systemTemp.createTempSync('adf-g05-ac7-stub');
      invocationLog = File('${stubDir.path}/invocations.log');
      invocationLog.writeAsStringSync('');
      final stub = File('${stubDir.path}/slow_crew_stub.py');
      stub.writeAsStringSync('''
import sys, time
log = ${jsonEncode(invocationLog.path)}
fid = sys.argv[1]
with open(log, "a") as f:
    f.write("start " + fid + "\\n")
time.sleep(3.0)  # hold the crew gate open across the racing trigger
# Exit non-zero → run() returns false → crew falls back to the deterministic
# engine (writes spec.md) and completes; the gate stays held for the full run.
sys.exit(1)
''');

      server7 = await Process.start(
        'dart',
        ['run', 'bin/server.dart'],
        environment: {
          'ORCH_PORT': '0',
          'ORCH_REPO_ROOT': repoRoot7,
          'ORCH_AUTO_RUNNER': 'false', // so autoEnqueueImplement sets state, not a real runner
          // ORCH_AUTO_AUTOPILOT deliberately UNSET → defaults ON → create with a
          // prompt auto-kicks kickAutopilotBackground (the seam under test).
          'ORCH_BRAIN': 'deterministic', // force the zero-token deterministic brain
          // — never a live/slow Ollama model (otherwise the in-flight window
          // depends on a network LLM that may or may not be up on a CI box, making
          // the race non-deterministic). The 3s stub below is then the ONLY source
          // of crew latency, so the window is wide AND deterministic.
          'ADF_REQUIREMENTS_CREW': '1',
          'ADF_REQUIREMENTS_CREW_SCRIPT': stub.path,
        },
        workingDirectory: '$repoRoot7/tools/orchestration_server',
      );
      final pc = Completer<int>();
      server7.stdout
          .transform(utf8.decoder)
          .transform(const LineSplitter())
          .listen((line) {
        final m = RegExp(r'http://127\.0\.0\.1:(\d+)').firstMatch(line);
        if (m != null && !pc.isCompleted) pc.complete(int.parse(m.group(1)!));
      });
      server7.stderr.transform(utf8.decoder).listen((_) {});
      port7 = await pc.future.timeout(const Duration(seconds: 60),
          onTimeout: () =>
              throw StateError('AC-7 server did not print its port within 60s'));
    });

    tearDownAll(() async {
      server7.kill(ProcessSignal.sigterm);
      await server7.exitCode
          .timeout(const Duration(seconds: 10), onTimeout: () => -1);
      for (final id in created7) {
        if (store7.featureExists(id)) {
          Directory(store7.featurePath(id)).deleteSync(recursive: true);
        }
        final specDir = Directory('$repoRoot7/specs/$id');
        if (specDir.existsSync()) specDir.deleteSync(recursive: true);
      }
      if (stubDir.existsSync()) stubDir.deleteSync(recursive: true);
    });

    // Build counter that does NOT depend on the requirements stub: every crew
    // run (auto-kicked or manual) appends a `{prompt:'crew'}` command to the
    // feature's commands.jsonl on completion. Counting them is the reliable,
    // stub-independent measure of how many crew bodies actually ran.
    int crewCommandCount(String id) => store7
        .listCommands(id, limit: 100)
        .where((c) => c['prompt'] == 'crew')
        .length;

    int startCount() => invocationLog
        .readAsLinesSync()
        .where((l) => l.startsWith('start '))
        .length;

    // Poster bound to THIS group's server (port7) — the outer postJson closes
    // over the AC-6 server's port.
    Future<HttpClientResponse> postJson7(String path, Object body) async {
      final client = HttpClient();
      try {
        final req =
            await client.postUrl(Uri.parse('http://127.0.0.1:$port7$path'));
        req.headers.contentType = ContentType.json;
        req.add(utf8.encode(jsonEncode(body)));
        return await req.close();
      } finally {
        client.close(force: false);
      }
    }

    Future<void> until(bool Function() cond, Duration budget, String what) async {
      final deadline = DateTime.now().add(budget);
      while (!cond()) {
        if (DateTime.now().isAfter(deadline)) throw StateError('timeout: $what');
        await Future<void>.delayed(const Duration(milliseconds: 50));
      }
    }

    test('auto-kick + racing same-id trigger → exactly ONE build (no duplicate)',
        () async {
      // Pre-create the feature WITHOUT autopilot (autopilot:false → NO auto-kick
      // yet) so we hold a known id and can fire the auto-kick path explicitly.
      const id = 'g05-ac7-autokick-race';
      created7.add(id);
      if (store7.featureExists(id)) {
        Directory(store7.featurePath(id)).deleteSync(recursive: true);
      }

      // Drive the REAL create-time auto-kick: create WITH autopilot:true and an
      // explicit id, and — without awaiting create's response — fire a same-id
      // manual autopilot POST concurrently (Future.wait). Both client connections
      // are queued before either crew body monopolizes the server's single event
      // loop. The server processes create FIRST: createFeature(sync) then
      // kickAutopilotBackground schedules the auto-kick microtask, which runs at
      // the microtask checkpoint (BEFORE the queued manual POST is processed) and
      // synchronously claims the crew gate via runCrewForFeature.tryAcquire,
      // holding it across the crew run (widened by the 3s requirements stub). When
      // the server then processes the manual POST, runCrewForFeature sees the gate
      // held and returns the `skipped` sentinel → the route maps it to 409. That
      // sentinel is EXACTLY the value kickAutopilotBackground keys its no-op on
      // (server.dart:628): the auto-kick is the gate HOLDER here, so this exercises
      // the auto-kick seam end to end and proves the guard AC-7 depends on.
      final results = await Future.wait([
        postJson7('/features', {
          'id': id,
          'requirement': 'Render a checkout screen. Print a receipt. '
              'Email the receipt to the customer.',
          'track': 'M',
          'autopilot': true,
        }),
        postJson7('/features/$id/autopilot', {}),
      ]);
      final bodies = await Future.wait(
          results.map((r) => r.transform(utf8.decoder).join()));
      final createStatus = results[0].statusCode;
      final manualStatus = results[1].statusCode;
      expect(createStatus, anyOf(200, 201),
          reason: 'create (autopilot) should succeed: ${bodies[0]}');

      // The racing manual trigger is rejected 409 (the auto-kick held the gate);
      // its body matches the documented contract exactly.
      expect(manualStatus, 409,
          reason: 'the same-id manual trigger racing the create-time auto-kick '
              'must be rejected 409 — if not, the gate is missing from '
              'runCrewForFeature and a duplicate build was spawned. '
              'manualBody=${bodies[1]}');
      final conflict = jsonDecode(bodies[1]) as Map;
      expect(conflict['error'], 'crew already in flight');
      expect(conflict['feature_id'], id);

      // The auto-kicked run hands off to implement (with ORCH_AUTO_RUNNER=false
      // this sets the phase-6 approval gate in state.json — the observable handoff
      // kickAutopilotBackground performs via autoEnqueueImplement). It must happen
      // EXACTLY ONCE; the rejected trigger contributes no second handoff.
      await until(() {
        final st = store7.readState(id);
        return st['pending_approval_phase'] == 6 || st['awaiting_user'] == true;
      }, const Duration(seconds: 30), 'auto-kick never handed off to implement');
      // Settle margin: any erroneously-admitted second build would have appended
      // its `crew` command (and started its stub) by now.
      await Future<void>.delayed(const Duration(seconds: 1));

      // TEETH (AC-7): exactly ONE crew body ran and handed off ONCE. The rejected
      // trigger produced NO second build / NO second implement handoff. Removing
      // crewGate.tryAcquire from runCrewForFeature lets the manual trigger run a
      // duplicate crew body → 2 `crew` commands (and the 409 above flips to 200) →
      // this test FAILS. This is the production guard kickAutopilotBackground's
      // skip-no-op relies on, and that the autopilot route maps to 409.
      expect(crewCommandCount(id), 1,
          reason: 'exactly one crew body must run under a same-id race; a second '
              '`crew` command means the gate did not prevent the duplicate build '
              '(the corruption AC-7 / the gate exist to stop). '
              'startCount(stub)=${startCount()}');
    });
  });
}
