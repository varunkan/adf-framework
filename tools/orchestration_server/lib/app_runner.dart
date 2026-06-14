import 'dart:async';
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

  bool hasApp(String id) => File('${_appDir(id)}/server.py').existsSync();

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
    if (!hasApp(id)) {
      return {
        'available': false,
        'status': 'no_app',
        'reason': 'No built app yet — finish the build (apps/$id/server.py).',
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
    final port = await _freePort();
    final Process proc;
    try {
      proc = await Process.start(
        'python3',
        ['server.py'],
        workingDirectory: _appDir(id),
        environment: {...Platform.environment, 'PORT': '$port'},
      );
    } catch (e) {
      return {
        'available': false,
        'status': 'spawn_failed',
        'reason': 'Could not launch python3 server.py: $e',
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
            ? 'App server is running but not on the requested port — rebuild so '
                'server.py honors the PORT env var.'
            : 'App server exited on launch. ${logBuf.toString().trim()}',
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
