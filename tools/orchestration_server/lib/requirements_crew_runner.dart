import 'dart:convert';
import 'dart:io';

import 'feature_store.dart';

typedef ProcessRun = Future<ProcessResult> Function(
    String exe, List<String> args, String workingDirectory,
    {Map<String, String>? environment});

/// Invokes the multi-agent requirements CREW (scripts/orch/requirements_crew.py)
/// for a feature, producing a research-grounded spec + a REAL Product-Owner verdict
/// — replacing the deterministic template engine and the faked reviewers (P2).
///
/// Gated by `ADF_REQUIREMENTS_CREW=1` so behaviour is unchanged when off. The run
/// is only reported successful when a real phase-2 verdict actually landed where the
/// approval gate reads it, so a crashed/empty crew run can NEVER fake a pass (the
/// file's content is validated for a recognizable verdict token, not merely its
/// existence).
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
  /// verdict now exists at [verdictPath] with a recognizable PASS/REVISE/FAIL token
  /// — otherwise the gate stays un-passed.
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
      // Pass Dart's resolver-chosen orchestration root explicitly so the Python
      // writer and the Dart gate reader are provably bound to the same path,
      // regardless of install layout (G01).
      result = await _run('python3', args, store.repoRoot,
          environment: {'ORCH_ORCHESTRATION_DIR': store.paths.orchestrationRoot});
    } on Object {
      return false; // process couldn't start → never fake a pass
    }
    final ok =
        result.exitCode == 0 && _hasValidVerdict(File(verdictPath(featureId)));
    if (ok) _liftOpenQuestions(featureId, '${result.stdout}');
    return ok;
  }

  /// True only when the phase-2 verdict file exists, is non-empty, and carries a
  /// recognizable verdict token — so an empty (0-byte), whitespace-only, or garbage
  /// file can NEVER fake a pass (G13). Matches the crew's real phase-2.md format
  /// `# PO verdict (phase 2): PASS|REVISE` (requirements_crew.py:237) and the bare
  /// `Verdict: PASS|REVISE|FAIL` token. Does NOT match po-validation.md's
  /// `**Verdict:**` form — that is a different artifact owned by
  /// feature_store.parseJudgeVerdict; keep them separate.
  static bool _hasValidVerdict(File f) {
    if (!f.existsSync()) return false;
    final content = f.readAsStringSync().trim();
    if (content.isEmpty) return false;
    return RegExp(
      r'(?:#\s*)?PO verdict[^:\n]*:\s*(PASS|REVISE|FAIL)'
      r'|Verdict:\s*(PASS|REVISE|FAIL)',
      caseSensitive: false,
    ).hasMatch(content);
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
          String exe, List<String> args, String cwd,
          {Map<String, String>? environment}) =>
      Process.run(exe, args,
          workingDirectory: cwd,
          // Merge so the explicitly-passed ORCH_ORCHESTRATION_DIR WINS over any
          // ambient shell value — the Dart-resolved path is authoritative (fail
          // CLOSED; a shell override cannot silently redirect verdict writes).
          environment: environment == null
              ? null
              : {...Platform.environment, ...environment});
}
