import 'package:flutter/material.dart';

/// Semantic status colors for orchestration UI.
class OrchStatusColors {
  const OrchStatusColors({
    required this.running,
    required this.awaiting,
    required this.error,
    required this.idle,
    required this.success,
    required this.runningBg,
    required this.awaitingBg,
    required this.errorBg,
    required this.idleBg,
    required this.successBg,
  });

  final Color running;
  final Color awaiting;
  final Color error;
  final Color idle;
  final Color success;
  final Color runningBg;
  final Color awaitingBg;
  final Color errorBg;
  final Color idleBg;
  final Color successBg;

  static OrchStatusColors light = OrchStatusColors(
    running: const Color(0xFF1565C0),
    awaiting: const Color(0xFFE65100),
    error: const Color(0xFFC62828),
    idle: const Color(0xFF616161),
    success: const Color(0xFF2E7D32),
    runningBg: const Color(0xFFE3F2FD),
    awaitingBg: const Color(0xFFFFF3E0),
    errorBg: const Color(0xFFFFEBEE),
    idleBg: const Color(0xFFF5F5F5),
    successBg: const Color(0xFFE8F5E9),
  );

  static OrchStatusColors dark = OrchStatusColors(
    running: const Color(0xFF64B5F6),
    awaiting: const Color(0xFFFFB74D),
    error: const Color(0xFFEF5350),
    idle: const Color(0xFFBDBDBD),
    success: const Color(0xFF81C784),
    runningBg: const Color(0xFF0D47A1).withValues(alpha: 0.35),
    awaitingBg: const Color(0xFFE65100).withValues(alpha: 0.25),
    errorBg: const Color(0xFFB71C1C).withValues(alpha: 0.3),
    idleBg: const Color(0xFF424242).withValues(alpha: 0.5),
    successBg: const Color(0xFF1B5E20).withValues(alpha: 0.35),
  );
}

class OrchSpacing extends ThemeExtension<OrchSpacing> {
  const OrchSpacing({
    this.xs = 4,
    this.sm = 8,
    this.md = 12,
    this.lg = 16,
    this.xl = 24,
  });

  final double xs;
  final double sm;
  final double md;
  final double lg;
  final double xl;

  static const OrchSpacing standard = OrchSpacing();

  @override
  OrchSpacing copyWith({
    double? xs,
    double? sm,
    double? md,
    double? lg,
    double? xl,
  }) {
    return OrchSpacing(
      xs: xs ?? this.xs,
      sm: sm ?? this.sm,
      md: md ?? this.md,
      lg: lg ?? this.lg,
      xl: xl ?? this.xl,
    );
  }

  @override
  OrchSpacing lerp(ThemeExtension<OrchSpacing>? other, double t) => this;
}

class OrchRadii extends ThemeExtension<OrchRadii> {
  const OrchRadii({
    this.card = 12,
    this.bubble = 14,
    this.chip = 20,
  });

  final double card;
  final double bubble;
  final double chip;

  static const OrchRadii standard = OrchRadii();

  @override
  OrchRadii copyWith({double? card, double? bubble, double? chip}) {
    return OrchRadii(
      card: card ?? this.card,
      bubble: bubble ?? this.bubble,
      chip: chip ?? this.chip,
    );
  }

  @override
  OrchRadii lerp(ThemeExtension<OrchRadii>? other, double t) => this;
}

extension OrchThemeContext on BuildContext {
  OrchStatusColors get orchStatus {
    final brightness = Theme.of(this).brightness;
    return brightness == Brightness.dark
        ? OrchStatusColors.dark
        : OrchStatusColors.light;
  }

  OrchSpacing get orchSpacing =>
      Theme.of(this).extension<OrchSpacing>() ?? OrchSpacing.standard;

  OrchRadii get orchRadii =>
      Theme.of(this).extension<OrchRadii>() ?? OrchRadii.standard;
}
