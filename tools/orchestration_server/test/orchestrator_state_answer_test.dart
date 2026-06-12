import 'dart:io';

import 'package:orchestration_server/feature_store.dart';
import 'package:orchestration_server/orchestrator_chat.dart';
import 'package:test/test.dart';

void main() {
  late Directory tmp;
  late FeatureStore store;
  late OrchestratorChatProcessor processor;

  setUp(() {
    tmp = Directory.systemTemp.createTempSync('orch_state_');
    store = FeatureStore(tmp.path);
    processor = OrchestratorChatProcessor(store);
    store.createFeature(id: 'pay1', requirement: 'Payment form', track: 'M');
  });

  tearDown(() => tmp.deleteSync(recursive: true));

  test('stateOnly answers phase questions', () async {
    final r = await processor.process(
      'pay1',
      'what phase are we on?',
      mode: ChatProcessMode.stateOnly,
    );
    expect(r.source, 'state');
    expect(r.action, OrchestratorAction.answerOnly);
    expect(r.assistantReply.toLowerCase(), contains('phase'));
  });

  test('stateOnly answers URL questions', () async {
    final r = await processor.process(
      'pay1',
      'what is the url for this feature?',
      mode: ChatProcessMode.stateOnly,
    );
    expect(r.source, 'state');
    expect(r.assistantReply, contains('3847'));
  });

  test('describe-intent questions answer instantly from disk state', () async {
    // Warm the VM/file cache so the timing loop measures steady-state.
    await processor.process(
      'pay1',
      'what does this feature do',
      mode: ChatProcessMode.stateOnly,
    );

    const questions = [
      'what does this feature do',
      'what does it do?',
      'what is this feature',
      "what's this feature?",
      'describe this feature',
      'explain the feature please',
      'summarize this feature',
      'what am I building',
    ];
    for (final q in questions) {
      final sw = Stopwatch()..start();
      final r = await processor.process(
        'pay1',
        q,
        mode: ChatProcessMode.stateOnly,
      );
      sw.stop();
      expect(r.source, 'state', reason: q);
      expect(r.action, OrchestratorAction.answerOnly, reason: q);
      expect(sw.elapsedMilliseconds, lessThan(100), reason: q);
      expect(r.latencyMs, isNotNull, reason: q);
      expect(r.assistantReply, contains('Payment form'), reason: q);
    }
  });

  test('describe answer includes spec EARS excerpt, phase, and gates',
      () async {
    File('${tmp.path}/specs/pay1/spec.md')
      ..parent.createSync(recursive: true)
      ..writeAsStringSync('# Specification — pay1\n\n'
          '## Requirements (EARS)\n\n### REQ-001\n\n'
          'The system SHALL render a payment form.\n');
    final r = await processor.process(
      'pay1',
      'what does this feature do?',
      mode: ChatProcessMode.stateOnly,
    );
    expect(r.source, 'state');
    expect(
      r.assistantReply,
      contains('The system SHALL render a payment form.'),
    );
    expect(r.assistantReply.toLowerCase(), contains('phase'));
    expect(r.assistantReply, contains('gates passed'));
    expect(r.latencyMs, lessThan(100));
  });
}
