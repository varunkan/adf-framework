import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'claude_child_env.dart';
import 'cost_meter.dart';
import 'feature_store.dart';
import 'runner_health.dart';

/// Headless runner-backed conversational dashboard chat.
class AgentChatRunner {
  AgentChatRunner({
    required this.repoRoot,
    RunnerHealth? healthParam,
  }) : health = healthParam ?? RunnerHealth(repoRoot: repoRoot);

  final String repoRoot;
  final RunnerHealth health;
  late final CostMeter _costs = CostMeter(FeatureStore(repoRoot));

  static Duration get chatTimeout {
    final sec =
        int.tryParse(Platform.environment['ORCH_CHAT_TIMEOUT_SEC'] ?? '120') ??
            120;
    return Duration(seconds: sec.clamp(30, 300));
  }

  Future<AgentChatResponse?> converse({
    required String featureId,
    required String contextBlock,
    required String userMessage,
    List<Map<String, dynamic>> recentMessages = const [],
    void Function(String partialText)? onPartial,
  }) async {
    final agent = health.backend.resolveExecutable();
    if (agent == null) return null;

    await health.killStalePrintAgents();

    final history = StringBuffer();
    for (final m in recentMessages.takeLast(6)) {
      final role = m['role'] as String? ?? 'user';
      if (role != 'user' && role != 'assistant') continue;
      var text = (m['text'] as String? ?? '').trim();
      if (text.isEmpty) continue;
      if (text.startsWith('Thinking')) continue;
      if (m['llm_source'] == 'pending') continue;
      if (text.length > 400) text = '${text.substring(0, 400)}…';
      history.writeln('${role.toUpperCase()}: $text');
    }

    final prompt = "You are the ADF orchestration assistant.\n"
        "Feature: $featureId\n\n"
        "$contextBlock\n\n"
        "${history.isEmpty ? '' : 'Recent chat:\n$history\n'}"
        "Answer the user naturally in 2-5 sentences. Use markdown if helpful.\n"
        "End with exactly one line: [ACTION:answer_only] or [ACTION:resume] or "
        "[ACTION:sync] or [ACTION:clarify]\n\n"
        "User: $userMessage";

    final args = health.backend.streamArgs(prompt, repoRoot, partial: true);

    Process? proc;
    String? fullResult;
    final streamed = StringBuffer();
    try {
      proc = await Process.start(agent, args,
          workingDirectory: repoRoot,
          // Bill the dashboard-chat claude -p on the $0 subscription, not the
          // paid API. This spawn previously inherited the raw server env (so it
          // leaked ANTHROPIC_API_KEY and skipped the nested-session scrub).
          environment: claudeChildEnvFromParent(
              claudeBackend: health.backend.buildsAppDirectly),
          includeParentEnvironment: false);
      final stdoutDone = proc.stdout
          .transform(utf8.decoder)
          .transform(const LineSplitter())
          .listen((line) {
        if (line.trim().isEmpty) return;
        try {
          final obj = jsonDecode(line) as Map<String, dynamic>;
          final type = obj['type'] as String?;
          if (type == 'result') {
            _costs.recordFromResultEvent(featureId, obj);
            final t = obj['result'] as String?;
            if (t != null && t.trim().isNotEmpty) fullResult = t.trim();
          } else if (type == 'assistant' ||
              type == 'text' ||
              type == 'message') {
            final t = _extractText(obj);
            if (t != null && t.isNotEmpty) {
              streamed.write(t);
              onPartial?.call(streamed.toString());
            }
          }
        } catch (_) {
          streamed.write(line);
        }
      });

      final code = await proc.exitCode.timeout(
        chatTimeout,
        onTimeout: () {
          try {
            proc?.kill(ProcessSignal.sigkill);
          } catch (_) {}
          return -1;
        },
      );
      await stdoutDone.cancel();

      final text = (fullResult ?? streamed.toString()).trim();
      if (text.isEmpty) return null;
      if (code != 0 && fullResult == null && streamed.length < 20) return null;
      return _parseReply(text);
    } catch (_) {
      try {
        proc?.kill(ProcessSignal.sigkill);
      } catch (_) {}
      final partial = (fullResult ?? streamed.toString()).trim();
      if (partial.length >= 20) return _parseReply(partial);
      return null;
    }
  }

  String? _extractText(Map<String, dynamic> obj) {
    if (obj['text'] is String) return obj['text'] as String;
    final msg = obj['message'];
    if (msg is Map) {
      final content = msg['content'];
      if (content is List) {
        final buf = StringBuffer();
        for (final block in content) {
          if (block is Map &&
              block['type'] == 'text' &&
              block['text'] is String) {
            buf.write(block['text']);
          }
        }
        if (buf.isNotEmpty) return buf.toString();
      }
    }
    final delta = obj['delta'];
    if (delta is Map && delta['text'] is String) return delta['text'] as String;
    return null;
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
