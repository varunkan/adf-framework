import { useColorScheme } from 'react-native';
import { Theme, themeFor } from './tokens';

/** The active theme, automatically light/dark from the OS color scheme. No provider
 *  needed — every component just calls `const t = useTheme()`. */
export function useTheme(): Theme {
  return themeFor(useColorScheme());
}
