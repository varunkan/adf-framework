import 'package:flutter_test/flutter_test.dart';
import 'package:orchestration_dashboard/utils/thought_sanitizer.dart';

void main() {
  group('ThoughtSanitizer.clean', () {
    test('keeps genuine natural-language reasoning verbatim', () {
      const prose = "I'll create the bookmarks table and persist it via SQLite.";
      expect(ThoughtSanitizer.clean(prose), prose);
      expect(
        ThoughtSanitizer.clean('Next, wire the API route that adds a bookmark.'),
        'Next, wire the API route that adds a bookmark.',
      );
    });

    test('rewrites a raw SQL query to plain English', () {
      expect(
        ThoughtSanitizer.clean(
            'CREATE TABLE bookmarks (id INTEGER PRIMARY KEY, url TEXT);'),
        'Writing a database query',
      );
      expect(
        ThoughtSanitizer.clean('SELECT * FROM users WHERE active = 1'),
        'Writing a database query',
      );
    });

    test('rewrites code lines to "Writing code", not a raw dump', () {
      expect(ThoughtSanitizer.clean('const router = express.Router();'),
          'Writing code');
      expect(ThoughtSanitizer.clean('def add_bookmark(url): return db.save(url)'),
          'Writing code');
      expect(ThoughtSanitizer.clean('import "package:flutter/material.dart";'),
          'Writing code');
    });

    test('rewrites shell/build commands to "Running a command"', () {
      expect(ThoughtSanitizer.clean('npm install express'), 'Running a command');
      expect(ThoughtSanitizer.clean('flutter pub get'), 'Running a command');
      expect(ThoughtSanitizer.clean(r'$ git commit -m "wip"'), 'Running a command');
    });

    test('rewrites JSON/config fragments to "Updating configuration"', () {
      expect(ThoughtSanitizer.clean('{"timeout": 240, "retries": 3}'),
          'Updating configuration');
      expect(ThoughtSanitizer.clean('"dependencies": {'), 'Updating configuration');
    });

    test('drops noise lines (bare paths, opaque identifiers)', () {
      expect(ThoughtSanitizer.clean('src/db/migrations/0001_init.sql'), isNull);
      expect(ThoughtSanitizer.clean('   '), isNull);
      expect(ThoughtSanitizer.clean('}'), isNull);
    });

    test('prose mentioning a tech term is NOT misclassified as code', () {
      const s = 'The SQLite database stores each bookmark with its URL and title.';
      expect(ThoughtSanitizer.clean(s), s);
    });

    test('keeps prose that opens with a SQL/code/shell keyword (D8)', () {
      for (final s in const [
        'Update the spec to add the validation rule.',
        'Return the new bookmark id to the client.',
        'From the spec, we derive the data schema.',
        'Static analysis shows no leaks.',
        'Flutter rebuilds the widget tree on setState.',
        'Select the best export format for the user.',
      ]) {
        expect(ThoughtSanitizer.clean(s), s, reason: 'must stay prose: "$s"');
      }
    });
  });
}
