import 'dart:convert';
import 'dart:io';

/// Surfaces an app's **context budget** and the `/compact` operation to the
/// dashboard by shelling the canonical engine (`scripts/orch/compaction.py`). The
/// budgeting + fold math lives in ONE tested place (Python) so the server can't
/// drift from what the runner does — it just relays the estimate and applies the
/// fold, which the engine records as a durable `.adf-context/` card.
class Compaction {
  Compaction(this.repoRoot, {this.python = 'python3'});

  final String repoRoot;
  final String python;

  String appDir(String id) => '$repoRoot/apps/$id';
  bool hasApp(String id) => Directory(appDir(id)).existsSync();

  /// `{has_app, tokens, budget, over, n_files}` — what the assembled context costs
  /// now versus the budget. `{has_app:false}` when nothing has been built yet.
  Future<Map<String, dynamic>> estimate(String id, {int? budget}) =>
      _run(id, apply: false, budget: budget);

  /// Apply the fold and write a context card; adds `{card, did_compact,
  /// tokens_after}` to the estimate.
  Future<Map<String, dynamic>> apply(String id, {int? budget}) =>
      _run(id, apply: true, budget: budget);

  Future<Map<String, dynamic>> _run(String id,
      {required bool apply, int? budget}) async {
    if (!hasApp(id)) return {'has_app': false};
    final script = '$repoRoot/scripts/orch/compaction.py';
    if (!File(script).existsSync()) {
      return {'has_app': true, 'error': 'engine not found at $script'};
    }
    final args = <String>[
      script, '--json',
      if (apply) '--apply',
      if (budget != null) ...['--budget', '$budget'],
      appDir(id),
    ];
    try {
      final r = await Process.run(python, args);
      final out = (r.stdout as String).trim();
      if (out.isEmpty) {
        return {
          'has_app': true,
          'error': 'engine produced no output',
          'stderr': (r.stderr as String).trim(),
        };
      }
      return {'has_app': true, ...jsonDecode(out) as Map<String, dynamic>};
    } catch (e) {
      return {'has_app': true, 'error': 'compaction failed: $e'};
    }
  }

  /// Automatic compaction "whenever logically required": compact iff the context
  /// is over budget and the operator hasn't disabled it (`ADF_AUTO_COMPACT=0`).
  /// Returns `{did, ...report}`. Best-effort — callers ignore failures.
  Future<Map<String, dynamic>> autoCompactIfNeeded(String id, {int? budget}) async {
    if ((Platform.environment['ADF_AUTO_COMPACT'] ?? '1') == '0') {
      return {'did': false, 'reason': 'disabled'};
    }
    final est = await estimate(id, budget: budget);
    if (est['over'] != true) {
      return {'did': false, 'reason': 'under_budget', ...est};
    }
    final res = await apply(id, budget: budget);
    return {'did': res['did_compact'] == true, ...res};
  }
}
