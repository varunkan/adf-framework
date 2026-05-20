import 'dart:io';

import 'package:orchestration_server/feature_store.dart';
import 'package:test/test.dart';

void main() {
  late String repoRoot;
  late FeatureStore store;
  const id = 'reviewer-reconcile-test';

  setUp(() {
    repoRoot = Directory.current.path;
    while (!Directory('$repoRoot/.cursor/orchestration').existsSync()) {
      repoRoot = Directory(repoRoot).parent.path;
    }
    store = FeatureStore(repoRoot);
    if (!store.featureExists(id)) {
      store.createFeature(id: id, requirement: 'reviewer test', track: 'S');
    }
    final verdictDir = Directory('${store.featurePath(id)}/judge-verdicts');
    verdictDir.createSync(recursive: true);
    File('${verdictDir.path}/phase-2.md').writeAsStringSync('''
# Judge Verdict — Phase 2

**Verdict:** PASS
**Reviewers:** bmad-agent-pm, bmad-validate-prd
''');
  });

  tearDown(() {
    if (store.featureExists(id)) {
      Directory(store.featurePath(id)).deleteSync(recursive: true);
    }
  });

  test('parseReviewerSkills splits comma list', () {
    final skills = store.parseReviewerSkills(
      '**Reviewers:** foo, bar-baz',
    );
    expect(skills, ['foo', 'bar-baz']);
  });

  test('reconcileCompletedReviewersFromVerdicts fills state', () {
    final state = store.readState(id)
      ..['completed_reviewers'] = <String, dynamic>{};
    expect(store.reconcileCompletedReviewersFromVerdicts(id, state), isTrue);
    final list = (state['completed_reviewers']['2'] as List).cast<String>();
    expect(list, contains('bmad-agent-pm'));
  });
}
