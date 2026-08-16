import 'package:flutter_test/flutter_test.dart';
import 'package:orchestration_dashboard/utils/message_classifier.dart';

/// The one-box loop: on a built app, a QUESTION goes to chat while a CHANGE
/// request edits the app. This pins the classifier that drives that routing.
void main() {
  test('questions classify as questions (→ chat)', () {
    const questions = [
      'what was built?',
      'can I test it',
      'how does this work',
      'is it done?',
      'why did the build fail',
      'where is the preview',
      "what's the url",
      'Does it persist data?',
    ];
    for (final q in questions) {
      expect(looksLikeQuestion(q), isTrue, reason: q);
    }
  });

  test('change requests do NOT classify as questions (→ edit)', () {
    const changes = [
      'make the header blue',
      'change the title to My Money',
      'add a dark mode toggle',
      'remove the footer',
      'set the button green',
      'use a larger font for the total',
      'rename the app to Budget',
    ];
    for (final c in changes) {
      expect(looksLikeQuestion(c), isFalse, reason: c);
    }
  });

  test('empty / whitespace is treated as a question (safe: no accidental edit)',
      () {
    expect(looksLikeQuestion(''), isTrue);
    expect(looksLikeQuestion('   '), isTrue);
  });
}
