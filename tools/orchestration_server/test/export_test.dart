import 'dart:io';

import 'package:orchestration_server/exporter.dart';
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
    if (File('${cand.path}/export_app.py').existsSync()) return cand.path;
    dir = dir.parent;
  }
  throw StateError('could not find scripts/orch from ${Directory.current.path}');
}

void main() {
  late Directory repo;
  late Exporter exporter;
  final srcScripts = _repoScriptsOrch();

  setUp(() {
    repo = Directory.systemTemp.createTempSync('adf-export');
    Directory('${repo.path}/scripts/orch').createSync(recursive: true);
    File('$srcScripts/export_app.py')
        .copySync('${repo.path}/scripts/orch/export_app.py');
    final app = Directory('${repo.path}/apps/demo')..createSync(recursive: true);
    File('${app.path}/.adf-proof.json').writeAsStringSync('{"seal":"adf1:x"}');
    Directory('${app.path}/src').createSync();
    File('${app.path}/src/App.tsx').writeAsStringSync('export const App = 1\n');
    exporter = Exporter(repo.path);
  });

  tearDown(() {
    if (repo.existsSync()) repo.deleteSync(recursive: true);
  });

  test('no app -> ok:false', () async {
    final res = await exporter.export('missing', null);
    expect(res['ok'], isFalse);
  });

  test('exports a portable zip embedding the audit bundle', () async {
    final res = await exporter.export('demo', {'format': 'adf-audit-bundle/1'});
    expect(res['ok'], isTrue, reason: res.toString());
    expect(res['files'] as num, greaterThan(0));
    expect(res['bytes'] as num, greaterThan(0));
    expect(File(res['out'] as String).existsSync(), isTrue);
    expect(res['out'], contains('.adf-exports'));
  }, skip: _pythonAvailable() ? false : 'python3 not available');
}
