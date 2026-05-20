import 'dart:io';

import 'package:yaml/yaml.dart';

import 'feature_store.dart';

/// Builds step-by-step pipeline plan from framework-routing.yaml + feature state.
class PipelinePlanner {
  PipelinePlanner(this.store);

  final FeatureStore store;

  static const phaseNames = {
    0: 'Orchestrate',
    1: 'Intake',
    2: 'Specify',
    3: 'Plan',
    4: 'Tasks',
    5: 'Test plan',
    6: 'Test cases',
    7: 'Implement',
    8: 'Verify',
    9: 'Review',
  };

  Map<String, dynamic>? _routingCache;

  Map<String, dynamic> get routing {
    if (_routingCache != null) return _routingCache!;
    final path = store.paths.frameworkRoutingYaml;
    final file = File(path);
    if (!file.existsSync()) {
      throw StateError('framework-routing.yaml not found at $path');
    }
    final doc = loadYaml(file.readAsStringSync());
    _routingCache = _yamlToJson(doc) as Map<String, dynamic>;
    return _routingCache!;
  }

  Map<String, dynamic> buildPlan(String featureId) {
    final state = store.readState(featureId);
    final rawPhase = (state['current_phase'] as num?)?.toInt() ?? 0;
    final currentPhase = store.effectivePhase(featureId, state);
    final gates = state['gates'] as Map<String, dynamic>? ?? {};
    final completedBuilders =
        state['completed_builders'] as Map<String, dynamic>? ?? {};
    final completedReviewers =
        state['completed_reviewers'] as Map<String, dynamic>? ?? {};
    final awaiting = state['awaiting_user'] == true;
    final runStatus = store.readRunStatus(featureId);
    final runState = runStatus?['status'] as String?;
    final specDir =
        state['spec_feature_dir'] as String? ?? 'specs/$featureId';

    final phasesYaml = routing['phases'] as Map<String, dynamic>? ?? {};
    final phaseGateMap =
        routing['phase_gate_map'] as Map<String, dynamic>? ??
            FeatureStore.phaseGateMap.map((k, v) => MapEntry('$k', v));

    final phases = <Map<String, dynamic>>[];
    var doneCount = 0;
    var totalSteps = 0;
    String? currentStepId;

    // Phase 0 bootstrap
    final bootstrapSteps = <Map<String, dynamic>>[
      _step(
        id: 'bootstrap-sync_speckit',
        kind: 'bootstrap',
        label: 'Sync Spec Kit feature dir',
        status: store.artifactExists('$specDir/.gitkeep') ||
                store.artifactExists('$specDir/spec.md') ||
                Directory('${store.repoRoot}/$specDir').existsSync()
            ? 'done'
            : (currentPhase == 0 ? 'pending' : 'skipped'),
        cursorCommand: '# Run: ./scripts/orch/sync_speckit_feature.sh $featureId',
        artifacts: _existing(['$specDir']),
      ),
    ];
    totalSteps += bootstrapSteps.length;
    doneCount += bootstrapSteps.where((s) => s['status'] == 'done').length;

    phases.add({
      'id': 'phase-0',
      'phase': 0,
      'name': phaseNames[0],
      'gate': 'user_request_recorded',
      'gate_met': currentPhase > 0,
      'status': currentPhase > 0 ? 'done' : 'active',
      'steps': bootstrapSteps,
    });

    for (var p = 1; p <= 9; p++) {
      final phaseKey = '$p';
      final phaseDef = phasesYaml[phaseKey] as Map<String, dynamic>?;
      if (phaseDef == null) continue;

      final gateKey = phaseGateMap[phaseKey] as String? ??
          FeatureStore.phaseGateMap[p];
      final gateMet = gateKey != null && gates[gateKey] == true;
      final phaseStatus = gateMet
          ? 'done'
          : (p == currentPhase)
              ? 'active'
              : (p < currentPhase ? 'done' : 'pending');

      final steps = <Map<String, dynamic>>[];

      // Builders
      final builders = _asList(phaseDef['builders']);
      for (final b in builders) {
        final skill = b['skill'] as String? ?? 'builder';
        final optional = b['optional'] == true;
        final stepId = 'p$p-builder-$skill';
        final phaseBuilders = completedBuilders['$p'];
        final done = phaseBuilders is List && phaseBuilders.contains(skill);
        final status = done
            ? 'done'
            : (p == currentPhase && runState == 'running' ? 'running' : 'pending');
        if (status == 'done') doneCount++;
        totalSteps++;
        if (phaseStatus == 'active' && status != 'done' && currentStepId == null) {
          currentStepId = stepId;
        }
        steps.add(_step(
          id: stepId,
          kind: 'builder',
          label: 'Build: $skill',
          status: optional && !done && p < currentPhase ? 'skipped' : status,
          cursorCommand:
              '@orch-orchestrator resume $featureId\n# Builder: $skill phase $p',
          artifacts: _phaseArtifacts(featureId, p, phaseDef, specDir),
          optional: optional,
        ));
      }

      // Review coordinator (single step)
      final reviewers = _asList(phaseDef['reviewers']);
      if (reviewers.isNotEmpty) {
        final stepId = 'p$p-review-coordinator';
        final verdictFile =
            store.artifactExists(store.paths.featureRel(featureId, 'judge-verdicts/phase-$p.md'));
        final phaseReviewers = completedReviewers['$p'];
        final done = verdictFile ||
            (phaseReviewers is List && phaseReviewers.isNotEmpty);
        final status = done
            ? 'done'
            : (p == currentPhase && awaiting ? 'running' : 'pending');
        if (status == 'done') doneCount++;
        totalSteps++;
        if (phaseStatus == 'active' && !done && currentStepId == null) {
          currentStepId = stepId;
        }
        steps.add(_step(
          id: stepId,
          kind: 'review',
          label: 'BMAD review panel (${reviewers.length} reviewers)',
          status: status,
          cursorCommand:
              '@orch-orchestrator resume $featureId\n# Reviews: ${reviewers.map((r) => r['skill']).join(', ')}',
          artifacts: verdictFile
              ? [store.paths.featureRel(featureId, 'judge-verdicts/phase-$p.md')]
              : [],
        ));
      }

      // Phase 8 machine gates
      if (p == 8) {
        final scripts = _asStringList(phaseDef['scripts']);
        final machineGates = _asStringList(phaseDef['machine_gates']);
        for (var i = 0; i < scripts.length; i++) {
          final script = scripts[i];
          final gateName =
              i < machineGates.length ? machineGates[i] : script;
          final stepId = 'p8-gate-$script';
          final met = gates[gateName] == true ||
              gates['all_quality_gates_pass'] == true;
          final status = met ? 'done' : 'pending';
          if (status == 'done') doneCount++;
          totalSteps++;
          steps.add(_step(
            id: stepId,
            kind: 'machine_gate',
            label: 'Gate: $script',
            status: status,
            cursorCommand: './scripts/orch/$script $featureId',
            artifacts: store.artifactExists(
                    store.paths.featureRel(featureId, '07-verification-report.md'))
                ? [
                    store.paths.featureRel(featureId, '07-verification-report.md'),
                  ]
                : [],
          ));
        }
      }

      // Approval step
      final approvalId = 'p$p-approval';
      final approvalDone = gateMet;
      final approvalStatus = approvalDone
          ? 'done'
          : (awaiting && (state['pending_approval_phase'] as num?)?.toInt() == p)
              ? 'running'
              : 'pending';
      if (approvalStatus == 'done') doneCount++;
      totalSteps++;
      if (phaseStatus == 'active' && awaiting && currentStepId == null) {
        currentStepId = approvalId;
      }
      steps.add(_step(
        id: approvalId,
        kind: 'approval',
        label: 'User approval (gate: $gateKey)',
        status: approvalStatus,
        cursorCommand: awaiting
            ? '@orch-orchestrator sync $featureId'
            : '@orch-orchestrator resume $featureId',
        artifacts: [],
      ));

      if (phaseStatus == 'done') doneCount++;

      phases.add({
        'id': 'phase-$p',
        'phase': p,
        'name': phaseNames[p] ?? phaseDef['name'],
        'gate': gateKey,
        'gate_met': gateMet,
        'status': phaseStatus,
        'steps': steps,
      });
    }

    currentStepId ??= currentPhase > 0 ? 'p$currentPhase-builder' : 'bootstrap-sync_speckit';

    final phasesComplete = phases
        .where((ph) =>
            (ph['phase'] as int) >= FeatureStore.firstPipelinePhase &&
            ph['gate_met'] == true)
        .length;

    return {
      'feature_id': featureId,
      'current_phase': currentPhase,
      if (rawPhase > FeatureStore.lastPipelinePhase)
        'raw_current_phase': rawPhase,
      'pipeline_complete': state['status'] == 'completed',
      'current_step_id': currentStepId,
      'phases': phases,
      'summary': {
        'done': doneCount,
        'total': totalSteps,
        'phases_complete': phasesComplete,
        'phases_total': FeatureStore.lastPipelinePhase,
      },
    };
  }

