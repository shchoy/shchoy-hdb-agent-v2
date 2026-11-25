import { expect, test } from "@playwright/test";
import {
  FIRST_OPEN,
  INBOX_QUESTION,
  QUESTION,
  REMINDER_GOLDEN_LEAF,
  answer,
  askInNewConversation,
  marker,
  openConversation,
  OFFICER,
  sourcesPanel,
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
      await marker(answer(page), 1).click();
      const chip = sourcesPanel(page).getByRole("listitem").first();
      await chip.getByText("Quote").click();
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
      // The in-chat approval card, with its letter preview and decision controls.
      await expect(answer(page).getByRole("button", { name: "Approve and send" })).toBeVisible();
      expect(await seriousViolations(page)).toEqual([]);
    });

    test("approvals inbox with a pending letter", async ({ page }) => {
      await signIn(page, OFFICER);
      await askInNewConversation(page, REMINDER_GOLDEN_LEAF);
      await visit(page, "/approvals");
      await expect(page.getByRole("list", { name: "Pending approvals" })).toBeVisible();
      // The detail view too: preview, slot table and decision controls.
      await page.getByRole("list", { name: "Pending approvals" }).getByRole("button", { name: /Golden Leaf/ }).first().click();
      await expect(page.getByRole("button", { name: "Approve and send" }).first()).toBeVisible();
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

    test("the approvals inbox and an opened letter fit a phone", async ({ page }) => {
      await signIn(page, OFFICER);
      await askInNewConversation(page, REMINDER_GOLDEN_LEAF);
      await page.setViewportSize({ width: 390, height: 844 });
      await visit(page, "/approvals");
      await page.getByRole("list", { name: "Pending approvals" }).getByRole("button", { name: /Golden Leaf/ }).first().click();
      await page.getByRole("button", { name: "Edit slots" }).first().click();
      await expect(page.getByRole("button", { name: "Send edited letter" }).first()).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)).toBe(false);
      expect(await seriousViolations(page)).toEqual([]);

      await visit(page, "/memory");
      await expect(page.getByRole("heading", { level: 1 })).toContainText("What I remember about you");
      expect(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)).toBe(false);
      expect(await seriousViolations(page)).toEqual([]);
    });

    test("the Library, Tasks and Document check screens fit a phone", async ({ page }) => {
      await signIn(page, OFFICER);
      await page.setViewportSize({ width: 390, height: 844 });
      const fits = () => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);

      await visit(page, "/library");
      const categories = page.getByRole("list", { name: "Document categories" });
      await categories.getByRole("button").first().click();
      await expect(categories.getByRole("region").first()).toBeVisible();
      expect(await fits()).toBe(true);
      expect(await seriousViolations(page)).toEqual([]);
      await page.getByRole("tab", { name: "Audit findings" }).click();
      await expect(page.getByRole("tabpanel")).not.toContainText("Loading");
      expect(await fits()).toBe(true);
      expect(await seriousViolations(page)).toEqual([]);

      await visit(page, "/tasks");
      await expect(page.getByRole("table", { name: "Ranked tasks" })).toBeVisible();
      expect(await fits()).toBe(true);

      await visit(page, "/doc-check");
      await expect(page.getByRole("table", { name: "Applications" })).toBeVisible();
      expect(await fits()).toBe(true);
      expect(await seriousViolations(page)).toEqual([]);
    });

    test("a conversation's menu, its rename field and delete confirmation, also in the phone drawer", async ({ page }) => {
      await signIn(page, OFFICER);
      await askInNewConversation(page, QUESTION);
      const options = openConversation(page).getByRole("button", { name: `Options for ${QUESTION}` });

      await options.click();
      await expect(page.getByRole("menu", { name: QUESTION })).toBeVisible();
      expect(await seriousViolations(page)).toEqual([]);
      await page.getByRole("menuitem", { name: "Rename" }).click();
      await expect(page.getByRole("textbox", { name: "Conversation title" })).toBeFocused();
      expect(await seriousViolations(page)).toEqual([]);
      await page.keyboard.press("Escape");

      await options.click();
      await page.getByRole("menuitem", { name: "Delete" }).click();
      const confirm = page.getByRole("group", { name: `Delete ${QUESTION}?` });
      await expect(confirm.getByRole("button", { name: "Cancel" })).toBeFocused();
      expect(await seriousViolations(page)).toEqual([]);
      await confirm.getByRole("button", { name: "Cancel" }).click();

      await page.setViewportSize({ width: 390, height: 844 });
      await page.getByRole("button", { name: "Menu", exact: true }).click();
      const drawer = page.getByRole("dialog", { name: "Menu" });
      await openConversation(page).getByRole("button", { name: `Options for ${QUESTION}` }).click();
      await expect(drawer.getByRole("menu", { name: QUESTION })).toBeVisible();
      expect(await seriousViolations(page)).toEqual([]);
      await page.keyboard.press("Escape");
      await expect(drawer.getByRole("menu")).toHaveCount(0);
      await expect(drawer).toBeVisible();
    });

    test("conversation groups: new group, group menu, rename, delete confirmation, Move to group…, also in the drawer", async ({
      page,
    }) => {
      await signIn(page, OFFICER);
      await askInNewConversation(page, QUESTION);
      const conversations = page.getByRole("navigation", { name: "Conversations" });
      const name = `Axe group ${colorScheme} ${Date.now()}`;

      await conversations.getByRole("button", { name: "New group" }).click();
      await expect(conversations.getByRole("textbox", { name: "Group name" })).toBeFocused();
      expect(await seriousViolations(page)).toEqual([]);
      await page.keyboard.type(name);
      await page.keyboard.press("Enter");

      const options = conversations.getByRole("button", { name: `Options for group ${name}` });
      await options.click();
      await expect(page.getByRole("menu", { name: `Group ${name}` })).toBeVisible();
      expect(await seriousViolations(page)).toEqual([]);
      await page.getByRole("menuitem", { name: "Rename group" }).click();
      await expect(conversations.getByRole("textbox", { name: "Group name" })).toBeFocused();
      expect(await seriousViolations(page)).toEqual([]);
      await page.keyboard.press("Escape");

      await openConversation(page).getByRole("button", { name: `Options for ${QUESTION}` }).click();
      await page.getByRole("menuitem", { name: "Move to group…" }).click();
      await expect(page.getByRole("menu", { name: `Move ${QUESTION} to` })).toBeVisible();
      expect(await seriousViolations(page)).toEqual([]);
      await page.getByRole("menuitemradio", { name, exact: true }).click();
      await expect(conversations.getByRole("list", { name, exact: true })).toBeVisible();
      expect(await seriousViolations(page)).toEqual([]);

      await page.setViewportSize({ width: 390, height: 844 });
      await page.getByRole("button", { name: "Menu", exact: true }).click();
      const drawer = page.getByRole("dialog", { name: "Menu" });
      await openConversation(page).getByRole("button", { name: `Options for ${QUESTION}` }).click();
      await drawer.getByRole("menuitem", { name: "Move to group…" }).click();
      await expect(drawer.getByRole("menu", { name: `Move ${QUESTION} to` })).toBeVisible();
      expect(await seriousViolations(page)).toEqual([]);
      await page.keyboard.press("Escape");
      await expect(drawer.getByRole("menu")).toHaveCount(0);
      await expect(drawer).toBeVisible();

      await drawer.getByRole("button", { name: `Options for group ${name}` }).click();
      await drawer.getByRole("menuitem", { name: "Delete group" }).click();
      const confirm = drawer.getByRole("group", { name: `Delete group ${name}?` });
      await expect(confirm.getByRole("button", { name: "Cancel" })).toBeFocused();
      expect(await seriousViolations(page)).toEqual([]);
      await confirm.getByRole("button", { name: "Delete group" }).click(); // leave the shared server as found
      await expect(drawer.getByRole("list", { name, exact: true })).toHaveCount(0);
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
