import 'dart:convert';
import 'dart:io';

import 'package:orchestration_server/feature_store.dart';
import 'package:test/test.dart';

/// Audit STATE-1: governance writes must be durable — a kill mid-write can't leave
/// a torn/corrupt file that bricks the feature. writeFileAtomic writes a temp
/// sibling then renames (atomic on POSIX); every whole-file governance writer uses
/// it, so a reader always sees a complete document and no `.tmp` leftovers.
void main() {
  late Directory tmp;
  late FeatureStore store;
  const id = 'atomic';

  setUp(() {
    tmp = Directory.systemTemp.createTempSync('adf-atomic');
    store = FeatureStore(tmp.path);
    store.createFeature(id: id, requirement: 'x', track: 'M');
  });
  tearDown(() {
    if (tmp.existsSync()) tmp.deleteSync(recursive: true);
  });

  test('writeFileAtomic writes via temp+rename, leaving no .tmp', () {
    final f = File('${tmp.path}/x.json');
    FeatureStore.writeFileAtomic(f, '{"a":1}');
    expect(f.readAsStringSync(), '{"a":1}');
    expect(File('${f.path}.tmp').existsSync(), isFalse);
  });

  test('every whole-file governance writer is atomic (valid JSON, no torn temp)',
      () {
    store.writeRunStatus(id, {'status': 'running', 'phase': 7});
    store.appendApproval(id, {'phase': 6, 'decision': 'approved'});
    store.writePhaseRequest(id, 7);
    final p = store.featurePath(id);
    for (final name in const [
      'state.json',
      'run-status.json',
      'approvals.json',
      'phase-request.json',
    ]) {
      final f = File('$p/$name');
      expect(f.existsSync(), isTrue, reason: name);
      expect(() => jsonDecode(f.readAsStringSync()), returnsNormally,
          reason: '$name is valid JSON');
      expect(File('${f.path}.tmp').existsSync(), isFalse,
          reason: 'no $name.tmp leftover');
    }
    expect(store.readApprovals(id).length, 1);
    expect(store.readRunStatus(id)?['status'], 'running');
  });
}
