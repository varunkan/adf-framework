import 'dart:convert';
import 'dart:io';

import 'orchestration_paths.dart';

export 'orchestration_paths.dart' show resolveRepoRoot;

/// Reads/writes `<orchestration>/features/<id>/` under repo root — `.adf/orchestration`
/// by default (legacy `.adf/orchestration` still resolves). See OrchestrationPaths.
class FeatureStore {
  FeatureStore(this.repoRoot) : paths = OrchestrationPaths(repoRoot);

  final String repoRoot;
  final OrchestrationPaths paths;

  String get featuresRootPath => featuresRoot;

  static const int firstPipelinePhase = 1;
  static const int lastPipelinePhase = 9;

  static const Map<int, String> phaseGateMap = {
    1: 'problem_statement_approved',
    2: 'requirements_complete',
    3: 'plan_covers_all_requirements',
    4: 'tasks_atomic_and_traced',
    5: 'test_strategy_approved',
    6: 'tests_red',
    7: 'tests_green',
    8: 'all_quality_gates_pass',
    9: 'review_approved',
  };

  static bool isPipelinePhase(int phase) =>
      phase >= firstPipelinePhase && phase <= lastPipelinePhase;

  /// First phase whose gate is not yet met (1–9); returns 9 when all done.
  int inferWorkPhase(Map<String, dynamic> gates) {
    for (var p = firstPipelinePhase; p <= lastPipelinePhase; p++) {
      final key = phaseGateMap[p];
      if (key != null && gates[key] != true) return p;
    }
    return lastPipelinePhase;
  }

  /// @deprecated Use [inferWorkPhase]; kept for tests.
  static int firstIncompleteGatePhase(Map<String, dynamic> gates) {
    final store = FeatureStore('');
    final w = store.inferWorkPhase(gates);
    return w >= lastPipelinePhase &&
            gates[phaseGateMap[lastPipelinePhase]] == true
        ? 10
        : w;
  }

  /// Clamp corrupt state (e.g. `current_phase` 10+) to ADF phases 1–9.
  bool repairPipelineState(String featureId, Map<String, dynamic> state) {
    final id = featureId;
    var changed = false;
    final gates = Map<String, dynamic>.from(
      state['gates'] as Map<String, dynamic>? ?? {},
    );

    final work = inferWorkPhase(gates);
    final reviewGate = phaseGateMap[lastPipelinePhase];
    final allDone =
        reviewGate != null && gates[reviewGate] == true && work == lastPipelinePhase;
    final completionCap = allDone ? lastPipelinePhase : work;

    for (final key in ['completed_builders', 'completed_reviewers']) {
      final map = Map<String, dynamic>.from(state[key] as Map? ?? {});
      for (final k in map.keys.toList()) {
        final n = int.tryParse(k.toString());
        if (n != null && n > completionCap) {
          map.remove(k);
          changed = true;
        }
      }
      state[key] = map;
    }

    final current = (state['current_phase'] as num?)?.toInt() ?? 0;
    final pending = (state['pending_approval_phase'] as num?)?.toInt();

    if (allDone) {
      if (state['current_phase'] != lastPipelinePhase) {
        state['current_phase'] = lastPipelinePhase;
        changed = true;
      }
      if (state['status'] != 'completed') {
        state['status'] = 'completed';
        changed = true;
      }
      if (state['awaiting_user'] == true) {
        state['awaiting_user'] = false;
        changed = true;
      }
      if (state['pending_approval_phase'] != null) {
        state['pending_approval_phase'] = null;
        changed = true;
      }
    } else if (current > lastPipelinePhase ||
        (pending != null && pending > lastPipelinePhase)) {
      state['current_phase'] = work;
      state['status'] = 'active';
      if (state['awaiting_user'] == true) {
        state['pending_approval_phase'] =
            pending != null && isPipelinePhase(pending) ? pending : work;
      }
      changed = true;
    } else if (current > work && state['status'] != 'completed') {
      state['current_phase'] = work;
      changed = true;
    } else if (current < firstPipelinePhase &&
        state['status'] == 'active' &&
        bootstrapComplete(id, state)) {
      state['current_phase'] = work;
      changed = true;
    }

    // A blocked feature has FAILED — it is NOT awaiting your approval. Clear the
    // stale awaiting/pending flags so the UI shows the blocked banner (the real
    // error + recovery steps), never a phantom "approve phase N" gate for an
    // already-passed phase that the user can't act on. (Bug: a feature blocked at
    // phase 7 showed "phase 1 needs your attention".)
    if (state['status'] == 'blocked' &&
        (state['awaiting_user'] == true ||
            state['pending_approval_phase'] != null)) {
      state['awaiting_user'] = false;
      state['pending_approval_phase'] = null;
      changed = true;
    }

    state['gates'] = gates;
    return changed;
  }

