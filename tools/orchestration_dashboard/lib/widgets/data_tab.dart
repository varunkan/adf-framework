import 'package:flutter/material.dart';

import '../services/api_client.dart';

/// The **Data tab** — a read-only window into the app's live SQLite database.
/// Pick a table, see its rows. ADF owns the data layer, so it can show you
/// exactly what your app persisted — visibility a hosted-DB builder hides.
class DataTab extends StatefulWidget {
  const DataTab({super.key, required this.api, required this.featureId});

  final ApiClient api;
  final String featureId;

  @override
  State<DataTab> createState() => _DataTabState();
}

class _DataTabState extends State<DataTab> {
  Map<String, dynamic>? _data;
  Map<String, dynamic>? _rows;
  String? _selected;
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _loadTables();
  }

  Future<void> _loadTables() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final d = await widget.api.getData(widget.featureId);
      if (!mounted) return;
      setState(() => _data = d);
      final tables = (d['tables'] as List?) ?? const [];
      if (tables.isNotEmpty) await _select(tables.first['name'] as String);
    } catch (e) {
      if (mounted) setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _select(String table) async {
    setState(() => _selected = table);
    try {
      final r = await widget.api.getTableRows(widget.featureId, table);
      if (mounted) setState(() => _rows = r);
    } catch (e) {
      if (mounted) setState(() => _rows = {'error': e.toString()});
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_loading && _data == null) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_error != null) {
      return Center(child: Text('Data unavailable: $_error'));
    }
    if (_data?['has_db'] != true) {
      return const Center(
        key: Key('data-empty'),
        child: Text('No database yet — build the app, add some data, then look here.'),
      );
    }
    final tables = ((_data?['tables'] as List?) ?? const [])
        .cast<Map<String, dynamic>>();
    return Padding(
      key: const Key('data-tab'),
      padding: const EdgeInsets.all(12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              for (final t in tables)
                ChoiceChip(
                  label: Text('${t['name']} (${t['rows']})'),
                  selected: _selected == t['name'],
                  onSelected: (_) => _select(t['name'] as String),
                ),
            ],
          ),
          const SizedBox(height: 12),
          Expanded(child: _rowsView()),
        ],
      ),
    );
  }

  Widget _rowsView() {
    final rows = _rows;
    if (rows == null) return const SizedBox.shrink();
    if (rows['error'] != null) return Text('Error: ${rows['error']}');
    final cols = (rows['columns'] as List?)?.cast<String>() ?? const [];
    final data = (rows['rows'] as List?) ?? const [];
    if (cols.isEmpty) return const Text('No columns.');
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: SingleChildScrollView(
        child: DataTable(
          columns: [for (final c in cols) DataColumn(label: Text(c))],
          rows: [
            for (final r in data)
              DataRow(cells: [
                for (final cell in (r as List))
                  DataCell(Text('${cell ?? ''}')),
              ]),
          ],
        ),
      ),
    );
  }
}
