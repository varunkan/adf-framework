import 'package:flutter/material.dart';

/// Responsive layout: 3-column desktop, tabbed mobile.
class OrchestrationShellBody extends StatefulWidget {
  const OrchestrationShellBody({
    super.key,
    required this.statusBar,
    required this.chatContent,
    required this.composer,
    this.approvalBar,
    this.pipelineRail,
    this.inspector,
    this.phaseSummary,
    this.isRunning = false,
    this.featureId = '',
    this.onRefresh,
  });

  final String featureId;
  final Widget statusBar;
  final Widget chatContent;
  final Widget composer;
  final Widget? approvalBar;
  final Widget? pipelineRail;
  final Widget? inspector;
  final String? phaseSummary;
  final bool isRunning;
  final VoidCallback? onRefresh;

  static const double breakpoint = 900;

  @override
  State<OrchestrationShellBody> createState() => _OrchestrationShellBodyState();
}

class _OrchestrationShellBodyState extends State<OrchestrationShellBody>
    with SingleTickerProviderStateMixin {
  late TabController _tabController;

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: 3, vsync: this);
  }

  @override
  void dispose() {
    _tabController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final width = MediaQuery.sizeOf(context).width;
    if (width >= OrchestrationShellBody.breakpoint) {
      return Column(
        children: [
          widget.statusBar,
          Expanded(
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                if (widget.pipelineRail != null)
                  SizedBox(
                    width: 240,
                    child: Card(
                      margin: const EdgeInsets.fromLTRB(12, 0, 0, 12),
                      child: widget.pipelineRail,
                    ),
                  ),
                Expanded(child: _chatStack()),
                if (widget.inspector != null)
                  SizedBox(
                    width: 320,
                    child: Card(
                      margin: const EdgeInsets.fromLTRB(0, 0, 12, 12),
                      child: widget.inspector,
                    ),
                  ),
              ],
            ),
          ),
        ],
      );
    }

    return Column(
      children: [
        widget.statusBar,
        TabBar(
          controller: _tabController,
          tabs: const [
            Tab(text: 'Chat'),
            Tab(text: 'Pipeline'),
            Tab(text: 'Details'),
          ],
        ),
        Expanded(
          child: TabBarView(
            controller: _tabController,
            children: [
              _chatStack(),
              widget.pipelineRail != null
                  ? Card(
                      margin: const EdgeInsets.all(12),
                      child: widget.pipelineRail,
                    )
                  : const Center(child: Text('No pipeline')),
              widget.inspector ?? const Center(child: Text('No details')),
            ],
          ),
        ),
      ],
    );
  }

  Widget _chatStack() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Expanded(child: widget.chatContent),
        if (widget.approvalBar != null) widget.approvalBar!,
        widget.composer,
      ],
    );
  }
}
