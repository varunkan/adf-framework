import 'package:orchestration_server/adf_brain.dart';
import 'package:orchestration_server/claude_api_brain.dart';
import 'package:orchestration_server/model_router.dart';
import 'package:orchestration_server/openai_compat_brain.dart';
import 'package:test/test.dart';

void main() {
  const withKey = {'ANTHROPIC_API_KEY': 'sk-test'};
  const withNvidia = {'NVIDIA_API_KEY': 'nvapi-test'};
  const withBoth = {'ANTHROPIC_API_KEY': 'sk-test', 'NVIDIA_API_KEY': 'nvapi-test'};

  ModelRouter routerWith([Map<String, String> env = withKey]) =>
      ModelRouter(env: env);

  group('tier selection', () {
    test('short chat routes local at zero cost', () {
      final d = routerWith().route(task: 'hi, how is the build?', kind: 'chat');
      expect(d.tier, 'local');
      expect(d.reason, contains('kind=chat'));
    });

    test('short artifact routes local', () {
      final d = routerWith()
          .route(task: 'write the README intro', kind: 'artifact');
      expect(d.tier, 'local');
    });

    test('medium-length chat lifts to fast', () {
      final d = routerWith().route(task: 'q' * 700, kind: 'chat');
      expect(d.tier, 'fast');
      expect(d.model, 'claude-haiku-4-5');
      expect(d.reason, contains('medium task'));
    });

    test('a code block lifts chat to fast', () {
      final d = routerWith().route(
        task: 'why does this throw?\n```dart\nvoid main() {}\n```',
        kind: 'chat',
      );
      expect(d.tier, 'fast');
      expect(d.reason, contains('code block'));
    });

    test('review and plan route balanced', () {
      final router = routerWith();
      final review = router.route(task: 'review the diff', kind: 'review');
      expect(review.tier, 'balanced');
      expect(review.model, 'claude-sonnet-4-6');
      expect(router.route(task: 'plan the milestone', kind: 'plan').tier,
          'balanced');
    });

    test('implement routes deep', () {
      final d = routerWith()
          .route(task: 'implement the cart endpoint', kind: 'implement');
      expect(d.tier, 'deep');
      expect(d.model, 'claude-opus-4-8');
    });

    test('explicit escalation words lift chat to balanced', () {
      final d = routerWith().route(
        task: 'think hard about why checkout intermittently fails',
        kind: 'chat',
      );
      expect(d.tier, 'balanced');
      expect(d.reason, contains('escalation words'));
    });

    test('very long implement task stays deep', () {
      final d = routerWith()
          .route(task: 'implement: ${'spec ' * 600}', kind: 'implement');
      expect(d.tier, 'deep');
      expect(d.reason, contains('long task'));
    });

    test('phase is recorded in the reason', () {
      final d = routerWith().route(task: 'hello', kind: 'chat', phase: 6);
      expect(d.reason, contains('phase=6'));
    });

    test('every decision is loggable', () {
      final d = routerWith().route(task: 'implement it', kind: 'implement');
      final json = d.toJson();
      expect(json['tier'], 'deep');
      expect(json['model'], 'claude-opus-4-8');
      expect(json['reason'], isNotEmpty);
      expect(d.toString(), contains('deep/claude-opus-4-8'));
    });
  });

  group('cloud degradation without ANTHROPIC_API_KEY', () {
    test('auto degrades cloud picks to local, never errors', () {
      final d = ModelRouter(env: const {})
          .route(task: 'implement the cart endpoint', kind: 'implement');
      expect(d.tier, 'local');
      expect(d.reason, contains('ANTHROPIC_API_KEY'));
    });

    test('cloud-only without a key still degrades to local', () {
      final d = ModelRouter(env: const {'ORCH_ROUTER': 'cloud-only'})
          .route(task: 'implement the cart endpoint', kind: 'implement');
      expect(d.tier, 'local');
      expect(d.reason, contains('degraded to local'));
    });
  });

  group('env overrides', () {
    test('ORCH_MODEL_* override the tier models', () {
      final router = ModelRouter(env: const {
        ...withKey,
        'ORCH_MODEL_FAST': 'fast-x',
        'ORCH_MODEL_BALANCED': 'balanced-x',
        'ORCH_MODEL_DEEP': 'deep-x',
      });
      expect(router.route(task: 'q' * 700, kind: 'chat').model, 'fast-x');
      expect(
          router.route(task: 'review it', kind: 'review').model, 'balanced-x');
      expect(router.route(task: 'implement it', kind: 'implement').model,
          'deep-x');
    });

    test('ORCH_ROUTER=local-only pins everything to local', () {
      final router =
          ModelRouter(env: const {...withKey, 'ORCH_ROUTER': 'local-only'});
      final d = router.route(task: 'implement the cart', kind: 'implement');
      expect(d.tier, 'local');
      expect(d.reason, contains('local-only'));
    });

    test('ORCH_ROUTER=cloud-only lifts local picks to fast', () {
      final router =
          ModelRouter(env: const {...withKey, 'ORCH_ROUTER': 'cloud-only'});
      final d = router.route(task: 'hi', kind: 'chat');
      expect(d.tier, 'fast');
      expect(d.model, 'claude-haiku-4-5');
    });

    test('ORCH_OLLAMA_MODEL names the local model', () {
      final router = ModelRouter(env: const {'ORCH_OLLAMA_MODEL': 'nemo-x'});
      expect(router.route(task: 'hi', kind: 'chat').model, 'nemo-x');
    });
  });

  group('escalation', () {
    test('chain walks local -> fast -> balanced -> deep and ends', () {
      final router = routerWith();
      final seen = <String>[];
      RouteDecision? d = router.route(task: 'hi', kind: 'chat');
      while (d != null) {
        seen.add(d.tier);
        d = router.escalate(d);
      }
      expect(seen, ['local', 'fast', 'balanced', 'deep']);
    });

    test('escalation carries the next model and a reason', () {
      final router = routerWith();
      final next =
          router.escalate(router.route(task: 'review it', kind: 'review'))!;
      expect(next.tier, 'deep');
      expect(next.model, 'claude-opus-4-8');
      expect(next.reason, contains('escalated from balanced'));
    });

    test('without an API key there is nothing to escalate to', () {
      final router = ModelRouter(env: const {});
      final d = router.route(task: 'hi', kind: 'chat');
      expect(router.escalate(d), isNull);
    });

    test('local-only never escalates', () {
      final router =
          ModelRouter(env: const {...withKey, 'ORCH_ROUTER': 'local-only'});
      final d = router.route(task: 'implement it', kind: 'implement');
      expect(router.escalate(d), isNull);
    });
  });

  group('brainFor', () {
    test('local decisions reuse one OllamaBrain instance', () {
      final router = routerWith();
      final d = router.route(task: 'hi', kind: 'chat');
      final a = router.brainFor(d);
      expect(a, isA<OllamaBrain>());
      expect(identical(a, router.brainFor(d)), isTrue);
    });

    test('cloud decisions reuse one ClaudeApiBrain per model', () {
      final router = routerWith();
      final d = router.route(task: 'implement the API', kind: 'implement');
      final a = router.brainFor(d);
      expect(a, isA<ClaudeApiBrain>());
      expect(a.name, 'claude:claude-opus-4-8');
      expect(a.billsTokens, isTrue);
      expect(identical(a, router.brainFor(d)), isTrue);
      // Escalating from balanced lands on the same deep instance.
      final viaEscalation = router
          .brainFor(router.escalate(router.route(task: 'r', kind: 'review'))!);
      expect(identical(a, viaEscalation), isTrue);
    });

    test('unknown tier falls back to the deterministic brain', () {
      expect(routerWith().brainForTier('instant'), isA<DeterministicBrain>());
    });
  });

  group('BrainSelector claude modes', () {
    test('ORCH_BRAIN=claude-balanced selects the balanced ClaudeApiBrain',
        () async {
      final selector = BrainSelector(
          env: const {...withKey, 'ORCH_BRAIN': 'claude-balanced'});
      final brain = await selector.select();
      expect(brain, isA<ClaudeApiBrain>());
      expect(brain.name, 'claude:claude-sonnet-4-6');
      expect(brain.billsTokens, isTrue);
      final desc = await selector.describe();
      expect(desc['token_cost'], 'metered');
    });

    test('claude-fast and claude-deep map to their tier models', () async {
      final fast =
          BrainSelector(env: const {...withKey, 'ORCH_BRAIN': 'claude-fast'});
      expect((await fast.select()).name, 'claude:claude-haiku-4-5');
      final deep =
          BrainSelector(env: const {...withKey, 'ORCH_BRAIN': 'claude-deep'});
      expect((await deep.select()).name, 'claude:claude-opus-4-8');
    });

    test('claude tiers honor ORCH_MODEL_* overrides', () async {
      final selector = BrainSelector(env: const {
        ...withKey,
        'ORCH_BRAIN': 'claude-deep',
        'ORCH_MODEL_DEEP': 'deep-x',
      });
      expect((await selector.select()).name, 'claude:deep-x');
    });

    test('existing modes stay byte-compatible', () async {
      final deterministic =
          BrainSelector(env: const {'ORCH_BRAIN': 'deterministic'});
      expect(await deterministic.select(), isA<DeterministicBrain>());

      final ollama = BrainSelector(env: const {
        'ORCH_BRAIN': 'ollama',
        'ORCH_OLLAMA_MODEL': 'nemo-x',
      });
      expect((await ollama.select()).name, 'ollama:nemo-x');
    });
  });

  group('NVIDIA free tier', () {
    test('with only an NVIDIA key, fast/balanced route to NVIDIA models', () {
      final router = ModelRouter(env: withNvidia);
      final fast = router.route(task: 'q' * 700, kind: 'chat');
      expect(fast.tier, 'fast');
      expect(fast.provider, 'nvidia');
      expect(fast.model, 'meta/llama-3.3-70b-instruct');

      final balanced = router.route(task: 'review the diff', kind: 'review');
      expect(balanced.provider, 'nvidia');
      expect(balanced.model, 'nvidia/llama-3.3-nemotron-super-49b-v1.5');
    });

    test('deep prefers Claude when both keys exist, NVIDIA elsewhere', () {
      final both = ModelRouter(env: withBoth);
      final deep = both.route(task: 'implement the cart', kind: 'implement');
      expect(deep.tier, 'deep');
      expect(deep.provider, 'anthropic');
      expect(deep.model, 'claude-opus-4-8');
      // fast/balanced still take the free NVIDIA path even with a Claude key.
      expect(both.route(task: 'q' * 700, kind: 'chat').provider, 'nvidia');
    });

    test('deep falls back to NVIDIA when no Claude key', () {
      final d = ModelRouter(env: withNvidia)
          .route(task: 'implement the cart', kind: 'implement');
      expect(d.tier, 'deep');
      expect(d.provider, 'nvidia');
      expect(d.model, 'qwen/qwen3.5-397b-a17b');
    });

    test('an NVIDIA key alone makes cloud tiers reachable', () {
      final router = ModelRouter(env: withNvidia);
      expect(router.hasApiKey, isTrue);
      expect(router.hasNvidiaKey, isTrue);
      expect(router.hasAnthropicKey, isFalse);
      // auto no longer degrades a medium task to local — NVIDIA serves it.
      expect(router.route(task: 'q' * 700, kind: 'chat').tier, 'fast');
    });

    test('brainForTier builds an OpenAiCompatBrain for NVIDIA tiers', () {
      final router = ModelRouter(env: withNvidia);
      final brain = router.brainForTier('fast');
      expect(brain, isA<OpenAiCompatBrain>());
      expect(brain.name, 'nvidia:meta/llama-3.3-70b-instruct');
      expect(brain.billsTokens, isFalse); // free tier
      // Claude deep brain when both keys present.
      expect(ModelRouter(env: withBoth).brainForTier('deep'),
          isA<ClaudeApiBrain>());
    });

    test('ORCH_PROVIDER_<TIER> forces a provider when its key exists', () {
      final pinClaude = ModelRouter(
          env: const {...withBoth, 'ORCH_PROVIDER_FAST': 'anthropic'});
      expect(pinClaude.route(task: 'q' * 700, kind: 'chat').provider,
          'anthropic');
      final pinNvidia = ModelRouter(
          env: const {...withBoth, 'ORCH_PROVIDER_DEEP': 'nvidia'});
      expect(pinNvidia.route(task: 'implement it', kind: 'implement').provider,
          'nvidia');
    });

    test('ORCH_NVIDIA_MODEL_<TIER> overrides the NVIDIA model', () {
      final router = ModelRouter(
          env: const {...withNvidia, 'ORCH_NVIDIA_MODEL_FAST': 'meta/llama-x'});
      expect(router.route(task: 'q' * 700, kind: 'chat').model, 'meta/llama-x');
    });

    test('generic ORCH_MODEL_<TIER> still wins over the NVIDIA default', () {
      final router =
          ModelRouter(env: const {...withNvidia, 'ORCH_MODEL_FAST': 'pinned'});
      expect(router.route(task: 'q' * 700, kind: 'chat').model, 'pinned');
    });

    test('no keys at all still degrades cloud picks to local', () {
      final d = ModelRouter(env: const {})
          .route(task: 'q' * 700, kind: 'chat');
      expect(d.tier, 'local');
      expect(d.provider, 'local');
    });
  });
}
