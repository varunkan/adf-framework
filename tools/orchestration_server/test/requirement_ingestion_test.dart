import 'dart:io';

import 'package:orchestration_server/feature_store.dart';
import 'package:test/test.dart';

/// G2/I4/I7 — `appendClientClarification` must NOT contaminate requirement.md
/// with orchestrator control commands or bare affirmatives. In the
/// regulatory-affairs incident the user typed `@orch-orchestrator resume …`
/// many times to unstick a hung build; each was appended verbatim and the
/// deterministic engine turned them into "The system SHALL …" requirements
/// (REQ-004 was a wall of command spam), permanently failing the garbage floor.
/// Real clarification prose must still be preserved.
void main() {
  late String repoRoot;
  late FeatureStore store;
  const id = 'requirement-ingestion-test';

  setUp(() {
    repoRoot = Directory.current.path;
    while (!Directory('$repoRoot/.adf/orchestration').existsSync()) {
      final parent = Directory(repoRoot).parent;
      if (parent.path == repoRoot) throw StateError('repo root not found');
      repoRoot = parent.path;
    }
    store = FeatureStore(repoRoot);
    if (!store.featureExists(id)) {
      store.createFeature(
        id: id,
        requirement: 'Build a notes app where a user can add and list notes.',
        track: 'M',
      );
    }
  });

  tearDown(() {
    if (store.featureExists(id)) {
      Directory(store.featurePath(id)).deleteSync(recursive: true);
    }
  });

  test('orchestrator command spam is quarantined out of requirement.md', () {
    store.appendClientClarification(
      id,
      '@orch-orchestrator resume requirement-ingestion-test\n'
      '# Builder: speckit-implement phase 7\n'
      'resume requirement-ingestion-test',
    );
    final req = store.readRequirement(id);
    expect(req, isNot(contains('@orch-orchestrator')),
        reason: 'orchestrator control commands must never enter requirement.md');
    expect(req, isNot(contains('# Builder:')));
    // A clarification block that was ENTIRELY control commands must not be
    // appended at all (no empty "## Client clarification" heading).
    expect(req, isNot(contains('## Client clarification')),
        reason: 'a control-only turn adds no requirement content');
  });

  test('a bare affirmative does not become a requirement', () {
    store.appendClientClarification(id, 'yes');
    expect(store.readRequirement(id), isNot(contains('## Client clarification')),
        reason: 'pure affirmatives update execution state, not requirements');
  });

  test('real clarification prose IS preserved', () {
    store.appendClientClarification(
        id, 'Also support tagging notes and filtering by tag.');
    final req = store.readRequirement(id);
    expect(req, contains('## Client clarification'));
    expect(req, contains('tagging notes and filtering by tag'));
  });

  test('mixed turn keeps the prose, drops the command line', () {
    store.appendClientClarification(
      id,
      '@orch-orchestrator resume requirement-ingestion-test\n'
      'The receipt must include the GST line item.',
    );
    final req = store.readRequirement(id);
    expect(req, isNot(contains('@orch-orchestrator')));
    expect(req, contains('The receipt must include the GST line item.'));
  });
}
