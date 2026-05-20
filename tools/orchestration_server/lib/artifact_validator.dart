import 'dart:io';

/// Runs scripts/orch/validate_adf_artifacts.sh and parses PASS/FAIL.
class ArtifactValidator {
  ArtifactValidator(this.repoRoot);

  final String repoRoot;

  String get _script =>
      '$repoRoot/scripts/orch/validate_adf_artifacts.sh';

  Future<Map<String, dynamic>> check(
    String featureId, {
    int? phase,
  }) async {
    final blockers = <String>[];
    final warnings = <String>[];
    var pass = true;

    if (!File(_script).existsSync()) {
      return {
        'pass': false,
        'blockers': ['validate_adf_artifacts.sh not found'],
        'warnings': warnings,
        'phase': phase,
      };
    }

    final args = <String>[_script, featureId];
    if (phase != null) {
      args.addAll(['--phase', '$phase']);
    }

    final result = await Process.run(
      'bash',
      args,
      workingDirectory: repoRoot,
      environment: Platform.environment,
    );

    final stdout = (result.stdout as String).trim();
    final stderr = (result.stderr as String).trim();
    final combined = [stdout, stderr].where((s) => s.isNotEmpty).join('\n');

    if (result.exitCode != 0) {
      pass = false;
      for (final line in combined.split('\n')) {
        if (line.startsWith('FAIL:')) {
          blockers.add(line.substring(5).trim());
        } else if (line.contains('FAIL:')) {
          blockers.add(line.trim());
        }
      }
      if (blockers.isEmpty && combined.isNotEmpty) {
        blockers.add(combined);
      }
      if (blockers.isEmpty) {
        blockers.add('validator exited ${result.exitCode}');
      }
    } else {
      for (final line in combined.split('\n')) {
        if (line.startsWith('WARN:')) {
          warnings.add(line.substring(5).trim());
        }
      }
    }

    return {
      'pass': pass,
      'blockers': blockers,
      'warnings': warnings,
      'phase': phase,
      'stdout': stdout,
      'exit_code': result.exitCode,
    };
  }

  Future<Map<String, dynamic>> checklist(
    String featureId,
    int phase,
  ) async {
    final validation = await check(featureId, phase: phase);
    final artifacts = <Map<String, dynamic>>[];

    void addArtifact(String path, {required bool required}) {
      final exists = File('$repoRoot/$path').existsSync() ||
          Directory('$repoRoot/$path').existsSync();
      artifacts.add({
        'path': path,
        'exists': exists,
        'required': required,
      });
      if (required && !exists) {
        validation['pass'] = false;
        (validation['blockers'] as List).add('missing: $path');
      }
    }

    if (phase >= 2) {
      addArtifact('specs/$featureId/spec.md', required: true);
    }
    if (phase >= 3) {
      addArtifact('specs/$featureId/plan.md', required: true);
    }
    if (phase >= 4) {
      addArtifact('specs/$featureId/tasks.md', required: true);
      addArtifact('specs/$featureId/task-graph.yaml', required: true);
      addArtifact('specs/$featureId/tasks', required: true);
    }

    return {
      'feature_id': featureId,
      'phase': phase,
      'pass': validation['pass'] == true,
      'blockers': validation['blockers'],
      'warnings': validation['warnings'],
      'artifacts': artifacts,
      'validation': validation,
    };
  }
}