  /// Removes `completed_builders` / `completed_reviewers` beyond first open gate.
  bool repairStalePhaseCompletionMaps(String featureId, Map<String, dynamic> state) {
    return repairPipelineState(featureId, state);
  }

  /// Normalizes stale run-status (e.g. `awaiting_approval` with no live agent).
  void repairRunStatus(String id) {
    final run = readRunStatus(id);
    if (run == null) return;
    final state = readState(id);
    final runStatus = run['status'] as String?;
    final agentActive = run['agent_active'] == true;
    final awaitingUser = state['awaiting_user'] == true;
    final completed = state['status'] == 'completed';

    final shouldIdle = (completed && runStatus != 'idle') ||
        (runStatus == 'awaiting_approval' && !agentActive && !awaitingUser) ||
        (completed &&
            (runStatus == 'running' ||
                runStatus == 'queued' ||
                runStatus == 'awaiting_approval'));

    if (shouldIdle) {
      writeRunStatus(id, {
        'status': 'idle',
        'agent_active': false,
        'finished_at': DateTime.now().toUtc().toIso8601String(),
        'error': null,
        'error_code': null,
      });
    }
  }

  /// True when phase-0 bootstrap is satisfied (Spec Kit feature dir exists).
  bool bootstrapComplete(String featureId, Map<String, dynamic> state) {
    final specDir = state['spec_feature_dir'] as String? ?? 'specs/$featureId';
    return File('$repoRoot/$specDir/spec.md').existsSync();
  }

  /// Phase for API/UI (never above 9). Maps stale `current_phase: 0` → work phase when bootstrapped.
  int effectivePhase(String featureId, Map<String, dynamic> state) {
    final gates = state['gates'] as Map<String, dynamic>? ?? {};
    final current = (state['current_phase'] as num?)?.toInt() ?? 0;
    if (state['status'] == 'completed') return lastPipelinePhase;
    final work = inferWorkPhase(gates);
    if (current > lastPipelinePhase) return work;
    if (current < firstPipelinePhase &&
        state['status'] == 'active' &&
        bootstrapComplete(featureId, state)) {
      return work;
    }
    if (current < work && state['status'] != 'completed') return work;
    return current;
  }

  String get featuresRoot => paths.featuresRoot;

  Directory featuresDir() => Directory(featuresRoot);

  String featurePath(String id) => '${featuresDir().path}/$id';

  bool featureExists(String id) => Directory(featurePath(id)).existsSync();

  List<String> listFeatures({bool includeExample = false}) {
    final dir = featuresDir();
    if (!dir.existsSync()) return [];
    return dir
        .listSync()
        .whereType<Directory>()
        .map((d) => d.path.split(Platform.pathSeparator).last)
        .where((id) => includeExample || !id.startsWith('_'))
        .toList()
      ..sort();
  }

  Map<String, dynamic> readState(String id) {
    final file = File('${featurePath(id)}/state.json');
    if (!file.existsSync()) {
      throw StateError('state.json not found for $id');
    }
    final raw = jsonDecode(file.readAsStringSync()) as Map<String, dynamic>;
    final copy = Map<String, dynamic>.from(raw);
    if (repairPipelineState(id, copy)) {
      writeState(id, copy, skipRepair: true);
    }
    return copy;
  }

  /// Persist the user's multimodal sources (links + ingested docs) for a feature so
  /// the requirements crew can GROUND + trace the spec to them (P4). Written to the
  /// exact path RequirementsCrewRunner reads via --sources.
  void writeSources(String id, List<dynamic> sources) {
    final file = File('$repoRoot/${paths.featureRel(id, 'sources.json')}');
    file.parent.createSync(recursive: true);
    writeFileAtomic(file, jsonEncode(sources));
  }

  void writeState(String id, Map<String, dynamic> state, {bool skipRepair = false}) {
    final toWrite = skipRepair ? state : Map<String, dynamic>.from(state);
    if (!skipRepair) {
      repairPipelineState(id, toWrite);
    }
    final file = File('${featurePath(id)}/state.json');
    file.parent.createSync(recursive: true);
    writeFileAtomic(
        file, const JsonEncoder.withIndent('  ').convert(toWrite));
  }

