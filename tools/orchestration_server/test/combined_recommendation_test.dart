import 'dart:io';

import 'package:orchestration_server/feature_store.dart';
import 'package:test/test.dart';

void main() {
  late Directory tmp;
  late FeatureStore store;

  setUp(() {
    tmp = Directory.systemTemp.createTempSync('orch_combined_');
    store = FeatureStore(tmp.path);
  });

  tearDown(() {
    if (tmp.existsSync()) tmp.deleteSync(recursive: true);
  });

  test('parseCombinedRecommendation extracts section', () {
    const md = '''
# Judge Verdict — Phase 1
**Verdict:** REVISE

## Analyst
### Recommendation
Fix scope.

## Combined recommendation
Do not advance until requirement.md is expanded. Re-run phase 1 after revision.
''';
    final combined = store.parseCombinedRecommendation(md);
    expect(combined, contains('Do not advance'));
    expect(combined, isNot(contains('## Analyst')));
  });

  test('readCombinedRecommendation from feature dir', () {
    store.createFeature(id: 'f1', requirement: 'x', track: 'S');
    final verdictDir = Directory('${store.featurePath('f1')}/judge-verdicts');
    verdictDir.createSync();
    File('${verdictDir.path}/phase-1.md').writeAsStringSync('''
**Verdict:** REVISE

## Combined recommendation
Reconcile product intent with codebase.
''');
    expect(store.readCombinedRecommendation('f1', phase: 1),
        'Reconcile product intent with codebase.');
  });
}
