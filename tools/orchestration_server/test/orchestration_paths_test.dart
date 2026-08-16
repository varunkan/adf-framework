import 'dart:io';

import 'package:orchestration_server/orchestration_paths.dart';
import 'package:test/test.dart';

void main() {

  test('OrchestrationPaths resolves feature rel paths', () {
    final tmp = Directory.systemTemp.createTempSync('orch_paths2_');
    Directory('${tmp.path}/.adf/orchestration/features/x').createSync(recursive: true);
    final paths = OrchestrationPaths(tmp.path);
    expect(paths.featureRel('x', 'state.json'), contains('features/x/state.json'));
    tmp.deleteSync(recursive: true);
  });

  // ---- CURSOR-6: .adf is the default; .cursor is a no-loss fallback ----------
  group('CURSOR-6 orchestration dir', () {
    test('C11: a fresh repo defaults to .adf/orchestration', () {
      final tmp = Directory.systemTemp.createTempSync('orch_c11_');
      expect(OrchestrationPaths(tmp.path).orchestrationRoot,
          endsWith('.adf/orchestration'));
      tmp.deleteSync(recursive: true);
    });



  });
}
