import AxeBuilder from "@axe-core/playwright";
import { expect, type Locator, type Page } from "@playwright/test";

/** The questions scripts/e2e_server.py scripts Claude's replies for. */
export const QUESTION = "When do we issue a letter of demand?";
export const FOLLOW_UP = "And how long does the tenant have to pay after that?";
export const REMINDER_GOLDEN_LEAF = "Draft a first reminder letter for Golden Leaf Minimart Pte Ltd's overdue rent";
export const REMINDER_HOMETOWN = "Draft a first reminder letter for Hometown Minimart Pte Ltd's overdue rent";
export const INBOX_QUESTION = "Process the latest email in the feedback inbox.";

/** The personas the tests sign in as, by name, and their staff IDs. */
export const OFFICER = "Siti Aishah Yusof";
export const OTHER_OFFICER = "Grace Chua";
const STAFF_IDS = { [OFFICER]: "S05", [OTHER_OFFICER]: "S11" } as const;
type Persona = keyof typeof STAFF_IDS;

/** Mock sign-in as a persona (through the BFF's session endpoint, which sets the session cookie), then opens the
 * Ask screen once it is interactive. */
export async function signIn(page: Page, name: Persona): Promise<void> {
  // Retried: the BFF checks the persona with plg-api, which may be busy finishing an earlier test's run.
  await expect(async () => {
    const response = await page.request.post("/api/session", { data: { staff_id: STAFF_IDS[name] } });
    expect(response.ok()).toBe(true); // 204: signed in
  }).toPass({ timeout: 30_000 });
  await visit(page, "/");
  await expect(page.getByRole("heading", { name: "Ask the Super-Librarian" })).toBeVisible();
  await expect(page.getByText(`Signed in as ${name}`)).toBeVisible();
}

/** Opens a page and waits until it has loaded its data and React has hydrated it (the dev server compiles on first
 * visit, and a click before hydration is lost). */
export async function visit(page: Page, path: string): Promise<void> {
  await page.goto(path);
  await page.waitForLoadState("networkidle");
}

/** Asks in the current conversation and waits until the answer has finished streaming (a knowledge search runs the
 * local cross-encoder: seconds each, more on a busy machine). */
export async function ask(page: Page, question: string): Promise<void> {
  await page.getByLabel("Your question").fill(question);
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  // The live run (not an earlier answer in the history) is this question's.
  await expect(page.locator("p", { hasText: `You asked: ${question}` })).toBeVisible();
  await expect(answer(page).getByRole("button", { name: "Helpful", exact: true })).toBeVisible({ timeout: 90_000 });
}

/** Starts a new conversation and asks in it. */
export async function askInNewConversation(page: Page, question: string): Promise<void> {
  await page.getByRole("button", { name: "New conversation" }).click();
  await ask(page, question);
}

/** How long the first source viewer may take to open: the dev server compiles the document routes on first use. */
export const FIRST_OPEN = { timeout: 60_000 };

/** How long a decision in the Approvals inbox may take: it resumes the run, which writes the Outbox and audit log. */
export const DECISION = { timeout: 60_000 };

/** The answer being (or just) streamed. */
export function answer(page: Page) {
  return page.getByRole("region", { name: "Answer" });
}

/** The sources panel an answer's `[n]` markers open. */
export function sourcesPanel(page: Page) {
  return page.getByRole("complementary", { name: "Sources" });
}

/** The `[n]` marker of an answer's source n (a button named by the source). */
export function marker(scope: Page | Locator, n: number) {
  return scope.getByRole("button", { name: new RegExp(`^\\[${n}\\] `) });
}

/** The signed-in user's thread with this title (its first question), via the BFF. */
export async function threadId(page: Page, title: string): Promise<string> {
  const response = await page.request.get("/api/threads");
  expect(response.status()).toBe(200);
  const threads = (await response.json()) as { thread_id: string; title: string }[];
  const thread = threads.find((t) => t.title === title);
  if (!thread) throw new Error(`No thread titled ${title}`);
  return thread.thread_id;
}

/** WCAG 2.1 A/AA violations axe rates serious or critical on the page as it is now. */
export async function seriousViolations(page: Page) {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    // The app's only frame is a draft letter's preview, which runs no scripts (sandbox=""), so axe can't be injected
    // into it; the frame element itself (its title) is still checked on the page.
    .options({ iframes: false })
    // Without frames there are no frame results to combine in a helper page (which fails beside the sandboxed frame).
    .setLegacyMode(true)
    .analyze();
  return results.violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .map((v) => ({ id: v.id, impact: v.impact, help: v.help, targets: v.nodes.map((n) => n.target.join(" ")) }));
}