  /// Write durably: a kill mid-write must never leave a half-written / corrupt
  /// file (which would brick the feature). Write to a temp sibling then rename
  /// (atomic on POSIX), so a reader sees either the old file or the new one,
  /// never a torn one.
  static void writeFileAtomic(File file, String contents) {
    final tmp = File('${file.path}.tmp');
    tmp.writeAsStringSync(contents, flush: true);
    tmp.renameSync(file.path);
  }

  String readRequirement(String id) {
    final file = File('${featurePath(id)}/requirement.md');
    if (!file.existsSync()) return '';
    return file.readAsStringSync();
  }

  // G2/I4/I7: lines that are orchestrator/builder control commands (not
  // requirement content). The user types these to drive the pipeline (e.g.
  // `@orch-orchestrator resume <id>`); they belong in commands.jsonl, never in
  // requirement.md — where the deterministic engine would synthesize them into
  // bogus "The system SHALL @orch-orchestrator resume…" EARS requirements (the
  // exact contamination that permanently blocked the regulatory-affairs spec).
  static final RegExp _controlLine = RegExp(
    r'^\s*(@orch-orchestrator\b|#\s*Builder:|resume\s+\S+\s*$)',
    caseSensitive: false,
  );
  static final RegExp _bareAffirmative = RegExp(
    r'^(yes|yep|yeah|ok|okay|sure|proceed|go ahead|continue|do it)[.!]*$',
    caseSensitive: false,
  );

  /// Strip control-command lines and return the requirement-bearing prose
  /// (trimmed). Returns '' when the turn carried no requirement content (it was
  /// only control commands, or a bare affirmative like "yes"/"proceed" — those
  /// update execution state, not the spec). Static so it is unit-testable.
  static String sanitizeClarification(String text) {
    final kept = text
        .split('\n')
        .where((l) => !_controlLine.hasMatch(l))
        .join('\n')
        .trim();
    if (kept.isEmpty || _bareAffirmative.hasMatch(kept)) return '';
    return kept;
  }

  void appendClientClarification(String id, String text) {
    final t = sanitizeClarification(text); // G2/I4/I7: never ingest control spam
    if (t.isEmpty) return;
    final file = File('${featurePath(id)}/requirement.md');
    file.parent.createSync(recursive: true);
    final existing = file.existsSync() ? file.readAsStringSync() : '';
    final stamp = DateTime.now().toUtc().toIso8601String();
    final block = '''

## Client clarification ($stamp)

$t
''';
    writeFileAtomic(
      file,
      existing.endsWith('\n') ? '$existing$block' : '$existing\n$block',
    );
  }

  List<dynamic> readApprovals(String id) {
    final file = File('${featurePath(id)}/approvals.json');
    if (!file.existsSync()) return [];
    return jsonDecode(file.readAsStringSync()) as List<dynamic>;
  }

  void appendApproval(String id, Map<String, dynamic> entry) {
    final list = readApprovals(id);
    list.add(entry);
    final file = File('${featurePath(id)}/approvals.json');
    writeFileAtomic(file, const JsonEncoder.withIndent('  ').convert(list));
  }

  String? readLatestJudgeVerdict(String id) {
    final dir = Directory('${featurePath(id)}/judge-verdicts');
    if (!dir.existsSync()) return null;
    final files = dir
        .listSync()
        .whereType<File>()
        .where((f) => f.path.endsWith('.md'))
        .toList()
      ..sort((a, b) => b.path.compareTo(a.path));
    if (files.isEmpty) return null;
    return files.first.readAsStringSync();
  }

  String? parseJudgeVerdict(String? markdown) {
    if (markdown == null) return null;
    final match = RegExp(
      r'\*\*Verdict:\*\*\s*(PASS|REVISE|FAIL)',
      caseSensitive: false,
    ).firstMatch(markdown);
    return match?.group(1)?.toLowerCase();
  }

  /// Parses `**Reviewers:** skill-a, skill-b` from a judge verdict markdown file.
  List<String>? parseReviewerSkills(String? markdown) {
    if (markdown == null) return null;
    final match = RegExp(
      r'\*\*Reviewers:\*\*\s*(.+)',
      caseSensitive: false,
    ).firstMatch(markdown);
    if (match == null) return null;
    return match
        .group(1)!
        .split(RegExp(r'[,;]'))
        .map((s) => s.trim())
        .where((s) => s.isNotEmpty)
        .toList();
  }

