import 'package:orchestration_server/feature_store.dart';
import 'package:orchestration_server/run_post_sync.dart';
import 'package:test/test.dart';

void main() {
  // CONTRACT with scripts/orch/requirements_crew.py's verdict writer — this is the
  // EXACT phase-2.md the crew emits. The live E2E caught a format mismatch where the
  // crew wrote "reviewers: …" but the parser wanted "**Reviewers:** …". Pin it both ways.
  test('parseReviewerSkills reads the real crew verdict format (E2E contract)', () {
    const crewVerdict = '# PO verdict (phase 2): REVISE\n\n'
        '**Reviewers:** bmad-agent-pm, bmad-validate-prd\n'
        '_(perspective-diverse: DeepSeek R1 ∥ Nemotron Ultra)_\n\ngaps: 8\n';
    expect(FeatureStore('/tmp').parseReviewerSkills(crewVerdict),
        ['bmad-agent-pm', 'bmad-validate-prd']);
  });

  group('RunPostSync.resolveReviewers (P2 honest gate)', () {
    const legacy = ['bmad-agent-analyst', 'bmad-review-adversarial-general'];

    test('real reviewers from the verdict always win', () {
      expect(
        RunPostSync.resolveReviewers(fromVerdict: ['bmad-po'], crewEnabled: true),
        ['bmad-po'],
      );
      expect(
        RunPostSync.resolveReviewers(fromVerdict: ['bmad-po'], crewEnabled: false),
        ['bmad-po'],
      );
    });

    test('crew OFF + no real reviewers → legacy fallback (back-compat)', () {
      expect(RunPostSync.resolveReviewers(fromVerdict: null, crewEnabled: false), legacy);
      expect(RunPostSync.resolveReviewers(fromVerdict: const [], crewEnabled: false), legacy);
    });

    test('crew ON + no real reviewers → null (NEVER fabricate a passing review)', () {
      expect(RunPostSync.resolveReviewers(fromVerdict: null, crewEnabled: true), isNull);
      expect(RunPostSync.resolveReviewers(fromVerdict: const [], crewEnabled: true), isNull);
    });
  });
}
