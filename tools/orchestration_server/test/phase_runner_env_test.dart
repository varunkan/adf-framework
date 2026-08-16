import 'package:orchestration_server/phase_runner.dart';
import 'package:test/test.dart';

// MAINTAINER NOTE: Update _canonicalKeys whenever you add a new key to
// NON_INTERACTIVE_ENV in scripts/orch/agent_runner.py. This list is the
// enforcement contract between the Python SSOT and the Dart mirror.
const List<String> _canonicalKeys = [
  'CI',
  'NO_COLOR',
  'TERM',
  'PAGER',
  'GIT_PAGER',
  'MANPAGER',
  'GIT_TERMINAL_PROMPT',
  'GIT_EDITOR',
  'GCM_INTERACTIVE',
  'DEBIAN_FRONTEND',
  'PYTHONUNBUFFERED',
  'PIP_NO_INPUT',
  'PIP_DISABLE_PIP_VERSION_CHECK',
  'PIP_PROGRESS_BAR',
  'npm_config_yes',
  'npm_config_audit',
  'npm_config_fund',
  'npm_config_progress',
  'npm_config_update_notifier',
  'ADBLOCK',
  'HOMEBREW_NO_AUTO_UPDATE',
];

void main() {
  group('PhaseRunner.nonInteractiveEnv', () {
    test('contains every key in the Python NON_INTERACTIVE_ENV canonical set',
        () {
      for (final key in _canonicalKeys) {
        expect(
          PhaseRunner.nonInteractiveEnv,
          containsPair(key, isNotEmpty),
          reason: 'Missing key: $key — add it to nonInteractiveEnv in '
              'phase_runner.dart (Python SSOT: scripts/orch/agent_runner.py)',
        );
      }
    });

    test('canonical set has the expected size (update when Python SSOT grows)',
        () {
      expect(_canonicalKeys.length, 21,
          reason: 'Update this count and _canonicalKeys when the Python '
              'NON_INTERACTIVE_ENV gains new keys');
    });
  });
}
