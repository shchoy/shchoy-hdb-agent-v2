import { expect, test } from "@playwright/test";
import {
  FIRST_OPEN,
  INBOX_QUESTION,
  QUESTION,
  REMINDER_GOLDEN_LEAF,
  answer,
  askInNewConversation,
  OFFICER,
  visit,
  seriousViolations,
  signIn,
} from "./helpers";

/**
 * Zero serious or critical WCAG 2.1 A/AA violations (axe) on every screen, in the states officers see, in both
 * themes: the OS preference is emulated and, with no saved choice, the app follows it.
 */
for (const colorScheme of ["light", "dark"] as const) {
  test.describe(`${colorScheme} theme`, () => {
    test.use({ colorScheme });

    test("sign-in screen", async ({ page }) => {
      await visit(page, "/sign-in");
      await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
      expect(await seriousViolations(page)).toEqual([]);
    });

    test("ask screen: the welcome, a cited answer with its source open, then the conversation history", async ({ page }) => {
      await signIn(page, OFFICER);
      await expect(page.getByRole("list", { name: "Starter prompts" })).toBeVisible();
      expect(await seriousViolations(page)).toEqual([]);

      await askInNewConversation(page, QUESTION);
      const chip = answer(page).getByRole("list", { name: "Sources" }).getByRole("listitem").first();
      await chip.locator("summary").click();
      await chip.getByRole("button", { name: "Open source" }).click();
      await expect(chip.locator("mark")).toBeVisible(FIRST_OPEN);
      expect(await seriousViolations(page)).toEqual([]);

      await visit(page, "/"); // the same tab: it reopens the conversation
      await expect(page.getByRole("list", { name: "Earlier in this conversation" })).toBeVisible();
      expect(await seriousViolations(page)).toEqual([]);
    });

    test("ask screen: a flagged document and a draft letter", async ({ page }) => {
      await signIn(page, OFFICER);
      await askInNewConversation(page, INBOX_QUESTION);
      await expect(answer(page).getByRole("alert")).toBeVisible();
      expect(await seriousViolations(page)).toEqual([]);

      await askInNewConversation(page, REMINDER_GOLDEN_LEAF);
      await expect(answer(page)).toContainText("It waits for your approval.");
      expect(await seriousViolations(page)).toEqual([]);
    });

    test("approvals inbox with a pending letter", async ({ page }) => {
      await signIn(page, OFFICER);
      await askInNewConversation(page, REMINDER_GOLDEN_LEAF);
      await visit(page, "/approvals");
      await expect(page.getByRole("list", { name: "Pending approvals" })).toBeVisible();
      expect(await seriousViolations(page)).toEqual([]);
    });

    for (const [path, heading] of [
      ["/memory", "What I remember about you"],
      ["/tasks", "My tasks"],
      ["/doc-check", "Document check"],
      ["/library", "Library"],
    ] as const) {
      test(`${heading} screen`, async ({ page }) => {
        await signIn(page, OFFICER);
        await visit(page, path);
        await expect(page.getByRole("heading", { level: 1 })).toContainText(heading);
        expect(await seriousViolations(page)).toEqual([]);
      });
    }

    test("a result card's table scrolls inside the card on a phone", async ({ page }) => {
      await signIn(page, OFFICER);
      await page.setViewportSize({ width: 390, height: 844 });
      await visit(page, "/tasks");
      const table = page.getByRole("region", { name: "Ranked tasks" });
      await expect(table).toBeVisible();
      const { scrolls, pageOverflows } = await table.evaluate((el) => ({
        scrolls: el.scrollWidth > el.clientWidth,
        pageOverflows: document.documentElement.scrollWidth > window.innerWidth,
      }));
      expect(scrolls).toBe(true);
      expect(pageOverflows).toBe(false);
      expect(await seriousViolations(page)).toEqual([]);
    });

    test("the sidebar as a drawer on a phone", async ({ page }) => {
      await signIn(page, OFFICER); // at desktop width: signIn checks the persona shown in the sidebar
      await page.setViewportSize({ width: 390, height: 844 });
      const menu = page.getByRole("button", { name: "Menu", exact: true });
      await expect(page.getByRole("navigation", { name: "Main" })).toBeHidden();
      expect(await seriousViolations(page)).toEqual([]);

      await menu.click();
      const drawer = page.getByRole("dialog", { name: "Menu" });
      await expect(drawer.getByRole("link", { name: "Ask", exact: true })).toHaveAttribute("aria-current", "page");
      expect(await seriousViolations(page)).toEqual([]);

      await page.keyboard.press("Escape");
      await expect(drawer).toBeHidden();
      await expect(menu).toBeFocused();
    });
  });
}
