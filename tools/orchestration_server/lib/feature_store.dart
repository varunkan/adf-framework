import 'dart:convert';
import 'dart:io';

import 'orchestration_paths.dart';

export 'orchestration_paths.dart' show resolveRepoRoot;

/// Reads/writes `.cursor/orchestration/features/<id>/` under repo root.
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

  void writeState(String id, Map<String, dynamic> state, {bool skipRepair = false}) {
    final toWrite = skipRepair ? state : Map<String, dynamic>.from(state);
    if (!skipRepair) {
      repairPipelineState(id, toWrite);
    }
    final file = File('${featurePath(id)}/state.json');
    file.parent.createSync(recursive: true);
    file.writeAsStringSync(const JsonEncoder.withIndent('  ').convert(toWrite));
  }

  String readRequirement(String id) {
    final file = File('${featurePath(id)}/requirement.md');
    if (!file.existsSync()) return '';
    return file.readAsStringSync();
  }

  void appendClientClarification(String id, String text) {
    final t = text.trim();
    if (t.isEmpty) return;
    final file = File('${featurePath(id)}/requirement.md');
    file.parent.createSync(recursive: true);
    final existing = file.existsSync() ? file.readAsStringSync() : '';
    final stamp = DateTime.now().toUtc().toIso8601String();
    final block = '''

## Client clarification ($stamp)

$t
''';
    file.writeAsStringSync(
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
    file.writeAsStringSync(const JsonEncoder.withIndent('  ').convert(list));
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
    file.writeAsStringSync(
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
    file.writeAsStringSync(const JsonEncoder.withIndent('  ').convert(updated));
  }

  Map<String, dynamic>? readRunStatus(String id) {
    final file = File('${featurePath(id)}/run-status.json');
    if (!file.existsSync()) return null;
    return jsonDecode(file.readAsStringSync()) as Map<String, dynamic>;
  }

  void writeRunStatus(String id, Map<String, dynamic> status) {
    final file = File('${featurePath(id)}/run-status.json');
    file.parent.createSync(recursive: true);
    file.writeAsStringSync(const JsonEncoder.withIndent('  ').convert(status));
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
    file.writeAsStringSync('${lines.sublist(lines.length - maxLines).join('\n')}\n');
  }

  void writeLastAgentResponse(String id, String text) {
    final file = File('${featurePath(id)}/last-agent-response.md');
    file.parent.createSync(recursive: true);
    file.writeAsStringSync(text.trim().isEmpty ? '' : '${text.trim()}\n');
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
      file.writeAsStringSync('${updated.join('\n')}\n');
    }
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
    file.writeAsStringSync('${updated.join('\n')}\n');
  }

  bool artifactExists(String relativePath) {
    return File('$repoRoot/$relativePath').existsSync();
  }

  void createFeature({
    required String id,
    required String requirement,
    required String track,
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

    File('${root.path}/approvals.json').writeAsStringSync('[]\n');

    // Spec Kit feature directory + pointer
    final specRel = 'specs/$id';
    Directory('$repoRoot/$specRel').createSync(recursive: true);
    Directory('$repoRoot/.specify').createSync(recursive: true);
    File('$repoRoot/.specify/feature.json').writeAsStringSync(
      '${const JsonEncoder.withIndent('  ').convert({'feature_directory': specRel})}\n',
    );

    writeState(id, defaultState(id: id, track: track));
  }

  Map<String, dynamic> defaultState({
    required String id,
    required String track,
  }) {
    return {
      'feature_id': id,
      'track': track,
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
