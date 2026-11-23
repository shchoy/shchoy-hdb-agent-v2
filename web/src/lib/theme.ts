/**
 * The officer's colour theme. With no saved choice the app follows the OS (`prefers-color-scheme`); a saved Light or
 * Dark choice lives in a plain (not httpOnly) cookie, so the server renders it on <html data-theme> in the first byte:
 * no light flash before hydration, no inline script.
 */
export const THEME_COOKIE = "plg_theme";

export type Theme = "light" | "dark";
export type ThemeChoice = Theme | "system";

/** A saved theme, or undefined (follow the OS) for anything else. */
export function savedTheme(value: string | undefined): Theme | undefined {
  return value === "light" || value === "dark" ? value : undefined;
}
