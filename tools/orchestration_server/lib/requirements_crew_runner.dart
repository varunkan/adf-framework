import 'dart:convert';
import 'dart:io';

import 'feature_store.dart';

typedef ProcessRun = Future<ProcessResult> Function(
    String exe, List<String> args, String workingDirectory);

/// Invokes the multi-agent requirements CREW (scripts/orch/requirements_crew.py)
/// for a feature, producing a research-grounded spec + a REAL Product-Owner verdict
/// — replacing the deterministic template engine and the faked reviewers (P2).
///
/// Gated by `ADF_REQUIREMENTS_CREW=1` so behaviour is unchanged when off. The run
/// is only reported successful when a real phase-2 verdict actually landed where the
/// approval gate reads it, so a crashed/empty crew run can NEVER fake a pass.
class RequirementsCrewRunner {
  RequirementsCrewRunner(this.store, {ProcessRun? run})
      : _run = run ?? _defaultRun;

  final FeatureStore store;
  final ProcessRun _run;

  static bool isEnabled([Map<String, String>? env]) =>
      (env ?? Platform.environment)['ADF_REQUIREMENTS_CREW'] == '1';

  /// The crew script to invoke. Overridable via ADF_REQUIREMENTS_CREW_SCRIPT so a
  /// server E2E can point at a fast deterministic stub (the real crew's quality is
  /// proven by the live run; this lets the SERVER path be tested without a ~10min run).
  static String scriptPath([Map<String, String>? env]) =>
      (env ?? Platform.environment)['ADF_REQUIREMENTS_CREW_SCRIPT'] ??
      'scripts/orch/requirements_crew.py';

  /// The path the approval gate reads the PO verdict from.
  String verdictPath(String featureId) =>
      '${store.repoRoot}/${store.paths.featureRel(featureId, 'judge-verdicts/phase-2.md')}';

  /// The multimodal-sources file (links + ingested docs) the crew reads (P4). The
  /// server writes it on feature create from the user's uploads/links.
  String sourcesPath(String featureId) =>
      '${store.repoRoot}/${store.paths.featureRel(featureId, 'sources.json')}';

  /// Runs the crew for [featureId]. Returns true ONLY if exit 0 AND a real phase-2
  /// verdict now exists at [verdictPath] — otherwise the gate stays un-passed.
  Future<bool> run(String featureId) async {
    final args = [
      scriptPath(),
      featureId,
      '--workspace',
      store.repoRoot,
    ];
    // Pass the user's multimodal sources (links/docs) when present so the crew
    // grounds the spec in them and traces every requirement back (P4).
    if (File(sourcesPath(featureId)).existsSync()) {
      args.addAll(['--sources', sourcesPath(featureId)]);
    }
    final ProcessResult result;
    try {
      result = await _run('python3', args, store.repoRoot);
    } on Object {
      return false; // process couldn't start → never fake a pass
    }
    final ok = result.exitCode == 0 && File(verdictPath(featureId)).existsSync();
    if (ok) _liftOpenQuestions(featureId, '${result.stdout}');
    return ok;
  }

  /// Lift the crew's open questions out of its stdout summary into structured state
  /// so the gate can PRESENT them to the user for interactive confirmation (P3) —
  /// the "confirm requirements with me first" loop. Best-effort: never breaks the run.
  void _liftOpenQuestions(String featureId, String stdout) {
    try {
      final line = stdout
          .split('\n')
          .reversed
          .firstWhere((l) => l.trim().startsWith('{'), orElse: () => '');
      if (line.isEmpty) return;
      final qs = (jsonDecode(line) as Map<String, dynamic>)['questions'];
      if (qs is! List || qs.isEmpty) return;
      final state = store.readState(featureId);
      state['requirements_open_questions'] = qs.map((q) => '$q').toList();
      store.writeState(featureId, state, skipRepair: true);
    } catch (_) {/* questions are a nicety; never fail the run on them */}
  }

  static Future<ProcessResult> _defaultRun(
          String exe, List<String> args, String cwd) =>
      Process.run(exe, args, workingDirectory: cwd);
}