  /// Fills [state] `completed_reviewers` from on-disk `judge-verdicts/phase-N.md`.
  bool reconcileCompletedReviewersFromVerdicts(
    String id,
    Map<String, dynamic> state,
  ) {
    var changed = false;
    final reviewers = Map<String, dynamic>.from(
      state['completed_reviewers'] as Map<String, dynamic>? ?? {},
    );
    for (var p = firstPipelinePhase; p <= lastPipelinePhase; p++) {
      final file = File('${featurePath(id)}/judge-verdicts/phase-$p.md');
      if (!file.existsSync()) continue;
      final skills = parseReviewerSkills(file.readAsStringSync());
      if (skills == null || skills.isEmpty) continue;
      reviewers['$p'] = skills;
      changed = true;
    }
    if (changed) {
      state['completed_reviewers'] = reviewers;
    }
    return changed;
  }

  String? readJudgeVerdictMarkdown(String id, {int? phase}) {
    if (phase != null) {
      final file = File('${featurePath(id)}/judge-verdicts/phase-$phase.md');
      if (file.existsSync()) return file.readAsStringSync();
    }
    return readLatestJudgeVerdict(id);
  }

  /// Extracts the "## Combined recommendation" section from a judge verdict file.
  String? parseCombinedRecommendation(String? markdown) {
    if (markdown == null || markdown.trim().isEmpty) return null;
    final match = RegExp(
      r'##\s*Combined recommendation\s*\n+([\s\S]*)$',
      caseSensitive: false,
    ).firstMatch(markdown);
    final text = match?.group(1)?.trim();
    if (text != null && text.isNotEmpty) return text;
    return null;
  }

  String? readCombinedRecommendation(String id, {int? phase}) {
    final md = readJudgeVerdictMarkdown(id, phase: phase);
    return parseCombinedRecommendation(md);
  }

  Map<String, dynamic>? readPhaseRequest(String id) {
    final file = File('${featurePath(id)}/phase-request.json');
    if (!file.existsSync()) return null;
    return jsonDecode(file.readAsStringSync()) as Map<String, dynamic>;
  }

  void writePhaseRequest(String id, int phase) {
    final file = File('${featurePath(id)}/phase-request.json');
    writeFileAtomic(
      file,
      const JsonEncoder.withIndent('  ').convert({
        'action': 'run_phase',
        'phase': phase,
        'requested_at': DateTime.now().toUtc().toIso8601String(),
        'consumed': false,
      }),
    );
  }

  void consumePhaseRequest(String id) {
    final req = readPhaseRequest(id);
    if (req == null) return;
    final updated = Map<String, dynamic>.from(req);
    updated['consumed'] = true;
    updated['consumed_at'] = DateTime.now().toUtc().toIso8601String();
    final file = File('${featurePath(id)}/phase-request.json');
    writeFileAtomic(file, const JsonEncoder.withIndent('  ').convert(updated));
  }

  Map<String, dynamic>? readRunStatus(String id) {
    final file = File('${featurePath(id)}/run-status.json');
    if (!file.existsSync()) return null;
    return jsonDecode(file.readAsStringSync()) as Map<String, dynamic>;
  }

  void writeRunStatus(String id, Map<String, dynamic> status) {
    final file = File('${featurePath(id)}/run-status.json');
    file.parent.createSync(recursive: true);
    writeFileAtomic(file, const JsonEncoder.withIndent('  ').convert(status));
  }

  void appendRunLog(String id, Map<String, dynamic> entry) {
    final file = File('${featurePath(id)}/run-log.jsonl');
    file.parent.createSync(recursive: true);
    file.writeAsStringSync('${jsonEncode(entry)}\n', mode: FileMode.append);
    _trimRunLog(file, maxLines: 200);
  }

  void _trimRunLog(File file, {required int maxLines}) {
    if (!file.existsSync()) return;
    final lines = file.readAsLinesSync();
    if (lines.length <= maxLines) return;
    writeFileAtomic(
        file, '${lines.sublist(lines.length - maxLines).join('\n')}\n');
  }

  void writeLastAgentResponse(String id, String text) {
    final file = File('${featurePath(id)}/last-agent-response.md');
    file.parent.createSync(recursive: true);
    writeFileAtomic(file, text.trim().isEmpty ? '' : '${text.trim()}\n');
  }

  String? readLastAgentResponse(String id) {
    final file = File('${featurePath(id)}/last-agent-response.md');
    if (!file.existsSync()) return null;
    final t = file.readAsStringSync().trim();
    return t.isEmpty ? null : t;
  }

  List<Map<String, dynamic>> readRunLog(String id, {int limit = 200}) {
    final file = File('${featurePath(id)}/run-log.jsonl');
    if (!file.existsSync()) return [];
    final out = <Map<String, dynamic>>[];
    for (final line in file.readAsLinesSync()) {
      if (line.trim().isEmpty) continue;
      try {
        out.add(jsonDecode(line) as Map<String, dynamic>);
      } catch (_) {}
    }
    if (out.length > limit) return out.sublist(out.length - limit);
    return out;
  }

