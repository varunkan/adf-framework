import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:orchestration_dashboard/widgets/agent_conversation_view.dart';

Widget _wrap(List<Map<String, dynamic>> messages) {
  return MaterialApp(
    home: Scaffold(
      body: AgentConversationView(messages: messages),
    ),
  );
}

void main() {
  testWidgets('state reply shows instant caption with ms latency',
      (tester) async {
    await tester.pumpWidget(_wrap([
      {
        'role': 'assistant',
        'text': 'Pipeline is idle.',
        'timestamp': '2026-06-12T10:00:01Z',
        'latency_ms': 12,
        'llm_source': 'state',
      },
    ]));
    await tester.pump();
    expect(find.text('12 ms · instant'), findsOneWidget);
  });

  testWidgets('ollama reply shows short model name and seconds latency',
      (tester) async {
    await tester.pumpWidget(_wrap([
      {
        'role': 'assistant',
        'text': 'Here is the status.',
        'timestamp': '2026-06-12T10:00:02Z',
        'latency_ms': 1234,
        'llm_source': 'ollama:hf.co/nvidia/NVIDIA-Nemotron-3-Nano-4B-GGUF:Q4_K_M',
      },
    ]));
    await tester.pump();
    expect(
      find.text('1.2 s · NVIDIA-Nemotron-3-Nano-4B-GGUF (local)'),
      findsOneWidget,
    );
  });

  testWidgets('plain ollama model under a second keeps ms format',
      (tester) async {
    await tester.pumpWidget(_wrap([
      {
        'role': 'assistant',
        'text': 'Done.',
        'timestamp': '2026-06-12T10:00:03Z',
        'latency_ms': 800,
        'llm_source': 'ollama:nemotron',
      },
    ]));
    await tester.pump();
    expect(find.text('800 ms · nemotron (local)'), findsOneWidget);
  });

  testWidgets('cursor_agent source renders unchanged as cursor agent',
      (tester) async {
    await tester.pumpWidget(_wrap([
      {
        'role': 'assistant',
        'text': 'Run finished.',
        'timestamp': '2026-06-12T10:00:04Z',
        'latency_ms': 2500,
        'llm_source': 'cursor_agent',
      },
    ]));
    await tester.pump();
    expect(find.text('2.5 s · cursor agent'), findsOneWidget);
  });

  testWidgets('messages without metadata render no caption', (tester) async {
    await tester.pumpWidget(_wrap([
      {
        'role': 'assistant',
        'text': 'No metadata here.',
        'timestamp': '2026-06-12T10:00:05Z',
      },
      {
        'role': 'user',
        'text': 'A question.',
        'timestamp': '2026-06-12T10:00:06Z',
      },
    ]));
    await tester.pump();
    expect(find.textContaining('·'), findsNothing);
    expect(find.textContaining(' ms'), findsNothing);
    expect(find.textContaining('(local)'), findsNothing);
  });
}
