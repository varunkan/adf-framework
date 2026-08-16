// The design-system token source of truth. EVERY component reads these — no raw
// hex anywhere else (the policy gate's no_raw_hex rule enforces it), so every
// generated app is on-theme and light/dark-correct BY CONSTRUCTION.

export interface ThemeColors {
  bg: string;
  surface: string;
  surfaceAlt: string;
  text: string;
  textMuted: string;
  primary: string;
  onPrimary: string;
  border: string;
  danger: string;
  onDanger: string;
  success: string;
  warning: string;
}

export interface TypeToken {
  fontSize: number;
  fontWeight: '400' | '500' | '600' | '700' | '800';
}

export interface Theme {
  name: 'light' | 'dark';
  colors: ThemeColors;
  spacing: { xs: number; sm: number; md: number; lg: number; xl: number };
  radius: { sm: number; md: number; lg: number; full: number };
  type: { h1: TypeToken; h2: TypeToken; body: TypeToken; caption: TypeToken; label: TypeToken };
  icon: { sm: number; md: number; lg: number };
}

const lightColors: ThemeColors = {
  bg: '#f9fafb',
  surface: '#ffffff',
  surfaceAlt: '#e5e7eb',
  text: '#111827',
  textMuted: '#6b7280',
  primary: '#2563eb',
  onPrimary: '#ffffff',
  border: '#d1d5db',
  danger: '#dc2626',
  onDanger: '#ffffff',
  success: '#16a34a',
  warning: '#d97706',
};

const darkColors: ThemeColors = {
  bg: '#0b0f17',
  surface: '#111827',
  surfaceAlt: '#1f2937',
  text: '#f3f4f6',
  textMuted: '#9ca3af',
  primary: '#3b82f6',
  onPrimary: '#0b0f17',
  border: '#374151',
  danger: '#ef4444',
  onDanger: '#0b0f17',
  success: '#22c55e',
  warning: '#f59e0b',
};

const base = {
  spacing: { xs: 4, sm: 8, md: 12, lg: 16, xl: 24 },
  radius: { sm: 6, md: 10, lg: 16, full: 9999 },
  type: {
    h1: { fontSize: 28, fontWeight: '800' as const },
    h2: { fontSize: 20, fontWeight: '700' as const },
    body: { fontSize: 16, fontWeight: '400' as const },
    caption: { fontSize: 13, fontWeight: '400' as const },
    label: { fontSize: 14, fontWeight: '500' as const },
  },
  icon: { sm: 16, md: 22, lg: 28 },
};

export const lightTheme: Theme = { name: 'light', colors: lightColors, ...base };
export const darkTheme: Theme = { name: 'dark', colors: darkColors, ...base };

/** Resolve the theme for a color scheme. Pure + total — the testable core. */
export function themeFor(scheme: 'light' | 'dark' | null | undefined): Theme {
  return scheme === 'dark' ? darkTheme : lightTheme;
}
