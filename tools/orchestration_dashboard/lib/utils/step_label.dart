/// Maps an internal pipeline step id (e.g. 'bmad-test-plan-phase-5') to a
/// human-friendly label, never the raw machine id. Pure + testable.
///
/// Specificity matters: `test` is checked BEFORE `plan` so a "test-plan" step
/// reads as "Writing tests", not "Planning" (D4).
String stepLabelFromId(String? id, int? phase) {
  if (id == null || id.trim().isEmpty) {
    return phase != null ? 'Phase $phase' : 'Working…';
  }
  final l = id.toLowerCase();
  if (l.contains('review')) return 'Reviewing with the AI panel';
  if (l.contains('test')) return 'Writing tests'; // before 'plan' (test-plan)
  if (l.contains('spec')) return 'Writing the spec';
  if (l.contains('plan')) return 'Planning';
  if (l.contains('task')) return 'Breaking down tasks';
  if (l.contains('implement') || l.contains('build') || l.contains('code')) {
    return 'Building';
  }
  if (l.contains('intake') || l.contains('problem')) {
    return 'Capturing requirements';
  }
  return id.replaceAll(RegExp(r'[-_]'), ' ').trim();
}
