import 'package:flutter/material.dart';

/// Shows the requirements crew's open questions at the gate — "confirm these
/// before I build" (P3 interactive elicitation). The user answers in chat; the
/// answer is appended to the requirement and re-runs the crew. Renders nothing when
/// there are no open questions.
class RequirementsQuestionsPanel extends StatelessWidget {
  const RequirementsQuestionsPanel({super.key, required this.questions});

  final List<String> questions;

  /// Pulls the questions out of a feature-detail payload (null/!=List → empty).
  static List<String> fromDetail(Map<String, dynamic>? detail) {
    final q = detail?['requirements_open_questions'];
    return q is List ? q.map((e) => '$e').toList() : const [];
  }

  @override
  Widget build(BuildContext context) {
    if (questions.isEmpty) return const SizedBox.shrink();
    final scheme = Theme.of(context).colorScheme;
    return Card(
      margin: const EdgeInsets.symmetric(vertical: 8),
      color: scheme.secondaryContainer,
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(Icons.help_outline, size: 18, color: scheme.onSecondaryContainer),
                const SizedBox(width: 8),
                Text(
                  'Confirm before building (${questions.length})',
                  style: TextStyle(
                    fontWeight: FontWeight.bold,
                    color: scheme.onSecondaryContainer,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 8),
            for (var i = 0; i < questions.length; i++)
              Padding(
                padding: const EdgeInsets.only(bottom: 6),
                child: Text('${i + 1}. ${questions[i]}',
                    style: TextStyle(color: scheme.onSecondaryContainer, height: 1.35)),
              ),
            const SizedBox(height: 4),
            Text(
              'Answer these in chat — your answers refine the spec and re-run the review.',
              style: TextStyle(
                fontSize: 12,
                fontStyle: FontStyle.italic,
                color: scheme.onSecondaryContainer.withValues(alpha: 0.8),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
