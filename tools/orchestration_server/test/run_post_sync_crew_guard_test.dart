import 'package:orchestration_server/run_post_sync.dart';
import 'package:test/test.dart';

void main() {
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