  Map<String, dynamic> appendCommand(
    String id, {
    required String prompt,
    String? stepId,
    bool execute = false,
  }) {
    final cmd = {
      'id': DateTime.now().microsecondsSinceEpoch.toString(),
      'prompt': prompt,
      if (stepId != null) 'step_id': stepId,
      'execute': execute,
      'status': 'pending',
      'created_at': DateTime.now().toUtc().toIso8601String(),
    };
    final file = File('${featurePath(id)}/commands.jsonl');
    file.parent.createSync(recursive: true);
    file.writeAsStringSync('${jsonEncode(cmd)}\n', mode: FileMode.append);
    return cmd;
  }

  /// Append a standalone assistant/system message to the conversation — a run
  /// outcome ("Build complete", "Build stopped", …) that must persist and be
  /// scrollable in the chat. It rides the same `commands.jsonl` store the chat
  /// view is built from, but with an EMPTY prompt so it renders as a single
  /// assistant bubble (no phantom user message). `buildChatView` surfaces these.
  Map<String, dynamic> appendSystemMessage(
    String id,
    String text, {
    String source = 'runner',
  }) {
    final cmd = {
      'id': DateTime.now().microsecondsSinceEpoch.toString(),
      'prompt': '',
      'type': 'system',
      'status': 'executed',
      'assistant_reply': text,
      'llm_source': source,
      'created_at': DateTime.now().toUtc().toIso8601String(),
      'executed_at': DateTime.now().toUtc().toIso8601String(),
    };
    final file = File('${featurePath(id)}/commands.jsonl');
    file.parent.createSync(recursive: true);
    file.writeAsStringSync('${jsonEncode(cmd)}\n', mode: FileMode.append);
    return cmd;
  }

  List<Map<String, dynamic>> listCommands(String id, {int limit = 20}) {
    final file = File('${featurePath(id)}/commands.jsonl');
    if (!file.existsSync()) return [];
    final out = <Map<String, dynamic>>[];
    for (final line in file.readAsLinesSync()) {
      if (line.trim().isEmpty) continue;
      try {
        out.add(jsonDecode(line) as Map<String, dynamic>);
      } catch (_) {}
    }
    if (out.length > limit) return out.sublist(out.length - limit);
    return out;
  }

  /// `rejected` + `awaiting_user` is inconsistent — revive to active revise loop.
  void reconcileFeatureState(String id) {
    final state = readState(id);
    var changed = false;
    final awaiting = state['awaiting_user'] == true;
    final status = state['status'] as String?;
    if (awaiting && status == 'rejected') {
      state['status'] = 'active';
      changed = true;
    }
    // Auto-flow: a feature stranded `awaiting_user` (e.g. from before auto-approve
    // was on) must not stay stuck nagging — clear the gate so it can advance.
    if (awaiting && autoApprove(state)) {
      state['awaiting_user'] = false;
      changed = true;
    }
    if (repairPipelineState(id, state)) {
      changed = true;
    }
    if (reconcileCompletedReviewersFromVerdicts(id, state)) {
      changed = true;
    }
    if (changed) {
      writeState(id, state, skipRepair: true);
    }
    repairRunStatus(id);
    repairStaleChatReplies(id);
  }

  /// Mark orphaned `running` commands as cancelled (hook/agent crash).
  void clearStuckCommands(String id) {
    final file = File('${featurePath(id)}/commands.jsonl');
    if (!file.existsSync()) return;
    final lines = file.readAsLinesSync();
    final updated = <String>[];
    var changed = false;
    for (final line in lines) {
      if (line.trim().isEmpty) continue;
      try {
        final cmd = jsonDecode(line) as Map<String, dynamic>;
        if (cmd['status'] == 'running') {
          cmd['status'] = 'cancelled';
          cmd['executed_at'] =
              cmd['executed_at'] ?? DateTime.now().toUtc().toIso8601String();
          changed = true;
        }
        updated.add(jsonEncode(cmd));
      } catch (_) {
        updated.add(line);
      }
    }
    if (changed) {
      writeFileAtomic(file, '${updated.join('\n')}\n');
    }
  }



