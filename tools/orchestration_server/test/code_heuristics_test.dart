import 'dart:convert';
import 'dart:io';

import 'package:orchestration_server/code_heuristics.dart';
import 'package:test/test.dart';

void main() {
  test('isCodeLike satisfies the shared golden contract (D3 SSOT)', () {
    // ../ from the package root → tools/code_heuristics_golden.json (the SAME file
    // the dashboard package's test loads — drift in either impl fails here).
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
