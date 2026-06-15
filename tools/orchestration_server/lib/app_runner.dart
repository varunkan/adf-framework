import 'dart:async';
import 'dart:convert';
import 'dart:io';

/// Runs a built app (`apps/<id>/server.py`) on an allocated localhost port so the
/// dashboard can render the REAL, running app inline (the Lovable/Emergent feel)
/// — not just spec text or a code excerpt.
///
/// Apps are iframed DIRECTLY at `http://127.0.0.1:<port>/`. That origin is the
/// app's own server, so the app's `fetch('/api/...')` calls hit its own backend
/// with zero CORS/proxy gymnastics (a sub-path proxy would break root-absolute
/// API paths). Lazy-starts on first request, restarts on rebuild, reaps on exit.
class AppRunner {
  AppRunner(this.repoRoot);

  final String repoRoot;
  final Map<String, _AppProc> _procs = {};

  String _appDir(String id) => '$repoRoot/apps/$id';

  /// How to build+run an app, from its `.adf-stack.json` manifest (contract C1).
  /// Falls back to the legacy stdlib `python3 server.py` when only that exists.
  /// No language guessing — the manifest is authoritative.
  Map<String, dynamic>? resolveStack(String id) {
    final manifest = File('${_appDir(id)}/.adf-stack.json');
    if (manifest.existsSync()) {
      try {
        final m = jsonDecode(manifest.readAsStringSync()) as Map<String, dynamic>;
        final run = (m['run_cmd'] as List?)?.cast<String>();
        if (run != null && run.isNotEmpty) {
          return {
            'stack': m['stack'] ?? 'unknown',
            'run_cmd': run,
            'build_cmd': (m['build_cmd'] as List?)?.cast<String>(),
            'post_build': (m['post_build'] as List?)?.cast<String>(),
            'port_env': m['port_env'] as String? ?? 'PORT',
          };
        }
      } catch (_) {}
    }
    if (File('${_appDir(id)}/server.py').existsSync()) {
      return {
        'stack': 'stdlib',
        'run_cmd': const ['python3', 'server.py'],
        'build_cmd': null,
        'post_build': null,
        'port_env': 'PORT',
      };
    }
    return null;
  }

  bool hasApp(String id) => resolveStack(id) != null;

  /// Run a shell-free command in the app dir; returns {ok, out}.
  Future<Map<String, Object>> _run(List<String> cmd, String id) async {
    try {
      final r = await Process.run(
        cmd.first,
        cmd.sublist(1),
        workingDirectory: _appDir(id),
        environment: Platform.environment,
      );
      return {'ok': r.exitCode == 0, 'out': '${r.stdout}\n${r.stderr}'.trim()};
    } catch (e) {
      return {'ok': false, 'out': 'could not run ${cmd.join(' ')}: $e'};
    }
  }

  /// Install deps ONCE (marker file) and rebuild the bundle EVERY start (cheap),
  /// so the preview always reflects the latest code. Returns an error payload on
  /// failure, or null on success.
  Future<Map<String, dynamic>?> _build(String id, Map<String, dynamic> stack) async {
    final installed = File('${_appDir(id)}/.adf-deps');
    final buildCmd = stack['build_cmd'] as List<String>?;
    if (buildCmd != null && buildCmd.isNotEmpty && !installed.existsSync()) {
      final r = await _run(buildCmd, id);
      if (r['ok'] != true) {
        return {'available': false, 'status': 'build_failed', 'reason': 'install failed:\n${r['out']}'};
      }
      installed.writeAsStringSync(DateTime.now().toUtc().toIso8601String());
    }
    final postBuild = stack['post_build'] as List<String>?;
    if (postBuild != null && postBuild.isNotEmpty) {
      final r = await _run(postBuild, id);
      if (r['ok'] != true) {
        return {'available': false, 'status': 'build_failed', 'reason': 'build failed:\n${r['out']}'};
      }
    }
    return null;
  }

  Future<int> _freePort() async {
    final s = await ServerSocket.bind(InternetAddress.loopbackIPv4, 0);
    final p = s.port;
    await s.close();
    return p;
  }