  /// Lovable-style: derive a kebab-case feature id from a free-text prompt.
  static String generateFeatureId(String prompt, {Set<String> existing = const {}}) {
    final words = prompt
        .toLowerCase()
        .replaceAll(RegExp(r'[^a-z0-9\s-]'), ' ')
        .split(RegExp(r'\s+'))
        .where((w) => w.isNotEmpty && !_stopWords.contains(w))
        .take(4)
        .toList();
    var base = words.isEmpty ? 'feature' : words.join('-');
    if (base.length > 40) base = base.substring(0, 40);
    base = base.replaceAll(RegExp(r'-+$'), '');
    if (!existing.contains(base)) return base;
    for (var i = 2; i < 100; i++) {
      final candidate = '$base-$i';
      if (!existing.contains(candidate)) return candidate;
    }
    return '$base-${DateTime.now().millisecondsSinceEpoch % 100000}';
  }

  static const _stopWords = {
    'a', 'an', 'the', 'i', 'we', 'to', 'of', 'for', 'and', 'or', 'in', 'on',
    'with', 'that', 'this', 'want', 'need', 'please', 'build', 'create',
    'make', 'add', 'me', 'my', 'our', 'app', 'feature',
  };

  /// Chat replies stuck at pending/streaming after server restart get closed out.
  void repairStaleChatReplies(String id, {Duration maxAge = const Duration(minutes: 10)}) {
    final file = File('${featurePath(id)}/commands.jsonl');
    if (!file.existsSync()) return;
    final now = DateTime.now().toUtc();
    final lines = file.readAsLinesSync();
    final updated = <String>[];
    var changed = false;
    for (final line in lines) {
      if (line.trim().isEmpty) continue;
      try {
        final cmd = jsonDecode(line) as Map<String, dynamic>;
        final src = cmd['llm_source'] as String?;
        if (src == 'pending' || src == 'streaming') {
          final created = DateTime.tryParse(cmd['created_at'] as String? ?? '');
          if (created != null && now.difference(created) > maxAge) {
            cmd['llm_source'] = 'timeout';
            cmd['assistant_reply'] =
                'The assistant did not finish replying (server restarted or '
                'the agent timed out). Ask again, or set GROQ_API_KEY for '
                'instant replies.';
            changed = true;
          }
        }
        updated.add(jsonEncode(cmd));
      } catch (_) {
        updated.add(line);
      }
    }
    if (changed) writeFileAtomic(file, '${updated.join('\n')}\n');
  }

  void updateCommandMeta(
    String id,
    String commandId, {
    String? assistantReply,
    String? orchestratorCommand,
    String? agentPrompt,
    String? llmSource,
    int? latencyMs,
  }) {
    final file = File('${featurePath(id)}/commands.jsonl');
    if (!file.existsSync()) return;
    final lines = file.readAsLinesSync();
    final updated = <String>[];
    for (final line in lines) {
      if (line.trim().isEmpty) continue;
      try {
        final cmd = jsonDecode(line) as Map<String, dynamic>;
        if (cmd['id'] == commandId) {
          if (assistantReply != null) cmd['assistant_reply'] = assistantReply;
          if (orchestratorCommand != null) {
            cmd['orchestrator_command'] = orchestratorCommand;
          }
          if (agentPrompt != null) cmd['agent_prompt'] = agentPrompt;
          if (llmSource != null) cmd['llm_source'] = llmSource;
          if (latencyMs != null) cmd['latency_ms'] = latencyMs;
        }
        updated.add(jsonEncode(cmd));
      } catch (_) {
        updated.add(line);
      }
    }
    writeFileAtomic(file, '${updated.join('\n')}\n');
  }

  void markCommandExecuted(String id, String commandId, {String? status}) {
    final file = File('${featurePath(id)}/commands.jsonl');
    if (!file.existsSync()) return;
    final lines = file.readAsLinesSync();
    final updated = <String>[];
    for (final line in lines) {
      if (line.trim().isEmpty) continue;
      try {
        final cmd = jsonDecode(line) as Map<String, dynamic>;
        if (cmd['id'] == commandId) {
          cmd['status'] = status ?? 'executed';
          cmd['executed_at'] = DateTime.now().toUtc().toIso8601String();
        }
        updated.add(jsonEncode(cmd));
      } catch (_) {
        updated.add(line);
      }
    }
    writeFileAtomic(file, '${updated.join('\n')}\n');
  }

  bool artifactExists(String relativePath) {
    return File('$repoRoot/$relativePath').existsSync();
  }

  /// Build stacks ADF can target (contract C5). `stdlib` = the original
  /// single-file Python app; `react-vite-sqlite` = a real React+Vite+Tailwind
  /// front + Fastify/better-sqlite3 server. The runner's StackProfile mirrors
  /// these names; an unknown stack falls back to stdlib there.
  static const Set<String> knownStacks = {
    'stdlib',
    'react-vite-sqlite',
    'expo-rn', // cross-platform mobile (Expo / React Native: iOS + Android + web)
  };

