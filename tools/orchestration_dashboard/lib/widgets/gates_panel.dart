import 'package:flutter/material.dart';

class GatesPanel extends StatelessWidget {
  const GatesPanel({super.key, required this.gates});

  final Map<String, dynamic> gates;

  @override
  Widget build(BuildContext context) {
    final entries = gates.entries
        .where((e) => e.value is bool)
        .toList()
      ..sort((a, b) => a.key.compareTo(b.key));
    final passed = entries.where((e) => e.value == true).length;

    return Card(
      child: ExpansionTile(
        title: const Text('Quality gates'),
        subtitle: Text('$passed/${entries.length} passed'),
        children: entries
            .map(
              (e) {
                final ok = e.value == true;
                return ListTile(
                  dense: true,
                  leading: Icon(
                    ok ? Icons.check_box : Icons.indeterminate_check_box,
                    color: ok ? Colors.green : Colors.orange.shade700,
                    size: 20,
                  ),
                  title: Text(e.key, style: const TextStyle(fontSize: 13)),
                );
              },
            )
            .toList(),
      ),
    );
  }
}
