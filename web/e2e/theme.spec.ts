import { expect, test, type Page } from "@playwright/test";
import { OFFICER, signIn, visit } from "./helpers";

/** The page background each theme paints (globals.css --color-bg). */
const LIGHT = "rgb(255, 255, 255)";
const DARK = "rgb(21, 24, 27)";

function background(page: Page) {
  return page.evaluate(() => getComputedStyle(document.body).backgroundColor);
}

function themeChoice(page: Page, name: "Light" | "Dark" | "System") {
  return page.getByRole("radiogroup", { name: "Theme" }).getByRole("radio", { name });
}

test.describe("with no saved choice", () => {
  for (const [colorScheme, expected] of [
    ["light", LIGHT],
    ["dark", DARK],
  ] as const) {
    test.describe(`on a ${colorScheme} OS`, () => {
      test.use({ colorScheme });

      test(`the app is ${colorScheme}`, async ({ page }) => {
        await signIn(page, OFFICER);
        await expect(themeChoice(page, "System")).toBeChecked();
        expect(await background(page)).toBe(expected);
      });
    });
  }
});

test.describe("on a light OS", () => {
  test.use({ colorScheme: "light" });

  test("Dark applies at once and is remembered; System follows the OS again", async ({ page }) => {
    await signIn(page, OFFICER);
    await themeChoice(page, "Dark").check();
    expect(await background(page)).toBe(DARK);

    await visit(page, "/library");
    await expect(themeChoice(page, "Dark")).toBeChecked();
    expect(await background(page)).toBe(DARK);
    // Rendered by the server in the page's first byte, so a reload never paints light first.
    expect(await (await page.request.get("/library")).text()).toMatch(/<html[^>]*data-theme="dark"/);

    await themeChoice(page, "System").check();
    expect(await background(page)).toBe(LIGHT);
    await page.reload();
    await expect(themeChoice(page, "System")).toBeChecked();
    expect(await background(page)).toBe(LIGHT);
  });
});

test.describe("before any script runs", () => {
  test.use({ javaScriptEnabled: false });

  test.describe("on a dark OS", () => {
    test.use({ colorScheme: "dark" });

    test("the first paint is dark", async ({ page }) => {
      await page.goto("/sign-in");
      expect(await background(page)).toBe(DARK);
    });
  });

  test.describe("on a light OS with Dark saved", () => {
    test.use({ colorScheme: "light" });

    test("the first paint is dark", async ({ page, context, baseURL }) => {
      await context.addCookies([{ name: "plg_theme", value: "dark", url: baseURL }]);
      await page.goto("/sign-in");
      expect(await background(page)).toBe(DARK);
    });
  });
});
