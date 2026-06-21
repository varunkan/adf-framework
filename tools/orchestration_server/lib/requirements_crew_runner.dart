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

  /// The path the approval gate reads the PO verdict from.
  String verdictPath(String featureId) =>
      '${store.repoRoot}/${store.paths.featureRel(featureId, 'judge-verdicts/phase-2.md')}';

  /// Runs the crew for [featureId]. Returns true ONLY if exit 0 AND a real phase-2
  /// verdict now exists at [verdictPath] — otherwise the gate stays un-passed.
  Future<bool> run(String featureId) async {
    final ProcessResult result;
    try {
      result = await _run(
        'python3',
        [
          'scripts/orch/requirements_crew.py',
          featureId,
          '--workspace',
          store.repoRoot,
        ],
        store.repoRoot,
      );
    } on Object {
      return false; // process couldn't start → never fake a pass
    }
    return result.exitCode == 0 && File(verdictPath(featureId)).existsSync();
  }

  static Future<ProcessResult> _defaultRun(
          String exe, List<String> args, String cwd) =>
      Process.run(exe, args, workingDirectory: cwd);
}
