import 'dart:io';

import 'package:orchestration_server/orchestration_paths.dart';
import 'package:test/test.dart';

void main() {
  test('hasOrchestrationAt detects legacy .cursor path', () {
    final tmp = Directory.systemTemp.createTempSync('orch_paths_');
    Directory('${tmp.path}/.cursor/orchestration').createSync(recursive: true);
    expect(OrchestrationPaths.hasOrchestrationAt(tmp.path), isTrue);
    tmp.deleteSync(recursive: true);
  });

  test('OrchestrationPaths resolves feature rel paths', () {
    final tmp = Directory.systemTemp.createTempSync('orch_paths2_');
    Directory('${tmp.path}/.cursor/orchestration/features/x').createSync(recursive: true);
    final paths = OrchestrationPaths(tmp.path);
    expect(paths.featureRel('x', 'state.json'), contains('features/x/state.json'));
    tmp.deleteSync(recursive: true);
  });
}
