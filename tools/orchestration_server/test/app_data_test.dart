import 'dart:io';

import 'package:orchestration_server/app_data.dart';
import 'package:test/test.dart';

bool _pythonAvailable() {
  try {
    return Process.runSync('python3', ['--version']).exitCode == 0;
  } catch (_) {
    return false;
  }
}

String _repoScriptsOrch() {
  var dir = Directory.current;
  for (var i = 0; i < 6; i++) {
    final cand = Directory('${dir.path}/scripts/orch');
    if (File('${cand.path}/app_data.py').existsSync()) return cand.path;
    dir = dir.parent;
  }
  throw StateError('could not find scripts/orch from ${Directory.current.path}');
}

void main() {
  late Directory repo;
  late AppData data;
  final srcScripts = _repoScriptsOrch();

  setUp(() {
    repo = Directory.systemTemp.createTempSync('adf-appdata');
    Directory('${repo.path}/scripts/orch').createSync(recursive: true);
    File('$srcScripts/app_data.py')
        .copySync('${repo.path}/scripts/orch/app_data.py');
    data = AppData(repo.path);
  });

  tearDown(() {
    if (repo.existsSync()) repo.deleteSync(recursive: true);
  });

  /// Seed a real SQLite DB the way a generated app would (via python3 stdlib).
  void seedDb() {
    final app = Directory('${repo.path}/apps/demo')..createSync(recursive: true);
    final r = Process.runSync('python3', [
      '-c',
      "import sqlite3; c=sqlite3.connect(r'${app.path}/data.db'); "
          "c.execute('CREATE TABLE notes (id INTEGER PRIMARY KEY, body TEXT)'); "
          "c.executemany('INSERT INTO notes (body) VALUES (?)', [('hi',),('yo',)]); "
          "c.commit(); c.close()",
    ]);
    expect(r.exitCode, 0, reason: '${r.stdout}\n${r.stderr}');
  }

  test('no DB -> has_db false', () async {
    Directory('${repo.path}/apps/demo').createSync(recursive: true);
    final res = await data.tables('demo');
    expect(res['has_db'], isFalse);
  });

  test('lists tables with row counts', () async {
    seedDb();
    final res = await data.tables('demo');
    expect(res['has_db'], isTrue, reason: res.toString());
    final names = (res['tables'] as List).map((t) => t['name']).toList();
    expect(names, contains('notes'));
    final notes = (res['tables'] as List).firstWhere((t) => t['name'] == 'notes');
    expect(notes['rows'], 2);
  }, skip: _pythonAvailable() ? false : 'python3 not available');

  test('browses a table\'s rows', () async {
    seedDb();
    final res = await data.rows('demo', 'notes');
    expect(res['columns'], ['id', 'body']);
    expect((res['rows'] as List).length, 2);
  }, skip: _pythonAvailable() ? false : 'python3 not available');

  test('an unknown / injected table name yields an error, not SQL', () async {
    seedDb();
    final res = await data.rows('demo', 'notes; DROP TABLE notes;--');
    expect(res['error'], isNotNull);
    // table still intact
    final after = await data.rows('demo', 'notes');
    expect((after['rows'] as List).length, 2);
  }, skip: _pythonAvailable() ? false : 'python3 not available');
}