  static bool isKnownStack(String stack) => knownStacks.contains(stack);

  /// Whether the proof-governed approval gates should auto-flow (no human pause):
  /// per-feature `state.auto_approve`, or globally via `ORCH_AUTO_APPROVE`. Single
  /// source of truth so the server route AND the per-phase post-sync agree (they
  /// disagreed before — auto-approve only covered the 6→7 handoff, so phases 1–6
  /// still nagged). `env` is injectable for tests.
  static bool autoApprove(Map<String, dynamic> state, [Map<String, String>? env]) {
    if (state['auto_approve'] == true) return true; // per-feature override always wins
    final g =
        ((env ?? Platform.environment)['ORCH_AUTO_APPROVE'] ?? '').toLowerCase();
    if (g == 'all') return true; // explicit power-user escape hatch: auto every track
    final globalOn = g == 'true' || g == '1';
    // Track-aware gate: a track-S micro-fix (≤1 file) may auto-flow when the global
    // flag is on, but tracks M/L/XL are net-new or cross-cutting work whose
    // REQUIREMENTS must be confirmed by a human — they NEVER auto-flow from the global
    // flag (only the per-feature `auto_approve` override above, or ORCH_AUTO_APPROVE=all).
    // This is the fix for ADF barreling to implementation on an unconfirmed spec.
    final track = (state['track'] as String? ?? 'M').toUpperCase();
    return track == 'S' && globalOn;
  }

  /// The build stack chosen for [id] (contract C5), read from `state.stack`.
  /// Features created before stack selection have no field → stdlib, so legacy
  /// single-file apps keep building exactly as before.
  String stackFor(String id) {
    try {
      final s = (readState(id)['stack'] as String?)?.trim();
      if (s != null && s.isNotEmpty) return s;
    } catch (_) {/* no state yet → default below */}
    return 'stdlib';
  }

  void createFeature({
    required String id,
    required String requirement,
    required String track,
    String stack = 'stdlib',
  }) {
    if (!RegExp(r'^[a-z0-9]+(-[a-z0-9]+)*$').hasMatch(id)) {
      throw ArgumentError('Invalid feature id: $id');
    }
    final root = Directory(featurePath(id));
    if (root.existsSync()) {
      throw StateError('Feature already exists: $id');
    }
    root.createSync(recursive: true);
    Directory('${root.path}/judge-verdicts').createSync();

    File('${root.path}/requirement.md').writeAsStringSync('''
# Requirement

**Track:** $track

## Description

$requirement
''');

    writeFileAtomic(File('${root.path}/approvals.json'), '[]\n');

    // Spec Kit feature directory + pointer
    final specRel = 'specs/$id';
    Directory('$repoRoot/$specRel').createSync(recursive: true);
    Directory('$repoRoot/.specify').createSync(recursive: true);
    File('$repoRoot/.specify/feature.json').writeAsStringSync(
      '${const JsonEncoder.withIndent('  ').convert({'feature_directory': specRel})}\n',
    );

    writeState(id, defaultState(id: id, track: track, stack: stack));
  }

  Map<String, dynamic> defaultState({
    required String id,
    required String track,
    String stack = 'stdlib',
  }) {
    return {
      'feature_id': id,
      'track': track,
      'stack': stack,
      'spec_feature_dir': 'specs/$id',
      'coverage_mode': 'repo_wide',
      'current_phase': 0,
      'phase_revision_count': 0,
      'pending_approval_phase': null,
      'last_judge_verdict': null,
      'awaiting_user': false,
      'gates': {
        'problem_statement_approved': false,
        'requirements_complete': false,
        'plan_covers_all_requirements': false,
        'tasks_atomic_and_traced': false,
        'test_strategy_approved': false,
        'tests_red': false,
        'tests_green': false,
        'r100': false,
        'l100': false,
        'l100_repo': false,
        'l100_feature': false,
        'lint_clean': false,
        'security_clean': false,
        'performance_clean': false,
        'all_quality_gates_pass': false,
        'review_approved': false,
      },
      'completed_builders': <String, dynamic>{},
      'completed_reviewers': <String, dynamic>{},
      'heal_attempts': 0,
      'correct_attempts': 0,
      'files_in_scope': <String>[],
      'status': 'active',
      'loop_history': <dynamic>[],
    };
  }

