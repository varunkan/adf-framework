import 'package:flutter/material.dart';

import 'typewriter_text.dart';

/// Cursor-style plain chain-of-thought (muted prose, no per-step cards).
class PlainThoughtView extends StatelessWidget {
  const PlainThoughtView({
    super.key,
    required this.lines,
    this.isLive = false,
  });

  final List<String> lines;
  final bool isLive;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final thoughtColor = scheme.onSurfaceVariant.withValues(alpha: 0.92);

    if (lines.isEmpty && !isLive) {
      return const SizedBox.shrink();
    }

    return Padding(
      padding: const EdgeInsets.only(top: 4, bottom: 16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (lines.isEmpty && isLive)
            Text(
              'Thinking…',
              style: TextStyle(
                fontSize: 14,
                height: 1.5,
                color: thoughtColor,
                fontStyle: FontStyle.italic,
              ),
            )
          else
            ...List.generate(lines.length, (i) {
              final style = TextStyle(
                fontSize: 14,
                height: 1.55,
                color: thoughtColor,
                fontWeight: FontWeight.w400,
              );
              // The live, actively-streaming line types out (the "watch it type"
              // feel); already-finalized lines render statically.
              final typeIt = isLive && i == lines.length - 1;
              return Padding(
                padding: const EdgeInsets.only(bottom: 14),
                child: typeIt
                    ? TypewriterText(lines[i], style: style)
                    : Text(lines[i], style: style),
              );
            }),
          if (isLive && lines.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Text(
                'Still updating… (run continues in the background)',
                style: TextStyle(
                  fontSize: 12,
                  height: 1.35,
                  fontStyle: FontStyle.italic,
                  color: thoughtColor.withValues(alpha: 0.65),
                ),
              ),
            ),
        ],
      ),
    );
  }
}
