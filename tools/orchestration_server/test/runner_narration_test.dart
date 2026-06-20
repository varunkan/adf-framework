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

    test('generating_progress is a NL heartbeat carrying no code (D2)', () {
      final msg =
          PhaseRunner.runnerNarration({'lines': 42}, 'generating_progress');
      expect(msg, isNotNull);
      expect(msg, contains('Generating'));
      expect(msg, isNot(contains('<<<FILE')));
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

  group('isCodeDump (NL-narration floor)', () {
    test('flags <<<FILE>>> blocks, code fences, SQL and code', () {
      expect(PhaseRunner.isCodeDump('<<<FILE: src/db.ts>>>\nexport const x=1'),
          isTrue);
      expect(PhaseRunner.isCodeDump('```dart\nvoid main() {}\n```'), isTrue);
      expect(
          PhaseRunner.isCodeDump('CREATE TABLE bookmarks (id INTEGER);'), isTrue);
      expect(PhaseRunner.isCodeDump('import "package:flutter/material.dart";'),
          isTrue);
      expect(PhaseRunner.isCodeDump('const router = express.Router();'), isTrue);
    });

    test('keeps genuine natural-language narration', () {
      expect(
          PhaseRunner.isCodeDump(
              "I'll create the bookmarks table and wire the add-bookmark route."),
          isFalse);
      expect(
          PhaseRunner.isCodeDump(
              'The SQLite database stores each bookmark with its URL and title.'),
          isFalse);
      expect(PhaseRunner.isCodeDump('Generating the data layer now.'), isFalse);
    });
  });

  group('ingest dispatch — the suppression/summary path (D7)', () {
    List<Map<String, dynamic>> ingest(List<Map<String, dynamic>> lines) {
      final repo = Directory.systemTemp.createTempSync('adf-ingest');
      addTearDown(
          () => repo.existsSync() ? repo.deleteSync(recursive: true) : null);
      final runner = PhaseRunner(FeatureStore(repo.path));
      for (final l in lines) {
        runner.ingestAgentLine('demo', 7, jsonEncode(l));
      }
      final f = File(OrchestrationPaths(repo.path).otelTracesFile);
      if (!f.existsSync()) return [];
      return f
          .readAsLinesSync()
          .where((s) => s.trim().isNotEmpty)
          .map((s) => jsonDecode(s) as Map<String, dynamic>)
          .toList();
    }

    test('type:text (raw token stream) produces NO span', () {
      final spans = ingest([
        {'type': 'text', 'text': 'const router = express.Router();'}
      ]);
      expect(spans, isEmpty,
          reason: 'the raw per-token code stream must be suppressed');
    });

    test('type:text is never BUFFERED — a following flush surfaces nothing (D7)', () {
      // PROSE text (so the isCodeDump flush-guard can't mask the regression): if
      // type:'text' were wrongly folded back into the buffer branch, the file_write
      // flush would surface it as an agent.stream span. Verified to go RED on a full
      // T7 revert — a genuinely non-vacuous guard (E7).
      const token = 'I am drafting the data layer now and it should work soon.';
      final spans = ingest([
        {'type': 'text', 'text': token},
        {'type': 'file_write', 'path': 'lib/db.dart', 'index': 1, 'total': 1},
      ]);
      expect(spans.any((s) => s['name'] == 'agent.stream'), isFalse,
          reason: 'text must not be buffered; a flush would otherwise surface it');
      expect(spans.where((s) => s['name'] == 'file.write'), hasLength(1));
      expect(spans.any((s) => jsonEncode(s).contains('drafting the data layer')),
          isFalse);
    });

    test('a <<<FILE>>> result is summarized, never dumped', () {
      final spans = ingest([
        {
          'type': 'result',
          'result': '<<<FILE: a.ts>>>\ncode\n<<<FILE: b.ts>>>\nmore code'
        }
      ]);
      final summary =
          spans.where((s) => s['name'] == 'runner.build_summary').toList();
      expect(summary, hasLength(1));
      expect((summary.first['attributes'] as Map)['orch.message'],
          contains('2 file'));
      expect(spans.any((s) => jsonEncode(s).contains('<<<FILE')), isFalse,
          reason: 'no raw code may reach any span');
    });

    test('a plain prose result is KEPT as a span', () {
      final spans = ingest([
        {'type': 'result', 'result': 'I created the login flow and its tests.'}
      ]);
      final res = spans.where((s) => s['name'] == 'agent.result').toList();
      expect(res, hasLength(1));
      expect((res.first['attributes'] as Map)['agent.reasoning'],
          contains('login flow'));
    });

    test('the Python-runner event set narrates WITHOUT the reasoning buffer (D11)',
        () {
      // agent_runner.py emits only narrate-kinds / file_write / result / text —
      // never assistant/message. That set must still produce live narration, and
      // must NOT depend on the (cursor-only) agent.stream reasoning-buffer path.
      final spans = ingest([
        {'type': 'generating', 'attempt': 1},
        {'type': 'file_write', 'path': 'lib/db.dart', 'index': 1, 'total': 2},
        {'type': 'text', 'text': 'const x = 1;'}, // suppressed
        {'type': 'result', 'result': 'I built the data layer.'},
      ]);
      expect(spans.any((s) => '${s['name']}'.startsWith('runner.')), isTrue);
      expect(spans.any((s) => s['name'] == 'agent.result'), isTrue);
      expect(spans.any((s) => s['name'] == 'agent.stream'), isFalse,
          reason: 'the reasoning buffer is cursor-only; Python must not need it');
    });
  });

  test('a long PROSE result keeps up to 8000 chars, not 2000 (D14)', () {
    final repo = Directory.systemTemp.createTempSync('adf-prose');
    addTearDown(() => repo.existsSync() ? repo.deleteSync(recursive: true) : null);
    final runner = PhaseRunner(FeatureStore(repo.path));

    // ~11k chars of plain prose (no <<<FILE>>>, not code) → must NOT be cut to 2000.
    final prose = 'The system stores each bookmark with its url and title. ' * 200;
    runner.ingestAgentLine(
        'demo', 2, jsonEncode({'type': 'result', 'result': prose}));

    final spans = File(OrchestrationPaths(repo.path).otelTracesFile)
        .readAsLinesSync()
        .where((l) => l.trim().isNotEmpty)
        .map((l) => jsonDecode(l) as Map<String, dynamic>)
        .toList();
    final result = spans.firstWhere((s) => s['name'] == 'agent.result');
    final reasoning =
        (result['attributes'] as Map)['agent.reasoning'] as String;
    expect(reasoning.length, greaterThan(4000),
        reason: 'a genuine prose answer must not be cut to the 2000 code-cap');
    expect(reasoning.length, lessThanOrEqualTo(8001)); // 8000 + ellipsis
  });
}
