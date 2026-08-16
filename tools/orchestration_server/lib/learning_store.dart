import 'dart:convert';
import 'dart:io';

import 'orchestration_paths.dart';

/// Self-evolution memory: every autopilot outcome (success, failure, heal)
/// is appended to `<orchestration>/learnings.jsonl` (`.adf/orchestration` by
/// default; legacy `.adf/orchestration` still resolves). Future runs consult
/// it to avoid repeating past failures — the framework gets measurably better
/// with every feature it builds.
class LearningStore {
  LearningStore(this.repoRoot);

  final String repoRoot;

  // CURSOR-6: follow the resolver instead of hardcoding .adf/orchestration.
  String get path =>
      '${OrchestrationPaths(repoRoot).orchestrationRoot}/learnings.jsonl';

  void record({
    required String featureId,
    required int phase,
    required String kind, // success | failure | heal
    List<String> blockers = const [],
    String? fix,
  }) {
    final entry = {
      'ts': DateTime.now().toUtc().toIso8601String(),
      'feature': featureId,
      'phase': phase,
      'kind': kind,
      if (blockers.isNotEmpty) 'blockers': blockers,
      if (fix != null) 'fix': fix,
    };
    final file = File(path);
    file.parent.createSync(recursive: true);
    file.writeAsStringSync('${jsonEncode(entry)}\n', mode: FileMode.append);
  }

  List<Map<String, dynamic>> all({int limit = 500}) {
    final file = File(path);
    if (!file.existsSync()) return [];
    final out = <Map<String, dynamic>>[];
    for (final line in file.readAsLinesSync()) {
      if (line.trim().isEmpty) continue;
      try {
        out.add(jsonDecode(line) as Map<String, dynamic>);
      } catch (_) {}
    }
    return out.length > limit ? out.sublist(out.length - limit) : out;
  }

  /// Known failure blockers for a phase, most frequent first.
  /// The artifact engine uses these to pre-empt repeat failures.
  List<String> knownBlockers(int phase) {
    final counts = <String, int>{};
    for (final e in all()) {
      if (e['phase'] != phase || e['kind'] != 'failure') continue;
      for (final b in (e['blockers'] as List? ?? [])) {
        final key = b.toString();
        counts[key] = (counts[key] ?? 0) + 1;
      }
    }
    final sorted = counts.entries.toList()
      ..sort((a, b) => b.value.compareTo(a.value));
    return sorted.map((e) => e.key).toList();
  }

  Map<String, dynamic> stats() {
    final entries = all();
    var success = 0, failure = 0, heal = 0;
    for (final e in entries) {
      switch (e['kind']) {
        case 'success':
          success++;
        case 'failure':
          failure++;
        case 'heal':
          heal++;
      }
    }
    final total = success + failure;
    return {
      'entries': entries.length,
      'successes': success,
      'failures': failure,
      'heals': heal,
      'success_rate':
          total == 0 ? 1.0 : double.parse((success / total).toStringAsFixed(3)),
    };
  }
}
