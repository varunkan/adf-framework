import 'dart:io';

import 'package:orchestration_server/claude_child_env.dart';
import 'package:test/test.dart';

// Proves the $0-subscription enforcement: claudeChildEnv removes the paid
// ANTHROPIC_API_KEY from a spawned `claude` child's env WHEN the subscription
// OAuth token is present, without ever stranding a build with no auth — AND that
// the removal actually reaches a real child process (which only works with
// includeParentEnvironment: false).
void main() {
  Map<String, String> base() => {
        'PATH': '/usr/bin',
        'HOME': '/home/x',
        'ANTHROPIC_API_KEY': 'sk-paid-XXXX',
        'CLAUDE_CODE_OAUTH_TOKEN': 'sk-oat-YYYY',
        'CLAUDE_CODE_ENTRYPOINT': 'cli',
        'CLAUDE_AGENT_SDK_VERSION': '1.2.3',
        'CLAUDECODE': '1',
        'ANTHROPIC_BASE_URL': 'http://nested',
        'ADF_FEATURE_ID': 'demo',
      };

  group('claudeChildEnv — pure contract', () {
    test('claude backend + OAuth present: paid key REMOVED, OAuth kept', () {
      final env = claudeChildEnv(base(), claudeBackend: true);
      expect(env.containsKey('ANTHROPIC_API_KEY'), isFalse,
          reason: 'paid key must be absent (not empty) so claude bills the sub');
      expect(env['CLAUDE_CODE_OAUTH_TOKEN'], 'sk-oat-YYYY');
      // ordinary env preserved
      expect(env['PATH'], '/usr/bin');
      expect(env['ADF_FEATURE_ID'], 'demo');
      // nested-session markers stripped
      expect(env.containsKey('CLAUDE_CODE_ENTRYPOINT'), isFalse);
      expect(env.containsKey('CLAUDE_AGENT_SDK_VERSION'), isFalse);
      expect(env.containsKey('CLAUDECODE'), isFalse);
      expect(env.containsKey('ANTHROPIC_BASE_URL'), isFalse);
    });

    test('claude backend + OAuth ABSENT: paid key KEPT (build keeps its auth)',
        () {
      final env = claudeChildEnv(base()..remove('CLAUDE_CODE_OAUTH_TOKEN'),
          claudeBackend: true);
      expect(env['ANTHROPIC_API_KEY'], 'sk-paid-XXXX',
          reason: 'with no OAuth, removing the key would strand the build');
    });

    test('claude backend + EMPTY OAuth: treated as absent, paid key KEPT', () {
      final env = claudeChildEnv(base()..['CLAUDE_CODE_OAUTH_TOKEN'] = '',
          claudeBackend: true);
      expect(env['ANTHROPIC_API_KEY'], 'sk-paid-XXXX');
    });

    test('custom/NVIDIA backend: env untouched (its paid path needs the key)',
        () {
      final env = claudeChildEnv(base(), claudeBackend: false);
      expect(env['ANTHROPIC_API_KEY'], 'sk-paid-XXXX');
      expect(env['CLAUDECODE'], '1'); // not even the nested scrub runs
    });

    test('key is fully removed, never set to empty string', () {
      final env = claudeChildEnv(base(), claudeBackend: true);
      // an empty ANTHROPIC_API_KEY="" would still win precedence and auth-fail
      expect(env['ANTHROPIC_API_KEY'], isNull);
    });
  });

  group('claudeChildEnv — end-to-end through a real child process', () {
    // The whole fix hinges on includeParentEnvironment:false. Prove it against a
    // real spawn: the parent process HAS ANTHROPIC_API_KEY, but the child must
    // NOT see it once scrubbed + passed with includeParentEnvironment:false.
    test('child does NOT see the paid key (the leak the fix closes)', () async {
      final parentLike = Map<String, String>.of(Platform.environment)
        ..['ANTHROPIC_API_KEY'] = 'sk-paid-LEAK'
        ..['CLAUDE_CODE_OAUTH_TOKEN'] = 'sk-oat-OK';
      final scrubbed = claudeChildEnv(parentLike, claudeBackend: true);

      final ok = await Process.run(
          'bash', ['-c', r'printf "%s" "${ANTHROPIC_API_KEY-__UNSET__}"'],
          environment: scrubbed, includeParentEnvironment: false);
      expect(ok.stdout, '__UNSET__',
          reason: 'scrub + includeParentEnvironment:false must keep the key out');

      // OAuth survives so the child still authenticates on the subscription.
      final oauth = await Process.run(
          'bash', ['-c', r'printf "%s" "${CLAUDE_CODE_OAUTH_TOKEN-__UNSET__}"'],
          environment: scrubbed, includeParentEnvironment: false);
      expect(oauth.stdout, 'sk-oat-OK');
    });
  });
}
