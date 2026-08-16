import 'package:flutter/material.dart';

/// Shows the "Request changes" note dialog and returns the trimmed note, or null
/// when the user cancels OR leaves it empty (empty == cancelled — D5/E10).
///
/// The controller lives in the dialog's own State and is disposed in dispose()
/// once the route is fully removed — so there is no leak (E9) and no disposing a
/// controller a still-animating TextField references. Extracted so the
/// note-capture flow is directly widget-testable.
Future<String?> promptRevisionNote(BuildContext context) async {
  final note = await showDialog<String>(
    context: context,
    builder: (_) => const _RevisionDialog(),
  );
  return (note == null || note.isEmpty) ? null : note;
}

class _RevisionDialog extends StatefulWidget {
  const _RevisionDialog();

  @override
  State<_RevisionDialog> createState() => _RevisionDialogState();
}

class _RevisionDialogState extends State<_RevisionDialog> {
  final _controller = TextEditingController();

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Request changes'),
      content: TextField(
        controller: _controller,
        autofocus: true,
        maxLines: 3,
        decoration: const InputDecoration(
          hintText: 'What should change? (the AI review is also used)',
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Cancel'),
        ),
        FilledButton(
          onPressed: () => Navigator.pop(context, _controller.text.trim()),
          child: const Text('Request changes'),
        ),
      ],
    );
  }
}
