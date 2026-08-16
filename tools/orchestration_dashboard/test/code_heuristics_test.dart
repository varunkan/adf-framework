import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:orchestration_dashboard/utils/code_heuristics.dart';

void main() {
  test('the two CodeHeuristics copies are byte-identical (DRIFT guard)', () {
    // The golden vector only catches drift on inputs it contains; this catches
    // ANY divergence between the server + dashboard copies. Both files are kept in
    // sync except the one cross-reference comment line (the other file's path).
    String norm(String path) => File(path)
        .readAsLinesSync()
        .where((l) => !l.contains('code_heuristics.dart;'))
        .join('\n');
    final dashboard = norm('lib/utils/code_heuristics.dart');
    final server = norm('../orchestration_server/lib/code_heuristics.dart');
    expect(dashboard, server,
        reason: 'CodeHeuristics copies drifted — re-sync them (SSOT contract)');
  });

  test('isCodeLike satisfies the shared golden contract (D3 SSOT)', () {
    // ../ from the package root → tools/code_heuristics_golden.json (shared with
    // the server package; both impls are pinned to this one vector).
    final golden = jsonDecode(
        File('../code_heuristics_golden.json').readAsStringSync())
        as Map<String, dynamic>;
    for (final c in (golden['cases'] as List)) {
      final text = c['text'] as String;
      final expected = c['code'] as bool;
      expect(CodeHeuristics.isCodeLike(text), expected,
          reason: 'golden contract violated for: "$text"');
    }
  });
}
