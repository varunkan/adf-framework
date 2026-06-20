import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:orchestration_dashboard/utils/code_heuristics.dart';

void main() {
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
