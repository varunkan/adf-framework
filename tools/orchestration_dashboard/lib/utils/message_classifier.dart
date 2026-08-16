/// Classifies a chat message for the one-box loop: a QUESTION is answered in
/// chat, while anything else (an imperative/change request) edits the built app.
///
/// Deliberately conservative — empty/whitespace counts as a question so we never
/// trigger an accidental rebuild on a stray submit.
///
/// A slash command the one-box loop handles directly (not a question, not an
/// edit): `/compact` folds the app's accumulated context and writes a card.
bool isCompactCommand(String s) => s.trim().toLowerCase() == '/compact';

bool looksLikeQuestion(String s) {
  final t = s.trim().toLowerCase();
  if (t.isEmpty) return true;
  if (t.endsWith('?')) return true;
  final first = t.split(RegExp(r'\s+')).first;
  const questionWords = {
    'what', "what's", 'whats', 'why', 'how', 'can', 'could', 'does', 'do',
    'is', 'are', 'was', 'were', 'where', 'when', 'who', 'which', 'should',
    'will', 'would', 'explain', 'tell', 'show', 'help',
  };
  return questionWords.contains(first);
}
