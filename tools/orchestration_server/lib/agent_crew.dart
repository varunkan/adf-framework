import 'dart:convert';
import 'dart:io';

import 'artifact_validator.dart';
import 'deterministic_artifacts.dart';
import 'feature_store.dart';
import 'integrity_chain.dart';
import 'learning_store.dart';

/// A specialized subagent in the crew. Agents declare dependencies; the
/// crew runs every agent whose needs are met concurrently (wave execution).
class CrewAgent {
  CrewAgent({
    required this.name,
    required this.role,
    required this.phase,
    this.needs = const [],
    required this.run,
  });

  final String name;
  final String role;
  final int phase;
  final List<String> needs;
  final Future<List<String>> Function() run;
}

/// Multi-agent harness: product analyst, spec writer, architect, task
/// planner, test architect, and test author work together in parallel
/// dependency waves — deterministic, zero tokens, milliseconds.
class AgentCrew {
  AgentCrew(
    this.store,
    this.engine,
    this.validator,
    this.learnings, {
    IntegrityChain? integrity,
  }) : integrity = integrity ?? IntegrityChain(store);

  final FeatureStore store;
  final DeterministicArtifactEngine engine;
  final ArtifactValidator validator;
  final LearningStore learnings;
  final IntegrityChain integrity;

  List<CrewAgent> buildCrew(String id) => [
        CrewAgent(
          name: 'product-analyst',
          role: 'Problem statement & success criteria',
          phase: 1,
          run: () => engine.generatePhase(id, 1),
        ),
        CrewAgent(
          name: 'spec-writer',
          role: 'EARS requirements & acceptance criteria',
          phase: 2,
          needs: ['product-analyst'],
          run: () => engine.generatePhase(id, 2),
        ),
        CrewAgent(
          name: 'architect',
          role: 'Implementation plan & risk register',
          phase: 3,
          needs: ['spec-writer'],
          run: () => engine.generatePhase(id, 3),
        ),
        CrewAgent(
          name: 'task-planner',
          role: 'Micro-task DAG (≤90s tasks)',
          phase: 4,
          needs: ['spec-writer'],
          run: () => engine.generatePhase(id, 4),
        ),
        CrewAgent(
          name: 'test-architect',
          role: 'Test strategy & exit criteria',
          phase: 5,
          needs: ['spec-writer'],
          run: () => engine.generatePhase(id, 5),
        ),
        CrewAgent(
          name: 'test-author',
          role: 'Test cases & traceability matrix',
          phase: 6,
          needs: ['task-planner', 'test-architect'],
          run: () => engine.generatePhase(id, 6),
        ),
      ];

  Future<Map<String, dynamic>> run(String id) async {
    final started = DateTime.now();
    final crew = buildCrew(id);
    final doneAgents = <String>{};
    final agentResults = <Map<String, dynamic>>[];
    final waves = <List<String>>[];

    final remaining = [...crew];
    while (remaining.isNotEmpty) {
      final wave = remaining
          .where((a) => a.needs.every(doneAgents.contains))
          .toList();
      if (wave.isEmpty) {
        throw StateError('crew dependency cycle: '
            '${remaining.map((a) => a.name).join(', ')}');
      }
      waves.add(wave.map((a) => a.name).toList());
      // All agents in a wave run concurrently.
      final results = await Future.wait(wave.map((agent) async {
        final sw = Stopwatch()..start();
        final artifacts = await agent.run();
        sw.stop();
        return {
          'agent': agent.name,
          'role': agent.role,
          'phase': agent.phase,
          'artifacts': artifacts,
          'duration_ms': sw.elapsedMilliseconds,
        };
      }));
      for (final r in results) {
        agentResults.add(r);
        doneAgents.add(r['agent'] as String);
        _logAgent(id, r);
      }
      remaining.removeWhere((a) => doneAgents.contains(a.name));
    }

    // Machine-validate, then advance gates exactly like a human-led run.
    final completed = <int>[];
    var blockers = <String>[];
    for (final phase in [1, 2, 3, 4, 5, 6]) {
      if ({2, 3, 4}.contains(phase)) {
        final v = await validator.check(id, phase: phase);
        if (v['pass'] != true) {
          blockers = (v['blockers'] as List? ?? [])
              .map((b) => b.toString())
              .toList();
          learnings.record(
            featureId: id,
            phase: phase,
            kind: 'failure',
            blockers: blockers,
          );
          break;
        }
      }
      _advance(id, phase);
      completed.add(phase);
      // Cryptographically seal this phase: artifacts + gates into the chain.
      integrity.seal(id, phase: phase, actor: 'adf-crew');
      learnings.record(featureId: id, phase: phase, kind: 'success');
    }

    final summary = {
      'feature_id': id,
      'mode': 'multi_agent_crew',
      'agents': agentResults,
      'waves': waves,
      'parallelism': waves.map((w) => w.length).reduce((a, b) => a > b ? a : b),
      'phases_completed': completed,
      'stop_reason':
          blockers.isNotEmpty ? 'blocked' : 'implementation_handoff',
      'blockers': blockers,
      'token_cost': engine.brain.billsTokens ? 'metered' : 'zero',
      'integrity': integrity.verify(id),
      'brain': engine.brain.name,
      'duration_ms': DateTime.now().difference(started).inMilliseconds,
    };
    _announce(id, summary);
    return summary;
  }

  void _advance(String id, int phase) {
    final state = store.readState(id);
    store.setGateForPhase(state, phase, true);
    final builders =
        Map<String, dynamic>.from(state['completed_builders'] as Map? ?? {});
    builders['$phase'] = ['adf-crew'];
    state['completed_builders'] = builders;
    final gates = state['gates'] as Map<String, dynamic>? ?? {};
    state['current_phase'] = store.inferWorkPhase(gates);
    state['status'] = 'active';
    state['awaiting_user'] = false;
    store.writeState(id, state);
  }

  void _logAgent(String id, Map<String, dynamic> entry) {
    final file = File('${store.featurePath(id)}/crew-log.jsonl');
    file.parent.createSync(recursive: true);
    file.writeAsStringSync(
      '${jsonEncode({...entry, 'ts': DateTime.now().toUtc().toIso8601String()})}\n',
      mode: FileMode.append,
    );
  }

  void _announce(String id, Map<String, dynamic> summary) {
    final agents = summary['agents'] as List;
    final waves = summary['waves'] as List;
    final text = StringBuffer('**Multi-agent crew finished.**\n\n');
    for (final w in waves) {
      text.writeln('- Wave: ${(w as List).join(' + ')}');
    }
    text
      ..writeln('- ${agents.length} subagents, max parallelism '
          '${summary['parallelism']}, ${summary['duration_ms']}ms total, '
          'token cost: ${summary['token_cost']}')
      ..writeln(summary['stop_reason'] == 'implementation_handoff'
          ? '- Next: phase 7 implementation against the red tests.'
          : '- Blocked: ${(summary['blockers'] as List).join('; ')}');
    final cmd = store.appendCommand(id, prompt: 'crew', execute: false);
    store.updateCommandMeta(
      id,
      cmd['id'] as String,
      assistantReply: text.toString().trim(),
      llmSource: 'crew',
    );
    store.markCommandExecuted(id, cmd['id'] as String);
  }
}
