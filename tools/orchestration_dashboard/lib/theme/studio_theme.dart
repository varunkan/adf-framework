import 'package:flutter/material.dart';

import 'orchestration_colors.dart';

/// Lovable-inspired dark studio theme for ADF agentic builder.
class StudioTheme {
  static const Color accent = Color(0xFF8B5CF6);
  static const Color accentSoft = Color(0xFF6366F1);
  static const Color surface = Color(0xFF0F0F12);
  static const Color panel = Color(0xFF17171C);
  static const Color panelBorder = Color(0xFF2A2A33);

  static ThemeData dark() {
    const scheme = ColorScheme.dark(
      primary: accent,
      secondary: accentSoft,
      surface: surface,
      onSurface: Color(0xFFECECF1),
      outline: panelBorder,
      surfaceContainerHighest: panel,
    );
    return ThemeData(
      useMaterial3: true,
      brightness: Brightness.dark,
      colorScheme: scheme,
      scaffoldBackgroundColor: surface,
      extensions: const [OrchSpacing.standard, OrchRadii.standard],
      appBarTheme: const AppBarTheme(
        backgroundColor: surface,
        foregroundColor: Color(0xFFECECF1),
        elevation: 0,
      ),
      cardTheme: CardThemeData(
        color: panel,
        elevation: 0,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(16),
          side: const BorderSide(color: panelBorder),
        ),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: panel,
        hintStyle: TextStyle(color: Colors.white.withValues(alpha: 0.45)),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(14),
          borderSide: const BorderSide(color: panelBorder),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(14),
          borderSide: const BorderSide(color: accent, width: 2),
        ),
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          backgroundColor: accent,
          foregroundColor: Colors.white,
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
        ),
      ),
    );
  }
}
