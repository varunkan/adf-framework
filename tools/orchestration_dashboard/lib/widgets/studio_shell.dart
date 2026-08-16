import 'package:flutter/material.dart';

import '../theme/studio_theme.dart';

/// Lovable-style layout: pipeline rail | chat hero | live preview.
class StudioShell extends StatelessWidget {
  const StudioShell({
    super.key,
    required this.featureId,
    required this.header,
    required this.chatContent,
    required this.composer,
    required this.preview,
    this.pipelineRail,
    this.approvalBar,
    this.statusBar,
  });

  final String featureId;
  final Widget header;
  final Widget chatContent;
  final Widget composer;
  final Widget preview;
  final Widget? pipelineRail;
  final Widget? approvalBar;
  final Widget? statusBar;

  static const double breakpoint = 960;

  @override
  Widget build(BuildContext context) {
    final wide = MediaQuery.sizeOf(context).width >= breakpoint;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        header,
        if (statusBar != null) statusBar!,
        Expanded(
          child: wide ? _wide(context) : _narrow(context),
        ),
      ],
    );
  }

  Widget _wide(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (pipelineRail != null)
          SizedBox(
            width: 220,
            child: Container(
              decoration: const BoxDecoration(
                border: Border(right: BorderSide(color: StudioTheme.panelBorder)),
              ),
              child: pipelineRail,
            ),
          ),
        Expanded(
          flex: 3,
          child: Container(
            decoration: const BoxDecoration(
              border: Border(right: BorderSide(color: StudioTheme.panelBorder)),
            ),
            child: _chatColumn(),
          ),
        ),
        Expanded(
          flex: 2,
          child: preview,
        ),
      ],
    );
  }

  Widget _narrow(BuildContext context) {
    return DefaultTabController(
      length: 3,
      child: Column(
        children: [
          const TabBar(tabs: [
            Tab(text: 'Chat'),
            Tab(text: 'Preview'),
            Tab(text: 'Pipeline'),
          ]),
          Expanded(
            child: TabBarView(
              children: [
                _chatColumn(),
                preview,
                pipelineRail ?? const Center(child: Text('No pipeline')),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _chatColumn() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Expanded(child: chatContent),
        if (approvalBar != null) approvalBar!,
        composer,
      ],
    );
  }
}
