import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:orchestration_server/feature_store.dart';
import 'package:test/test.dart';

// normalizeIntakeSources + sanitizeUploadFilename + extractDispositionFilename
// are the importable, pure pieces of G18's intake logic. They live in
// bin/server.dart (a bin entry-point), imported here via relative path. The pure
// unit groups below pin the normalization + filename-sanitization contracts.
//
// The HTTP routes are exercised at two levels:
//   - POST /features (create-with-sources) is covered by scripts/orch/e2e_server.sh.
//   - POST /features/<id>/upload (multipart) is NOT covered by e2e_server.sh —
//     that script only drives the create path. The "G18 — POST upload over HTTP"
//     group below boots the real server on an ephemeral port and drives the
//     actual upload route end-to-end (RED-2 200 + on-disk file + sources.json,
//     RED-3 non-multipart 400, path-traversal rejection, unknown-id 404).
import '../bin/server.dart';

void main() {
  group('G18 — normalizeIntakeSources', () {
    // RED-1: figma_url and reference_sites must be merged into sources.json.
    test('merges sources[] + figma_url + reference_sites into {url} entries',
        () {
      final out = normalizeIntakeSources({
        'sources': [
          {'url': 'https://x'}
        ],
        'figma_url': 'https://figma.com/file/abc',
        'reference_sites': ['https://fda.gov'],
      });
      // Deep-equality on the whole list (matcher `contains` uses element `==`,
      // which is identity for Map instances).
      expect(out, [
        {'url': 'https://x'},
        {'url': 'https://figma.com/file/abc'},
        {'url': 'https://fda.gov'},
      ]);
    });

    test('reference_sites accepts both bare strings and {url} objects', () {
      final out = normalizeIntakeSources({
        'reference_sites': [
          'https://a.com',
          {'url': 'https://b.com'}
        ],
      });
      expect(out, [
        {'url': 'https://a.com'},
        {'url': 'https://b.com'},
      ]);
    });

    // AC-2 / REQ-8: no new fields → identical to today (only sources[] passed).
    test('with no figma_url/reference_sites, returns only the sources[] entries',
        () {
      final out = normalizeIntakeSources({
        'sources': [
          {'url': 'https://only'}
        ],
      });
      expect(out, [
        {'url': 'https://only'}
      ]);
    });

    test('empty body produces an empty list (caller skips the write)', () {
      expect(normalizeIntakeSources({}), isEmpty);
    });

    // RED-4 / REQ-6: audio[] and repo_path are silently dropped (G09 shim).
    test('drops audio[] and repo_path without error', () {
      final out = normalizeIntakeSources({
        'prompt': 'x',
        'audio': ['file.mp3'],
        'repo_path': '/some/repo',
      });
      expect(out, isEmpty);
      expect(out.any((e) => '$e'.contains('.mp3')), isFalse);
      expect(out.any((e) => '$e'.contains('/some/repo')), isFalse);
    });

    test('passes through {path} doc entries unchanged', () {
      final out = normalizeIntakeSources({
        'sources': [
          {'path': '/tmp/doc.pdf'}
        ],
      });
      expect(out, [
        {'path': '/tmp/doc.pdf'}
      ]);
    });
  });

  group('G18 — sanitizeUploadFilename (path-traversal defense, AC-7)', () {
    test('strips directory components from a traversal filename', () {
      expect(sanitizeUploadFilename('../../etc/passwd'), 'passwd');
      expect(sanitizeUploadFilename('/abs/path/report.pdf'), 'report.pdf');
      expect(sanitizeUploadFilename('plain.pdf'), 'plain.pdf');
    });

    test('rejects empty / dot-only basenames', () {
      expect(sanitizeUploadFilename(null), isNull);
      expect(sanitizeUploadFilename(''), isNull);
      expect(sanitizeUploadFilename('   '), isNull);
      expect(sanitizeUploadFilename('..'), isNull);
      expect(sanitizeUploadFilename('.'), isNull);
    });
  });

  group('G18 — extractDispositionFilename (RFC 6266 / RFC 5987)', () {
    test('plain quoted filename', () {
      expect(
          extractDispositionFilename(
              'form-data; name="file"; filename="report.pdf"'),
          'report.pdf');
    });

    test('RFC 5987 extended filename* (UTF-8 percent-encoded) is decoded', () {
      // résumé.pdf percent-encoded as UTF-8.
      expect(
          extractDispositionFilename(
              "form-data; name=\"file\"; filename*=UTF-8''r%C3%A9sum%C3%A9.pdf"),
          'résumé.pdf');
    });

    test('filename* is PREFERRED over a plain filename when both are present',
        () {
      expect(
          extractDispositionFilename(
              'form-data; name="file"; filename="fallback.pdf"; '
              "filename*=UTF-8''pr%C3%A9f%C3%A9r%C3%A9.pdf"),
          'préféré.pdf');
    });

    test('no filename parameter → null', () {
      expect(extractDispositionFilename('form-data; name="text"'), isNull);
    });

    test('extended filename* feeds through sanitize to strip traversal', () {
      // ../../etc/passwd percent-encoded; sanitize must reduce it to the basename.
      final raw = extractDispositionFilename(
          "form-data; name=\"file\"; filename*=UTF-8''..%2F..%2Fetc%2Fpasswd");
      expect(raw, '../../etc/passwd');
      expect(sanitizeUploadFilename(raw), 'passwd');
    });
  });

  // RED-2 / RED-3 / AC-3..AC-7: the upload route over a REAL socket. Boots the
  // server on an ephemeral port (ORCH_PORT=0) and drives multipart POSTs. These
  // FAIL today if the route or its multipart handling regresses (the pure unit
  // groups above cannot catch an unwired route — only this group does).
  group('G18 — POST /features/<id>/upload over HTTP', () {
    late String repoRoot;
    late FeatureStore store;
    late Process server;
    late int port;
    final createdIds = <String>[];

    String findRepoRoot() {
      var dir = Directory.current.path;
      while (!Directory('$dir/.cursor/orchestration').existsSync()) {
        final parent = Directory(dir).parent;
        if (parent.path == dir) throw StateError('repo root not found');
        dir = parent.path;
      }
      return dir;
    }

    setUpAll(() async {
      repoRoot = findRepoRoot();
      store = FeatureStore(repoRoot);
      server = await Process.start(
        'dart',
        ['run', 'bin/server.dart'],
        environment: {
          'ORCH_PORT': '0',
          'ORCH_REPO_ROOT': repoRoot,
          'ORCH_AUTO_RUNNER': 'false',
          'ORCH_AUTO_AUTOPILOT': 'false',
        },
        workingDirectory: '$repoRoot/tools/orchestration_server',
      );
      final portCompleter = Completer<int>();
      server.stdout
          .transform(utf8.decoder)
          .transform(const LineSplitter())
          .listen((line) {
        final m = RegExp(r'http://127\.0\.0\.1:(\d+)').firstMatch(line);
        if (m != null && !portCompleter.isCompleted) {
          portCompleter.complete(int.parse(m.group(1)!));
        }
      });
      server.stderr.transform(utf8.decoder).listen((_) {});
      port = await portCompleter.future
          .timeout(const Duration(seconds: 60), onTimeout: () {
        throw StateError('server did not print its port within 60s');
      });
    });

    tearDownAll(() async {
      server.kill(ProcessSignal.sigterm);
      await server.exitCode
          .timeout(const Duration(seconds: 10), onTimeout: () => -1);
      for (final id in createdIds) {
        if (store.featureExists(id)) {
          Directory(store.featurePath(id)).deleteSync(recursive: true);
        }
        final up = Directory('$repoRoot/.adf-uploads/$id');
        if (up.existsSync()) up.deleteSync(recursive: true);
        final specDir = Directory('$repoRoot/specs/$id');
        if (specDir.existsSync()) specDir.deleteSync(recursive: true);
      }
    });

    Future<String> createFeature() async {
      final client = HttpClient();
      try {
        final req = await client
            .postUrl(Uri.parse('http://127.0.0.1:$port/features'));
        req.headers.contentType = ContentType.json;
        req.add(utf8.encode(jsonEncode({
          'requirement': 'Build a URL shortener with a web page.',
          'track': 'S',
          'stack': 'stdlib',
        })));
        final resp = await req.close();
        expect(resp.statusCode, 201);
        final payload =
            jsonDecode(await resp.transform(utf8.decoder).join()) as Map;
        final id = payload['id'] as String;
        createdIds.add(id);
        return id;
      } finally {
        client.close(force: false);
      }
    }

    /// Build a minimal multipart/form-data body with one file part. [filename]
    /// is placed verbatim into the Content-Disposition header.
    List<int> multipartBody(String boundary, String filename, List<int> bytes) {
      final head = '--$boundary\r\n'
          'Content-Disposition: form-data; name="file"; filename="$filename"\r\n'
          'Content-Type: application/octet-stream\r\n\r\n';
      final tail = '\r\n--$boundary--\r\n';
      return [...utf8.encode(head), ...bytes, ...utf8.encode(tail)];
    }

    // RED-2 / AC-3: multipart upload → 200 {appended:1}, file on disk, sources.json.
    test('multipart upload saves the file and appends a {path} to sources.json',
        () async {
      final id = await createFeature();
      const boundary = 'adfBoundaryRED2';
      final pdfBytes = utf8.encode('%PDF-1.4 fake pdf body\n');
      final body = multipartBody(boundary, 'spec.pdf', pdfBytes);

      final client = HttpClient();
      try {
        final req = await client
            .postUrl(Uri.parse('http://127.0.0.1:$port/features/$id/upload'));
        req.headers.set(HttpHeaders.contentTypeHeader,
            'multipart/form-data; boundary=$boundary');
        req.add(body);
        final resp = await req.close();
        final respBody = await resp.transform(utf8.decoder).join();
        expect(resp.statusCode, 200, reason: respBody);
        expect(jsonDecode(respBody), {'appended': 1});
      } finally {
        client.close(force: false);
      }

      // (a) file saved under .adf-uploads/<id>/
      final saved = File('$repoRoot/.adf-uploads/$id/spec.pdf');
      expect(saved.existsSync(), isTrue,
          reason: 'uploaded file must be written under .adf-uploads/<id>/');
      expect(saved.readAsBytesSync(), pdfBytes);

      // (b) sources.json updated with a {path} entry pointing at the saved file.
      final srcFile =
          File('$repoRoot/${store.paths.featureRel(id, 'sources.json')}');
      expect(srcFile.existsSync(), isTrue);
      final srcs = jsonDecode(srcFile.readAsStringSync()) as List;
      expect(srcs.any((e) => e is Map && e['path'] == saved.absolute.path),
          isTrue,
          reason: 'sources.json must contain the saved file as a {path} entry');
    });

    // AC-7 / path-traversal: a `../../etc/passwd` filename is written by basename
    // only — never outside the per-feature upload dir.
    test('path-traversal filename is reduced to its basename at the HTTP layer',
        () async {
      final id = await createFeature();
      const boundary = 'adfBoundaryTraversal';
      final body =
          multipartBody(boundary, '../../etc/passwd', utf8.encode('x'));

      final client = HttpClient();
      try {
        final req = await client
            .postUrl(Uri.parse('http://127.0.0.1:$port/features/$id/upload'));
        req.headers.set(HttpHeaders.contentTypeHeader,
            'multipart/form-data; boundary=$boundary');
        req.add(body);
        final resp = await req.close();
        final respBody = await resp.transform(utf8.decoder).join();
        expect(resp.statusCode, 200, reason: respBody);
      } finally {
        client.close(force: false);
      }

      // Written as the basename inside the per-feature dir.
      expect(File('$repoRoot/.adf-uploads/$id/passwd').existsSync(), isTrue);
      // The traversal target the filename would have escaped to (two levels up
      // from the upload dir, i.e. <repoRoot>/etc/passwd) is NOT created.
      expect(File('$repoRoot/etc/passwd').existsSync(), isFalse,
          reason: 'sanitize must prevent the upload escaping its feature dir');
    });

    // RED-3 / AC-4: a non-multipart (application/json) body → 400, no sources.json.
    test('non-multipart body returns 400 and does not modify sources.json',
        () async {
      final id = await createFeature();
      final srcFile =
          File('$repoRoot/${store.paths.featureRel(id, 'sources.json')}');
      final before = srcFile.existsSync() ? srcFile.readAsStringSync() : null;

      final client = HttpClient();
      try {
        final req = await client
            .postUrl(Uri.parse('http://127.0.0.1:$port/features/$id/upload'));
        req.headers.contentType = ContentType.json;
        req.add(utf8.encode('{}'));
        final resp = await req.close();
        final respBody = await resp.transform(utf8.decoder).join();
        expect(resp.statusCode, 400, reason: respBody);
      } finally {
        client.close(force: false);
      }

      final after = srcFile.existsSync() ? srcFile.readAsStringSync() : null;
      expect(after, before, reason: 'a rejected upload must not touch sources.json');
    });

    // AC-6: unknown feature id → 404 and no upload dir is created.
    test('upload to an unknown feature id returns 404', () async {
      const id = 'g18-unknown-feature-id-xyz';
      const boundary = 'adfBoundary404';
      final body = multipartBody(boundary, 'x.pdf', utf8.encode('x'));

      final client = HttpClient();
      try {
        final req = await client
            .postUrl(Uri.parse('http://127.0.0.1:$port/features/$id/upload'));
        req.headers.set(HttpHeaders.contentTypeHeader,
            'multipart/form-data; boundary=$boundary');
        req.add(body);
        final resp = await req.close();
        final respBody = await resp.transform(utf8.decoder).join();
        expect(resp.statusCode, 404, reason: respBody);
      } finally {
        client.close(force: false);
      }
      expect(Directory('$repoRoot/.adf-uploads/$id').existsSync(), isFalse,
          reason: 'no upload dir for an unknown feature');
    });
  });
}
