"use client";

import { useState } from "react";
import { THEME_COOKIE, type Theme, type ThemeChoice } from "@/lib/theme";
import styles from "./shell.module.css";

const CHOICES: { value: ThemeChoice; label: string }[] = [
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
  { value: "system", label: "System" },
];

/** A year: the choice outlives the session. */
const MAX_AGE = 60 * 60 * 24 * 365;

function apply(choice: ThemeChoice) {
  const root = document.documentElement;
  if (choice === "system") {
    delete root.dataset.theme;
    document.cookie = `${THEME_COOKIE}=; path=/; max-age=0; samesite=lax`;
  } else {
    root.dataset.theme = choice;
    document.cookie = `${THEME_COOKIE}=${choice}; path=/; max-age=${MAX_AGE}; samesite=lax`;
  }
}

/** Light / Dark / System. Applies at once; Light or Dark is remembered (cookie), System follows the OS again. */
export function ThemeToggle({ theme }: { theme?: Theme }) {
  const [choice, setChoice] = useState<ThemeChoice>(theme ?? "system");

  return (
    <div role="radiogroup" aria-labelledby="theme-label" className={styles.theme}>
      <span id="theme-label" className={styles.themeLabel}>
        Theme
      </span>
      <div className={styles.themeChoices}>
        {CHOICES.map(({ value, label }) => (
          <label key={value} className={styles.themeChoice}>
            <input
              type="radio"
              name="theme"
              value={value}
              checked={choice === value}
              onChange={() => {
                setChoice(value);
                apply(value);
              }}
            />
            <span>{label}</span>
          </label>
        ))}
      </div>
    </div>
  );
}
