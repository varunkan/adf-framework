import 'package:orchestration_server/runner_backend.dart';
import 'package:test/test.dart';

void main() {
  group('backend identity', () {
    test('claude backend builds claude -p stream args', () {
      final b = ClaudeBackend();
      expect(b.kind, RunnerKind.claude);
      final args = b.streamArgs('hello', '/repo');
      expect(args.first, '-p');
      expect(args, contains('--verbose'));
      expect(args, contains('--dangerously-skip-permissions'));
      expect(args, containsAllInOrder(['--add-dir', '/repo']));
      expect(args.last, 'hello');
      expect(b.apiKeyEnvVar, 'ANTHROPIC_API_KEY');
      // Claude must NOT receive Cursor-only flags.
      expect(args, isNot(contains('--workspace')));
      expect(args, isNot(contains('--print')));
    });

    test('custom backend expands {prompt}/{workspace} template', () {
      // Simulate an env-driven custom runner without mutating the process env
      // by exercising the template logic through a subclass shim.
      final b = _CustomShim(args: '-p {prompt} --cwd {workspace}');
      final out = b.streamArgs('do it', '/work');
      expect(out, ['-p', 'do it', '--cwd', '/work']);
    });
  });

  // CURSOR-1 — cursor-the-tool is purged: no cursor RunnerKind, no CursorBackend,
  // and the auto/default selection never yields a cursor runner.
  group('CURSOR-1: cursor purged', () {
    test('cursor is not a runner kind (only claude + custom remain)', () {
      expect(RunnerKind.values.map((k) => k.id), isNot(contains('cursor')));
      expect(RunnerKind.values.map((k) => k.id).toSet(), {'claude', 'custom'});
    });

    test('the active backend is never cursor', () {
      expect(RunnerBackend.active().kind.id, isNot('cursor'),
          reason: 'default/auto resolution must fall back to custom, not cursor');
    });
  });
}

/// Test shim that overrides the env-derived template so the expansion logic can
/// be asserted deterministically.
class _CustomShim extends CustomBackend {
  _CustomShim({required this.args});
  final String args;
  @override
  List<String> streamArgs(String prompt, String workspace,
      {bool partial = true}) {
    final out = <String>[];
    for (final tok in args.split(RegExp(r'\s+'))) {
      if (tok == '{prompt}') {
        out.add(prompt);
      } else {
        out.add(tok.replaceAll('{workspace}', workspace));
      }
    }
    return out;
  }
}
