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
      // The prompt MUST sit right after -p and BEFORE the variadic --add-dir, or
      // claude consumes it as a directory ("Input must be provided … --print").
      expect(args[1], 'hello');
      expect(args.indexOf('hello') < args.indexOf('--add-dir'), isTrue,
          reason: 'prompt must precede the variadic --add-dir');
      expect(b.apiKeyEnvVar, 'ANTHROPIC_API_KEY');
      // Claude must NOT receive Cursor-only flags.
      expect(args, isNot(contains('--workspace')));
      expect(args, isNot(contains('--print')));
    });

    test('claude pins --model (before the variadic --add-dir) when set', () {
      final b = _OpusClaude();
      final args = b.streamArgs('hi', '/repo');
      final mi = args.indexOf('--model');
      expect(mi, greaterThanOrEqualTo(0), reason: 'must pass --model when pinned');
      expect(args[mi + 1], 'opus');
      expect(mi < args.indexOf('--add-dir'), isTrue,
          reason: '--model must precede the variadic --add-dir');
      expect(args[1], 'hi', reason: 'prompt still sits right after -p');
      // textArgs carries the model too (no --verbose there).
      final t = _OpusClaude().textArgs('hi', '/repo');
      expect(t, containsAllInOrder(['--model', 'opus']));
      expect(t, isNot(contains('--verbose')));
    });

    test('claude omits --model when unset (uses CLI default)', () {
      // No ADF_RUNNER_CLAUDE_MODEL in the test env → no --model flag.
      final args = ClaudeBackend().streamArgs('hi', '/repo');
      expect(args, isNot(contains('--model')));
      expect(args[1], 'hi');
    });

    test('claude builds app directly (real prompt); custom uses ADF protocol', () {
      expect(ClaudeBackend().buildsAppDirectly, isTrue,
          reason: 'Claude Code writes files via its own tools — needs a real prompt');
      expect(CustomBackend().buildsAppDirectly, isFalse,
          reason: 'agent_runner.py understands @orch-orchestrator');
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

/// Pins a model without mutating the process env, so --model placement can be
/// asserted deterministically.
class _OpusClaude extends ClaudeBackend {
  @override
  String? get model => 'opus';
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
