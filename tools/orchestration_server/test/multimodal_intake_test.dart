import 'package:test/test.dart';

// normalizeIntakeSources + sanitizeUploadFilename are the importable, pure
// pieces of G18's POST /features intake logic. They live in bin/server.dart (a
// bin entry-point), imported here via relative path. The full HTTP routes
// (POST /features, POST /features/<id>/upload) are exercised by the server E2E
// (scripts/orch/e2e_server.sh); this file pins the normalization + filename
// sanitization contracts without booting a server.
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
}
