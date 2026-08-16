import 'dart:io';

import 'package:orchestration_server/compaction.dart';
import 'package:test/test.dart';

bool _pythonAvailable() {
  try {
    return Process.runSync('python3', ['--version']).exitCode == 0;
  } catch (_) {
    return false;
  }
}

/// Locate the repo's scripts/orch so the test shells the REAL /compact engine
/// (single source of truth — the Dart side never re-implements the math).
String _repoScriptsOrch() {
  var dir = Directory.current;
  for (var i = 0; i < 6; i++) {
    final cand = Directory('${dir.path}/scripts/orch');
    if (File('${cand.path}/compaction.py').existsSync()) return cand.path;
    dir = dir.parent;
  }
  throw StateError('could not find scripts/orch from ${Directory.current.path}');
}

void main() {
  late Directory repo;
  late Compaction cx;
  final srcScripts = _repoScriptsOrch();

  setUp(() {
    repo = Directory.systemTemp.createTempSync('adf-compaction');
    Directory('${repo.path}/scripts/orch').createSync(recursive: true);
    File('$srcScripts/compaction.py')
        .copySync('${repo.path}/scripts/orch/compaction.py');
    cx = Compaction(repo.path);
  });

  tearDown(() {
    if (repo.existsSync()) repo.deleteSync(recursive: true);
  });

  void writeApp() {
    // Several files so the fold has something to summarize (a lone oversized file
    // can't be folded — the engine always keeps at least one file whole).
    final app = Directory('${repo.path}/apps/demo')..createSync(recursive: true);
    Directory('${app.path}/src').createSync(recursive: true);
    Directory('${app.path}/server/api').createSync(recursive: true);
    File('${app.path}/src/a.tsx').writeAsStringSync('// a\n${'x' * 4000}');
    File('${app.path}/src/b.tsx').writeAsStringSync('// b\n${'y' * 4000}');
    File('${app.path}/server/api/c.mjs').writeAsStringSync('// c\n${'z' * 4000}');
  }

  test('no app -> has_app false, no crash', () async {
    final res = await cx.estimate('missing');
    expect(res['has_app'], isFalse);
  });

  test('estimate reports tokens vs budget and an over-budget verdict', () async {
    writeApp();
    final res = await cx.estimate('demo', budget: 100);
    expect(res['has_app'], isTrue);
    expect(res['over'], isTrue, reason: res.toString());
    expect(res['tokens'] as num, greaterThan(100));
    expect(res['budget'], 100);
  }, skip: _pythonAvailable() ? false : 'python3 not available');

  test('apply writes a durable context card', () async {
    writeApp();
    final res = await cx.apply('demo', budget: 100);
    expect(res['has_app'], isTrue);
    expect(res['card'], isNotNull, reason: res.toString());
    expect(
        Directory('${repo.path}/apps/demo/.adf-context').existsSync(), isTrue);
  }, skip: _pythonAvailable() ? false : 'python3 not available');

  test('autoCompactIfNeeded compacts when over budget', () async {
    writeApp();
    final res = await cx.autoCompactIfNeeded('demo', budget: 100);
    expect(res['did'], isTrue, reason: res.toString());
  }, skip: _pythonAvailable() ? false : 'python3 not available');

  test('autoCompactIfNeeded is a no-op under budget', () async {
    writeApp();
    final res = await cx.autoCompactIfNeeded('demo', budget: 1000000);
    expect(res['did'], isFalse);
    expect(
        Directory('${repo.path}/apps/demo/.adf-context').existsSync(), isFalse);
  }, skip: _pythonAvailable() ? false : 'python3 not available');
}
