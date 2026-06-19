import 'dart:convert';
import 'dart:io';

import 'package:orchestration_server/feature_store.dart';
import 'package:orchestration_server/orchestration_paths.dart';
import 'package:orchestration_server/phase_runner.dart';
import 'package:test/test.dart';

void main() {
  group('runnerNarration (pure)', () {
    test('verify_stage announces the stage is running', () {
      expect(PhaseRunner.runnerNarration({'stage': 'vitest'}, 'verify_stage'),
          'Running vitest…');
    });

    test('verify_stage_result reflects the REAL ok flag, never optimism', () {
      expect(
          PhaseRunner.runnerNarration(
              {'stage': 'vitest', 'ok': true}, 'verify_stage_result'),
          'vitest passed ✓');
      expect(
          PhaseRunner.runnerNarration(
              {'stage': 'vitest', 'ok': false}, 'verify_stage_result'),
          'vitest failed ✗');
    });

    test('sealed formats the real seal + file count', () {
      expect(
          PhaseRunner.runnerNarration({'seal': 'abc123', 'files': 7}, 'sealed'),
          '🔏 Sealed Proof of Build abc123 over 7 file(s)');
    });

    test('policy_blocked names the enforced rules', () {
      expect(
          PhaseRunner.runnerNarration({
            'rules': ['no_weak_crypto', 'no_secrets']
          }, 'policy_blocked'),
          '🚫 Blocked by policy: no_weak_crypto, no_secrets');
    });

    test('an unknown type returns null (left for other handlers)', () {
      expect(PhaseRunner.runnerNarration({}, 'totally_unknown'), isNull);
    });
  });

  test('a runner narration event becomes a live trace span (kills dead-air)', () {
    final repo = Directory.systemTemp.createTempSync('adf-narr');
    addTearDown(() => repo.existsSync() ? repo.deleteSync(recursive: true) : null);
    final runner = PhaseRunner(FeatureStore(repo.path));

    runner.ingestAgentLine(
        'demo', 7, jsonEncode({'type': 'verify_stage', 'stage': 'vitest'}));
    runner.ingestAgentLine('demo', 7,
        jsonEncode({'type': 'verify_stage_result', 'stage': 'vitest', 'ok': true}));

    final spans = File(OrchestrationPaths(repo.path).otelTracesFile)
        .readAsLinesSync()
        .where((l) => l.trim().isNotEmpty)
        .map((l) => jsonDecode(l) as Map<String, dynamic>)
        .toList();
    final narr =
        spans.where((s) => '${s['name']}'.startsWith('runner.')).toList();
    expect(narr, hasLength(2), reason: 'both events must surface as spans');
    expect((narr[0]['attributes'] as Map)['orch.message'], 'Running vitest…');
    expect((narr[1]['attributes'] as Map)['orch.message'], 'vitest passed ✓');
  });
}
