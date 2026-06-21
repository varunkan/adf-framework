import 'dart:io';

import 'package:orchestration_server/orchestration_paths.dart';
import 'package:test/test.dart';

void main() {
  test('hasOrchestrationAt detects legacy .cursor path', () {
    final tmp = Directory.systemTemp.createTempSync('orch_paths_');
    Directory('${tmp.path}/.cursor/orchestration').createSync(recursive: true);
    expect(OrchestrationPaths.hasOrchestrationAt(tmp.path), isTrue);
    tmp.deleteSync(recursive: true);
  });

  test('OrchestrationPaths resolves feature rel paths', () {
    final tmp = Directory.systemTemp.createTempSync('orch_paths2_');
    Directory('${tmp.path}/.cursor/orchestration/features/x').createSync(recursive: true);
    final paths = OrchestrationPaths(tmp.path);
    expect(paths.featureRel('x', 'state.json'), contains('features/x/state.json'));
    tmp.deleteSync(recursive: true);
  });

  // ---- CURSOR-6: .adf is the default; .cursor is a no-loss fallback ----------
  group('CURSOR-6 orchestration dir', () {
    test('C11: a fresh repo defaults to .adf/orchestration', () {
      final tmp = Directory.systemTemp.createTempSync('orch_c11_');
      expect(OrchestrationPaths(tmp.path).orchestrationRoot,
          endsWith('.adf/orchestration'));
      tmp.deleteSync(recursive: true);
    });

    test('C11: legacy .cursor still resolves when .adf is absent', () {
      final tmp = Directory.systemTemp.createTempSync('orch_c11b_');
      Directory('${tmp.path}/.cursor/orchestration').createSync(recursive: true);
      expect(OrchestrationPaths(tmp.path).orchestrationRoot,
          endsWith('.cursor/orchestration'));
      tmp.deleteSync(recursive: true);
    });

    test('C11: .adf wins over .cursor when both exist', () {
      final tmp = Directory.systemTemp.createTempSync('orch_c11c_');
      Directory('${tmp.path}/.cursor/orchestration').createSync(recursive: true);
      Directory('${tmp.path}/.adf/orchestration').createSync(recursive: true);
      expect(OrchestrationPaths(tmp.path).orchestrationRoot,
          endsWith('.adf/orchestration'));
      tmp.deleteSync(recursive: true);
    });

    test('C12: migrateLegacyIfNeeded copies features with ZERO loss + idempotent',
        () {
      final tmp = Directory.systemTemp.createTempSync('orch_c12_');
      for (final f in ['feat-a', 'feat-b']) {
        final d = Directory('${tmp.path}/.cursor/orchestration/features/$f')
          ..createSync(recursive: true);
        File('${d.path}/state.json').writeAsStringSync('{"feature_id":"$f"}');
      }
      expect(OrchestrationPaths.migrateLegacyIfNeeded(tmp.path), isTrue);
      // migrated, no loss
      for (final f in ['feat-a', 'feat-b']) {
        final mf = File('${tmp.path}/.adf/orchestration/features/$f/state.json');
        expect(mf.existsSync(), isTrue, reason: '$f migrated to .adf');
        expect(mf.readAsStringSync(), contains(f));
      }
      // non-destructive: legacy kept as backup
      expect(
          Directory('${tmp.path}/.cursor/orchestration/features/feat-a')
              .existsSync(),
          isTrue);
      // count preserved
      final inCount = Directory('${tmp.path}/.cursor/orchestration/features')
          .listSync()
          .length;
      final outCount =
          Directory('${tmp.path}/.adf/orchestration/features').listSync().length;
      expect(outCount, inCount);
      // idempotent: .adf now exists → no-op
      expect(OrchestrationPaths.migrateLegacyIfNeeded(tmp.path), isFalse);
      tmp.deleteSync(recursive: true);
    });
  });
}
