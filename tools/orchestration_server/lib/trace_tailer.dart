import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'orchestration_paths.dart';
import 'trace_writer.dart';

/// S3 — the smooth-streaming fix. The build runner (`agent_runner.py`) runs
/// OUT OF PROCESS and appends its narration spans directly to the per-feature
/// `otel-traces.jsonl` — so those spans never hit `TraceWriter.events` and the
/// dashboard only saw them via the 1.5s `/traces` poll (the "waits, then dumps a
/// lot at once" feeling). This tailer watches that file from a byte offset and
/// pushes each NEW line into the live SSE broadcast, so out-of-process spans
/// stream continuously. Spans the server itself wrote (already broadcast by
/// `TraceWriter.append`) are skipped via `TraceWriter.pushedByServer`.
///
/// Offset-based + last-complete-newline only, so a half-written line at EOF is
/// re-read on the next pump rather than dropped or pushed malformed.
class TraceTailer {
  TraceTailer(this.repoRoot, this.featureId,
      {this.poll = const Duration(milliseconds: 250)});

  final String repoRoot;
  final String featureId;
  final Duration poll;

  int _offset = 0;
  Timer? _timer;
  bool _started = false;

  String get _path =>
      OrchestrationPaths(repoRoot).featureOtelTracesFile(featureId);

  /// Begin tailing. Starts at the current EOF so only NEW appends are pushed
  /// (the backfill on SSE connect already replays the existing spans).
  void start() {
    if (_started) return;
    _started = true;
    final f = File(_path);
    _offset = f.existsSync() ? f.lengthSync() : 0;
    _timer = Timer.periodic(poll, (_) => pumpOnce());
  }

  void stop() {
    _timer?.cancel();
    _timer = null;
    _started = false;
  }

  /// Read bytes appended since the last pump, push each complete, non-server span
  /// to the live broadcast. Returns how many spans it pushed (exposed for tests).
  int pumpOnce() {
    final f = File(_path);
    if (!f.existsSync()) return 0;
    final len = f.lengthSync();
    if (len < _offset) _offset = 0; // file truncated/rotated → restart
    if (len <= _offset) return 0;

    final raf = f.openSync(mode: FileMode.read);
    var pushed = 0;
    try {
      raf.setPositionSync(_offset);
      final bytes = raf.readSync(len - _offset);
      // Only consume up to the last newline; leave any partial trailing line for
      // the next pump so we never parse/push a half-written record.
      final lastNl = bytes.lastIndexOf(0x0a);
      if (lastNl < 0) return 0; // no complete line yet
      final complete = bytes.sublist(0, lastNl + 1);
      _offset += complete.length;
      for (final line in const LineSplitter().convert(utf8.decode(complete))) {
        if (line.trim().isEmpty) continue;
        try {
          final rec = jsonDecode(line) as Map<String, dynamic>;
          final spanId = rec['span_id'] as String? ?? '';
          if (TraceWriter.pushedByServer(spanId)) continue; // server already broadcast it
          TraceWriter.pushLive(rec);
          pushed++;
        } catch (_) {/* malformed line — skip */}
      }
    } finally {
      raf.closeSync();
    }
    return pushed;
  }

  // ---- per-feature refcounted registry (one tailer per feature, shared by all
  // SSE clients of that feature) ------------------------------------------------
  static final Map<String, TraceTailer> _active = {};
  static final Map<String, int> _refs = {};

  /// Ensure a tailer is running for [featureId] (starts one on the first SSE
  /// client). Call [release] when a client disconnects.
  static void subscribe(String repoRoot, String featureId) {
    _refs[featureId] = (_refs[featureId] ?? 0) + 1;
    _active[featureId] ??= TraceTailer(repoRoot, featureId)..start();
  }

  static void release(String featureId) {
    final n = (_refs[featureId] ?? 1) - 1;
    if (n <= 0) {
      _refs.remove(featureId);
      _active.remove(featureId)?.stop();
    } else {
      _refs[featureId] = n;
    }
  }
}
