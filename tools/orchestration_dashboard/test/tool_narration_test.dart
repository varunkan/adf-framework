import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:orchestration_dashboard/utils/tool_narration.dart';

void main() {
  group('ToolNarration.humanize', () {
    test('parses tool input structurally — embedded quotes survive (D9)', () {
      // jsonEncode is what the server now sends; the value has escaped quotes that
      // a naive "([^"]+)" regex truncates. Structural parse keeps them intact.
      expect(
        ToolNarration.humanize(
            'bash', jsonEncode({'command': 'grep -r "TODO" lib/'})),
        '\$ grep -r "TODO" lib/',
      );
    });

    test('still reads the Dart Map.toString() form (no-quotes) (D9)', () {
      // What the server emitted BEFORE the jsonEncode fix — must not degrade to
      // the generic "Reading a file".
      expect(ToolNarration.humanize('read_file', '{file_path: lib/db.dart}'),
          'Reading lib/db.dart');
    });

    test('files: read/write/edit show a short path, not JSON', () {
      expect(ToolNarration.humanize('read_file', '{"file_path":"/a/b/c/db.dart"}'),
          'Reading …/b/c/db.dart');
      expect(ToolNarration.humanize('write_file', '{"file_path":"lib/main.dart"}'),
          'Writing lib/main.dart');
      expect(
          ToolNarration.humanize(
              'str_replace_editor', '{"file_path":"server.py","content":"x"}'),
          'Editing server.py');
    });

    test('bash shows the command with a \$ prompt', () {
      expect(ToolNarration.humanize('bash', '{"command":"npm install express"}'),
          '\$ npm install express');
      expect(ToolNarration.humanize('bash', '{}'), 'Running a command');
    });

    test('search shows the query; fetch shows the domain', () {
      expect(ToolNarration.humanize('grep', '{"pattern":"bookmark table"}'),
          'Searching: bookmark table');
      expect(ToolNarration.humanize('web_fetch', '{"url":"https://www.fda.gov/ectd"}'),
          'Fetching fda.gov');
    });

    test('unknown tool falls back to a clean "Using <name>"', () {
      expect(ToolNarration.humanize('mystery_tool', '{}'), 'Using mystery_tool');
      expect(ToolNarration.humanize(null, null), 'Using tool');
    });
  });
}