  Future<bool> _waitListening(
    int port, {
    Duration timeout = const Duration(seconds: 7),
  }) async {
    final deadline = DateTime.now().add(timeout);
    while (DateTime.now().isBefore(deadline)) {
      try {
        final sock = await Socket.connect(
          InternetAddress.loopbackIPv4,
          port,
          timeout: const Duration(milliseconds: 400),
        );
        sock.destroy();
        return true;
      } catch (_) {
        await Future<void>.delayed(const Duration(milliseconds: 200));
      }
    }
    return false;
  }

  /// Start the app if it isn't already running; return a status payload the
  /// dashboard uses to render (or skip) the live iframe.
  Future<Map<String, dynamic>> ensureRunning(String id) async {
    final stack = resolveStack(id);
    if (stack == null) {
      return {
        'available': false,
        'status': 'no_app',
        'reason': 'No built app yet — finish the build first.',
      };
    }
    final existing = _procs[id];
    if (existing != null && existing.running) {
      return {
        'available': true,
        'status': 'running',
        'url': existing.url,
        'port': existing.port,
        'started_at': existing.startedAt.toUtc().toIso8601String(),
      };
    }
    // Install (once) + rebuild (each start) for stacks that need it (react).
    final buildErr = await _build(id, stack);
    if (buildErr != null) return buildErr;

    final port = await _freePort();
    final runCmd = (stack['run_cmd'] as List).cast<String>();
    final portEnv = stack['port_env'] as String;
    final Process proc;
    try {
      proc = await Process.start(
        runCmd.first,
        runCmd.sublist(1),
        workingDirectory: _appDir(id),
        environment: {...Platform.environment, portEnv: '$port'},
      );
    } catch (e) {
      return {
        'available': false,
        'status': 'spawn_failed',
        'reason': 'Could not launch ${runCmd.join(' ')}: $e',
      };
    }
    final rec = _AppProc(process: proc, port: port);
    _procs[id] = rec;
    // Drain pipes so a chatty server never blocks on a full buffer.
    final logBuf = StringBuffer();
    proc.stdout.listen((d) {}, onError: (_) {});
    proc.stderr.listen(
      (d) {
        if (logBuf.length < 4000) logBuf.write(String.fromCharCodes(d));
      },
      onError: (_) {},
    );
    proc.exitCode.then((_) {
      rec.running = false;
      if (identical(_procs[id], rec)) _procs.remove(id);
    });

    final ok = await _waitListening(port);
    if (!ok) {
      // Either the server crashed or it ignored PORT (older builds hardcoded
      // 8000). Surface a clear reason; a rebuild regenerates a PORT-aware server.
      final alive = rec.running;
      rec.running = false;
      proc.kill(ProcessSignal.sigterm);
      _procs.remove(id);
      return {
        'available': false,
        'status': 'failed_to_start',
        'reason': alive
            ? 'App is running but not on the requested port — the server must '
                'honor the $portEnv env var.'
            : 'App exited on launch. ${logBuf.toString().trim()}',
      };
    }
    return {
      'available': true,
      'status': 'running',
      'url': rec.url,
      'port': port,
      'started_at': rec.startedAt.toUtc().toIso8601String(),
    };
  }

  /// Kill + relaunch — used after a rebuild so the preview shows fresh code.
  Future<Map<String, dynamic>> restart(String id) async {
    await stop(id);
    return ensureRunning(id);
  }

  Future<void> stop(String id) async {
    final p = _procs.remove(id);
    if (p != null) {
      p.running = false;
      p.process.kill(ProcessSignal.sigterm);
    }
  }

  void stopAll() {
    for (final p in _procs.values) {
      p.running = false;
      p.process.kill(ProcessSignal.sigterm);
    }
    _procs.clear();
  }
}

class _AppProc {
  _AppProc({required this.process, required this.port})
      : startedAt = DateTime.now();

  final Process process;
  final int port;
  final DateTime startedAt;
  bool running = true;

  String get url => 'http://127.0.0.1:$port/';
}
