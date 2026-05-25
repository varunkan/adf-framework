import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'runner_health.dart';

/// Headless cursor-agent for conversational dashboard chat (Cursor-like replies).
class AgentChatRunner {
  AgentChatRunner({
    required this.repoRoot,
    RunnerHealth? healthParam,
  }) : health = healthParam ?? RunnerHealth(repoRoot: repoRoot);

  final String repoRoot;
  final RunnerHealth health;

  static const Duration chatTimeout = Duration(seconds: 120);

  Future<AgentChatResponse?> converse({
    required String featureId,
    required String contextBlock,
    required String userMessage,
    List<Map<String, dynamic>> recentMessages = const [],
  }) async {
    final agent = health.resolveCursorAgent();
    if (agent == null) return null;

    final history = StringBuffer();
    for (final m in recentMessages.takeLast(8)) {
      final role = m['role'] as String? ?? 'user';
      final text = (m['text'] as String? ?? '').trim();
      if (text.isEmpty) continue;
      history.writeln('${role.toUpperCase()}: $text');
    }

    final prompt = '''You are the ADF v3 orchestration assistant in the POS development dashboard.
Feature id: $featureId

$contextBlock

${history.isEmpty ? '' : 'Recent chat:\n$history\n'}
Respond naturally to the user — like Cursor IDE chat. Be specific, helpful, and concise.
Use the feature context above; do not invent URLs or paths not listed.

End your reply with exactly one line (required):
[ACTION:answer_only] — questions only, no code/agent work
[ACTION:resume] — continue orchestration / implement / clarify requirements
[ACTION:sync] — user approved; sync phase gates
[ACTION:clarify] — user added requirements to capture

User message:
$userMessage''';

    final args = <String>[
      '--print',
      '--trust',
      '--workspace',
      repoRoot,
      '--output-format',
      'text',
      prompt,
    ];
    final apiKey = Platform.environment['CURSOR_API_KEY'];
    if (apiKey != null && apiKey.isNotEmpty) {
      args.insertAll(0, ['--api-key', apiKey]);
    }

    Process? proc;
    final out = StringBuffer();
    final err = StringBuffer();
    try {
      proc = await Process.start(
        agent,
        args,
        workingDirectory: repoRoot,
      );
      final subOut = proc.stdout.transform(utf8.decoder).listen(out.write);
      final subErr = proc.stderr.transform(utf8.decoder).listen(err.write);
      final code = await proc.exitCode.timeout(
        chatTimeout,
        onTimeout: () {
          try {
            proc?.kill(ProcessSignal.sigkill);
          } catch (_) {}
          return -1;
        },
      );
      await subOut.cancel();
      await subErr.cancel();
      if (code != 0) return null;
      final text = out.toString().trim();
      if (text.isEmpty) return null;
      return _parseReply(text);
    } catch (_) {
      try {
        proc?.kill(ProcessSignal.sigkill);
      } catch (_) {}
      return null;
    }
  }

  AgentChatResponse _parseReply(String raw) {
    var text = raw.trim();
    var action = 'answer_only';
    final tag = RegExp(r'\[ACTION:(\w+)\]\s*$', caseSensitive: false)
        .firstMatch(text);
    if (tag != null) {
      action = tag.group(1)!.toLowerCase();
      text = text.substring(0, tag.start).trim();
    }
    return AgentChatResponse(reply: text, actionTag: action);
  }
}

class AgentChatResponse {
  AgentChatResponse({required this.reply, required this.actionTag});

  final String reply;
  final String actionTag;
}

extension _TakeLast<E> on List<E> {
  Iterable<E> takeLast(int n) {
    if (length <= n) return this;
    return sublist(length - n);
  }
}
