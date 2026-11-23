// @vitest-environment node
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

/**
 * The design tokens' contract (globals.css): every colour role has a light and a dark value (`light-dark()`), and in
 * both themes every text colour reads at WCAG AA (4.5:1) on every background role, and borders/focus at 3:1.
 */
const CSS = readFileSync(new URL("./globals.css", import.meta.url), "utf8");

function rootTokens(): Map<string, string> {
  const root = /:root\s*\{([\s\S]*?)\n\}/.exec(CSS)?.[1] ?? "";
  const tokens = new Map<string, string>();
  for (const [, name, value] of root
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) {
    tokens.set(name, value.trim());
  }
  return tokens;
}

const TOKENS = rootTokens();
const ROLES = [...TOKENS.keys()].filter((name) => name.startsWith("--color-"));

/** A colour role's value in one theme, with palette var()s resolved. */
function colour(role: string, theme: "light" | "dark"): string {
  let value = TOKENS.get(`--color-${role}`);
  if (value === undefined) throw new Error(`No --color-${role}`);
  const pair = /^light-dark\((.+)\)$/.exec(value);
  if (pair) {
    const [light, dark] = splitTopLevel(pair[1]);
    value = theme === "light" ? light : dark;
  }
  for (let ref = /^var\((--[\w-]+)\)$/.exec(value); ref; ref = /^var\((--[\w-]+)\)$/.exec(value)) {
    value = TOKENS.get(ref[1]) ?? "";
  }
  return value;
}

function splitTopLevel(args: string): string[] {
  let depth = 0;
  for (let i = 0; i < args.length; i++) {
    if (args[i] === "(") depth++;
    else if (args[i] === ")") depth--;
    else if (args[i] === "," && depth === 0) return [args.slice(0, i).trim(), args.slice(i + 1).trim()];
  }
  throw new Error(`Not a pair: ${args}`);
}

function luminance(hex: string): number {
  const match = /^#([0-9a-f]{6})$/i.exec(hex);
  if (!match) throw new Error(`Not a hex colour: ${hex}`);
  const [r, g, b] = [0, 2, 4].map((i) => {
    const c = parseInt(match[1].slice(i, i + 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

const TEXT = ["text", "text-muted", "primary", "primary-hover", "danger", "danger-strong", "success", "warning-text"];
const BACKGROUNDS = [
  "bg",
  "surface",
  "surface-raised",
  "primary-tint",
  "primary-tint-strong",
  "danger-bg",
  "success-bg",
  "warning-bg",
  "highlight",
];
const ON = [
  ["on-primary", "primary"],
  ["on-primary", "primary-hover"],
  ["on-danger", "danger"],
  ["on-danger", "danger-strong"],
];
const NON_TEXT = [
  ["border-strong", "bg"],
  ["border-strong", "surface"],
  ["focus", "bg"],
  ["focus", "surface"],
  ["focus", "surface-raised"],
];

describe("Design tokens", () => {
  it("give every colour role a light and a dark value", () => {
    expect(ROLES.length).toBeGreaterThan(20);
    const single = ROLES.filter((role) => !TOKENS.get(role)?.startsWith("light-dark("));
    expect(single).toEqual([]);
  });

  for (const theme of ["light", "dark"] as const) {
    it(`meet AA contrast in the ${theme} theme`, () => {
      const failing: string[] = [];
      const check = (fg: string, bg: string, min: number) => {
        const ratio = contrast(colour(fg, theme), colour(bg, theme));
        if (ratio < min) failing.push(`${fg} on ${bg}: ${ratio.toFixed(2)}`);
      };
      for (const fg of TEXT) for (const bg of BACKGROUNDS) check(fg, bg, 4.5);
      for (const [fg, bg] of ON) check(fg, bg, 4.5);
      for (const [fg, bg] of NON_TEXT) check(fg, bg, 3);
      expect(failing).toEqual([]);
    });
  }

  it("follow the OS unless the officer chose a theme", () => {
    expect(CSS).toMatch(/:root\s*\{[^}]*color-scheme:\s*light dark/);
    expect(CSS).toMatch(/:root\[data-theme="light"\]\s*\{\s*color-scheme:\s*light;/);
    expect(CSS).toMatch(/:root\[data-theme="dark"\]\s*\{\s*color-scheme:\s*dark;/);
  });
});