  List<String> _phaseArtifacts(
    String featureId,
    int phase,
    Map<String, dynamic> phaseDef,
    String specDir,
  ) {
    final paths = <String>[];
    for (final o in _asStringList(phaseDef['orch_outputs'])) {
      paths.add(store.paths.featureRel(featureId, o));
    }
    for (final o in _asStringList(phaseDef['spec_outputs'])) {
      paths.add('$specDir/$o');
    }
    return _existing(paths);
  }

  List<String> _existing(List<String> paths) {
    return paths.where(store.artifactExists).toList();
  }

  Map<String, dynamic> _step({
    required String id,
    required String kind,
    required String label,
    required String status,
    required String cursorCommand,
    required List<String> artifacts,
    bool optional = false,
  }) {
    return {
      'id': id,
      'kind': kind,
      'label': label,
      'status': status,
      'cursor_command': cursorCommand,
      'artifacts': artifacts,
      if (optional) 'optional': true,
    };
  }

  List<Map<String, dynamic>> _asList(dynamic value) {
    if (value == null) return [];
    if (value is List) {
      return value.map((e) => _yamlToJson(e) as Map<String, dynamic>).toList();
    }
    if (value is Map) {
      return [_yamlToJson(value) as Map<String, dynamic>];
    }
    return [];
  }

  List<String> _asStringList(dynamic value) {
    if (value == null) return [];
    if (value is List) return value.map((e) => e.toString()).toList();
    return [value.toString()];
  }

  dynamic _yamlToJson(dynamic value) {
    if (value is YamlMap) {
      return value.map((k, v) => MapEntry(k.toString(), _yamlToJson(v)));
    }
    if (value is YamlList) {
      return value.map(_yamlToJson).toList();
    }
    return value;
  }
}