  void setGateForPhase(Map<String, dynamic> state, int phase, bool value) {
    final gates = state['gates'] as Map<String, dynamic>? ?? {};
    final key = phaseGateMap[phase];
    if (key != null) {
      gates[key] = value;
    }
    if (phase == 8 && value) {
      gates['all_quality_gates_pass'] = true;
      final waivers = state['gate_waivers'] as Map<String, dynamic>? ?? {};
      for (final key in [
        'r100',
        'l100_repo',
        'l100_feature',
        'l100',
        'lint_clean',
        'security_clean',
        'performance_clean',
      ]) {
        gates[key] = !waivers.containsKey(key);
      }
    }
    state['gates'] = gates;
  }

  Map<String, dynamic> featureSummary(String id) {
    final state = readState(id);
    final run = readRunStatus(id);
    return {
      'id': id,
      'track': state['track'],
      'current_phase': effectivePhase(id, state),
      'status': state['status'],
      'pipeline_complete': state['status'] == 'completed',
      'awaiting_user': state['awaiting_user'],
      'pending_approval_phase': state['pending_approval_phase'],
      'last_judge_verdict': state['last_judge_verdict'],
      // The crew's open questions, surfaced so the user can confirm requirements
      // before the build proceeds (P3 — interactive elicitation).
      'requirements_open_questions': state['requirements_open_questions'],
      // G06: surface whether phase-2 used the real crew or fell back to the
      // deterministic template, so a silent fallback is auditable in the UI.
      'spec_source': state['spec_source'],
      'run_status': run?['status'],
    };
  }

  List<Map<String, dynamic>> readTraces(
    String id, {
    int limit = 100,
    String? event,
    int? phase,
    bool reasoningOnly = false,
    String? since,
  }) {
    final tracePaths = <String>[
      '${featurePath(id)}/otel-traces.jsonl',
      this.paths.otelTracesFile,
    ];
    final records = <Map<String, dynamic>>[];
    final seen = <String>{};

    for (final path in tracePaths) {
      final file = File(path);
      if (!file.existsSync()) continue;
      for (final line in file.readAsLinesSync()) {
        if (line.trim().isEmpty) continue;
        if (seen.contains(line)) continue;
        seen.add(line);
        try {
          records.add(jsonDecode(line) as Map<String, dynamic>);
        } catch (_) {
          continue;
        }
      }
    }

    records.sort((a, b) {
      final ta = a['timestamp'] as String? ?? '';
      final tb = b['timestamp'] as String? ?? '';
      return ta.compareTo(tb);
    });

    var filtered = records.where((r) {
      final attrs = r['attributes'] as Map<String, dynamic>?;
      final fid = attrs?['orch.feature_id'] as String?;
      if (fid != null && fid != id) return false;
      return true;
    }).toList();

    if (since != null && since.isNotEmpty) {
      filtered = filtered.where((r) {
        final ts = r['timestamp'] as String? ?? '';
        return ts.compareTo(since) > 0;
      }).toList();
    }
    if (event != null) {
      filtered = filtered.where((r) {
        final attrs = r['attributes'] as Map<String, dynamic>?;
        return attrs?['hook.event'] == event;
      }).toList();
    }
    if (phase != null) {
      filtered = filtered.where((r) {
        final attrs = r['attributes'] as Map<String, dynamic>?;
        return attrs?['orch.phase'] == phase;
      }).toList();
    }
    if (reasoningOnly) {
      filtered = filtered.where((r) {
        final attrs = r['attributes'] as Map<String, dynamic>?;
        return attrs?['agent.reasoning'] != null;
      }).toList();
    }
    if (filtered.length > limit) {
      return filtered.sublist(filtered.length - limit);
    }
    return filtered;
  }

  Map<String, dynamic> featureDetail(String id, {Map<String, dynamic>? pipeline}) {
    final state = readState(id);
    final pendingPhase = (state['pending_approval_phase'] as num?)?.toInt() ??
        (state['current_phase'] as num?)?.toInt();
    final verdictMd = readJudgeVerdictMarkdown(id, phase: pendingPhase);
    return {
      'summary': featureSummary(id),
      'requirement': readRequirement(id),
      'state': state,
      'approvals': readApprovals(id),
      'judge_verdict': verdictMd,
      'combined_recommendation': parseCombinedRecommendation(verdictMd),
      'judge_verdict_phase': pendingPhase,
      'phase_request': readPhaseRequest(id),
      'run_status': readRunStatus(id),
      'run_log': readRunLog(id, limit: 20),
      'commands': listCommands(id, limit: 10),
      if (pipeline != null) 'pipeline': pipeline,
      'trace_count': readTraces(id, limit: 10000).length,
    };
  }
}
