import 'dart:io';

import 'package:orchestration_server/app_runner.dart';
import 'package:test/test.dart';

/// `python3` must be on PATH for the live-app tests; skip cleanly if absent.
bool _pythonAvailable() {
  try {
    return Process.runSync('python3', ['--version']).exitCode == 0;
  } catch (_) {
    return false;
  }
}

const _portAwareServer = '''
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *a):
        pass


def make_server(port=0):
    return ThreadingHTTPServer(("127.0.0.1", port), H)


if __name__ == "__main__":
    make_server(int(os.environ.get("PORT", "8000"))).serve_forever()
''';

void main() {
  late Directory repo;
  late AppRunner runner;
  const id = 'app-runner-test';

  setUp(() {
    repo = Directory.systemTemp.createTempSync('adf-apprun');
    runner = AppRunner(repo.path);
  });

  tearDown(() {
    runner.stopAll();
    if (repo.existsSync()) repo.deleteSync(recursive: true);
  });

  void writeApp(String body) {
    final d = Directory('${repo.path}/apps/$id')..createSync(recursive: true);
    File('${d.path}/server.py').writeAsStringSync(body);
  }

  test('hasApp is false without server.py, true with it', () {
    expect(runner.hasApp(id), isFalse);
    writeApp(_portAwareServer);
    expect(runner.hasApp(id), isTrue);
  });

  test('ensureRunning reports no_app when nothing is built', () async {
    final res = await runner.ensureRunning(id);
    expect(res['available'], isFalse);
    expect(res['status'], 'no_app');
  });

  test('ensureRunning launches a PORT-aware app, serves it, idempotent',
      () async {
    writeApp(_portAwareServer);
    final res = await runner.ensureRunning(id);
    expect(res['available'], isTrue, reason: res.toString());
    final url = res['url'] as String;
    expect(url, startsWith('http://127.0.0.1:'));

    // It actually serves over HTTP.
    final client = HttpClient();
    final req = await client.getUrl(Uri.parse(url));
    final resp = await req.close();
    expect(resp.statusCode, 200);
    client.close(force: true);

    // Second call is idempotent — same live process / port.
    final res2 = await runner.ensureRunning(id);
    expect(res2['port'], res['port']);

    // Restart yields a fresh, serving instance.
    final res3 = await runner.restart(id);
    expect(res3['available'], isTrue, reason: res3.toString());
    expect(res3['url'], startsWith('http://127.0.0.1:'));
  }, skip: _pythonAvailable() ? false : 'python3 not available');

  test('stop reaps the process so ensureRunning relaunches', () async {
    writeApp(_portAwareServer);
    final res = await runner.ensureRunning(id);
    expect(res['available'], isTrue);
    await runner.stop(id);
    final relaunched = await runner.ensureRunning(id);
    expect(relaunched['available'], isTrue, reason: relaunched.toString());
  }, skip: _pythonAvailable() ? false : 'python3 not available');
}
