import 'dart:io';

import 'package:orchestration_server/artifact_validator.dart';
import 'package:test/test.dart';

void main() {
  late String repoRoot;
  late ArtifactValidator validator;

  setUpAll(() {
    repoRoot = Directory.current.path.contains('orchestration_server')
        ? Directory.current.parent.parent.path
        : Directory.current.path;
    validator = ArtifactValidator(repoRoot);
  });

  test('check returns map with pass key for missing feature', () async {
    final result = await validator.check('_nonexistent_feature_xyz');
    expect(result.containsKey('pass'), isTrue);
    expect(result.containsKey('blockers'), isTrue);
  });

  test('checklist includes artifacts list for phase 4', () async {
    final result = await validator.checklist('_nonexistent_feature_xyz', 4);
    expect(result['phase'], 4);
    expect(result['artifacts'], isA<List>());
  });
}
