import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../main.dart';
import '../services/api_client.dart';

/// Identity of the active runner backend, derived from `/runner/health`.
/// Falls back to Cursor wording when the server predates the `runner` field.
class _RunnerIdentity {
  _RunnerIdentity(Map<String, dynamic> health)
      : id = health['runner'] as String? ?? 'cursor',
        _label = health['runner_label'] as String?,
        _login = health['login_command'] as String?;

  final String id;
  final String? _label;
  final String? _login;

  String get label =>
      _label ??
      switch (id) {
        'claude' => 'Claude Code CLI (claude)',
        'custom' => 'Custom agent CLI',
        _ => 'Cursor CLI (cursor-agent)',
      };

  String? get loginCommand =>
      _login ??
      switch (id) {
        'claude' => 'claude login',
        'custom' => null,
        _ => 'cursor-agent login',
      };

  List<String> get fallbackSteps => [
        if (loginCommand != null)
          'In Terminal: $loginCommand (complete sign-in if prompted)',
        if (id == 'cursor') 'Or add CURSOR_API_KEY to ~/.cursor/agent.env',
        if (id == 'claude') 'Or export ANTHROPIC_API_KEY in your environment',
        if (id == 'custom')
          'Set ADF_RUNNER_BIN / ADF_RUNNER_ARGS in .adf/runner.env',
        'Restart API: dart run tools/orchestration_server/bin/server.dart',
        'Tap Verify below, then Start pipeline',
      ];
}

class RunnerSetupCard extends StatelessWidget {
  const RunnerSetupCard({
    super.key,
    required this.health,
    required this.onVerify,
    this.onRetry,
  });

  final Map<String, dynamic> health;
  final VoidCallback onVerify;
  final VoidCallback? onRetry;

  bool get ready => health['ready'] == true;

  bool get headlessReady => health['headless_ready'] == true;

  @override
  Widget build(BuildContext context) {
    final runner = _RunnerIdentity(health);

    if (ready && headlessReady) {
      return Card(
        color: Colors.green.shade50,
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Row(
            children: [
              Icon(Icons.check_circle, color: Colors.green.shade700),
              const SizedBox(width: 12),
              Expanded(
                child: Text(
                  '${runner.label} ready (${health['agent_path'] ?? 'authenticated'})',
                  style: TextStyle(color: Colors.green.shade900),
                ),
              ),
            ],
          ),
        ),
      );
    }

    if (ready && !headlessReady) {
      final hint = health['headless_hint'] as String? ??
          'Headless probe failed — run the phase in your IDE, then Sync here.';
      return Card(
        color: Colors.amber.shade50,
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Icon(Icons.info_outline, color: Colors.amber.shade900),
              const SizedBox(width: 12),
              Expanded(
                child: Text(
                  'IDE mode: logged in, but headless `--print` is unavailable.\n$hint',
                  style: TextStyle(color: Colors.amber.shade900, fontSize: 13),
                ),
              ),
            ],
          ),
        ),
      );
    }

    final steps = (health['recovery_steps'] as List<dynamic>?)
            ?.map((e) => e.toString())
            .toList() ??
        runner.fallbackSteps;

    return Card(
      color: Colors.red.shade50,
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(Icons.warning_amber, color: Colors.red.shade800),
                const SizedBox(width: 8),
                Text(
                  '${runner.label} setup required',
                  style: TextStyle(
                    fontWeight: FontWeight.bold,
                    color: Colors.red.shade900,
                  ),
                ),
              ],
            ),
            if (health['hint'] != null) ...[
              const SizedBox(height: 8),
              Text(health['hint'] as String),
            ],
            const SizedBox(height: 12),
            ...steps.asMap().entries.map(
              (e) => Padding(
                padding: const EdgeInsets.only(bottom: 4),
                child: Text('${e.key + 1}. ${e.value}'),
              ),
            ),
            if (runner.id == 'cursor') ...[
              const SizedBox(height: 8),
              const Text(
                'Quick setup (Terminal):',
                style: TextStyle(fontWeight: FontWeight.w600, fontSize: 13),
              ),
              const SizedBox(height: 4),
              const SelectableText(
                './scripts/orch/setup_cursor_runner.sh',
                style: TextStyle(fontFamily: 'monospace', fontSize: 12),
              ),
            ],
            const SizedBox(height: 12),
            Wrap(
              spacing: 8,
              children: [
                if (runner.loginCommand != null)
                  OutlinedButton.icon(
                    onPressed: () async {
                      await Clipboard.setData(
                        ClipboardData(text: runner.loginCommand!),
                      );
                      if (context.mounted) {
                        showMessage(
                          context,
                          'Copied. Paste in Terminal to sign in.',
                        );
                      }
                    },
                    icon: const Icon(Icons.copy, size: 18),
                    label: const Text('Copy login command'),
                  ),
                FilledButton.icon(
                  onPressed: onVerify,
                  icon: const Icon(Icons.verified_user, size: 18),
                  label: const Text('Verify'),
                ),
                if (onRetry != null)
                  OutlinedButton(
                    onPressed: onRetry,
                    child: const Text('Retry run'),
                  ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

/// Loads runner health for list screen chip.
class RunnerHealthLoader extends StatefulWidget {
  const RunnerHealthLoader({super.key, required this.api});

  final ApiClient api;

  @override
  State<RunnerHealthLoader> createState() => _RunnerHealthLoaderState();
}

class _RunnerHealthLoaderState extends State<RunnerHealthLoader> {
  Map<String, dynamic>? _health;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final h = await widget.api.getRunnerHealth();
      if (mounted) setState(() => _health = h);
    } catch (_) {}
  }

  @override
  Widget build(BuildContext context) {
    if (_health == null) return const SizedBox.shrink();
    final ready = _health!['ready'] == true;
    return Tooltip(
      message: ready
          ? '${_RunnerIdentity(_health!).label} ready'
          : _health!['hint'] as String? ?? 'Setup required',
      child: Icon(
        ready ? Icons.smart_toy : Icons.smart_toy_outlined,
        color: ready ? Colors.greenAccent : Colors.orangeAccent,
        size: 22,
      ),
    );
  }
}
