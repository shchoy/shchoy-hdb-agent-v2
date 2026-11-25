"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore, type ReactNode } from "react";
import { roleLabel, type Group, type ThreadSummary, type UserCtx } from "@/lib/events";
import type { Theme } from "@/lib/theme";
import { ACTIVE_THREAD } from "../runClient";
import { collapsedSnapshot, parseCollapsed, saveCollapsed, subscribeCollapsed } from "./collapsedGroups";
import { SignOutButton } from "../SignOutButton";
import {
  ApprovalsIcon,
  AskIcon,
  CloseIcon,
  DocCheckIcon,
  LibraryIcon,
  MemoryIcon,
  MenuIcon,
  PlusIcon,
  TasksIcon,
} from "./icons";
import { ConversationItem } from "./ConversationItem";
import { GroupSection, NewGroup } from "./GroupSection";
import { ShellProvider, type ConversationControl, type Shell } from "./ShellContext";
import styles from "./shell.module.css";
import { ThemeToggle } from "./ThemeToggle";

const SECTIONS = [
  { href: "/", label: "Ask", Icon: AskIcon },
  { href: "/approvals", label: "Approvals", Icon: ApprovalsIcon },
  { href: "/tasks", label: "Tasks", Icon: TasksIcon },
  { href: "/doc-check", label: "Document check", Icon: DocCheckIcon },
  { href: "/library", label: "Library", Icon: LibraryIcon },
  { href: "/memory", label: "Memory", Icon: MemoryIcon },
] as const;

/** Matches shell.module.css: below it the sidebar is a drawer. */
const DRAWER_QUERY = "(max-width: 47.99rem)";

const FOCUSABLE = 'a[href], button:not([disabled]), input, select, textarea, [tabindex]:not([tabindex="-1"])';

function current(pathname: string, href: string): boolean {
  return href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`);
}

/**
 * The signed-in app's frame: a left sidebar (product, New conversation, sections, pending-approvals count, recent
 * conversations in the officer's groups and under Recent, theme toggle, persona) beside the screen. Below a tablet width the sidebar is a drawer behind a Menu button.
 */
export function AppShell({ user, theme, children }: { user: UserCtx; theme?: Theme; children: ReactNode }) {
  const pathname = usePathname() ?? "/";
  const router = useRouter();
  const [threads, setThreads] = useState<ThreadSummary[]>([]);
  const [groups, setGroups] = useState<Group[]>([]);
  const savedCollapsed = useSyncExternalStore(subscribeCollapsed, collapsedSnapshot, () => "[]");
  const collapsed = useMemo(() => parseCollapsed(savedCollapsed), [savedCollapsed]);
  /** A conversation just moved: its Options button in the new place takes focus once, then this clears. */
  const [moving, setMoving] = useState<string | null>(null);
  const [pending, setPending] = useState(0);
  const [active, setActive] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [announcement, setAnnouncement] = useState("");
  const conversationsHeading = useRef<HTMLHeadingElement>(null);
  const groupsHeading = useRef<HTMLHeadingElement>(null);
  const control = useRef<ConversationControl | null>(null);
  const menuButton = useRef<HTMLButtonElement>(null);
  const drawer = useRef<HTMLDivElement>(null);

  const refresh = useCallback(() => {
    void fetch("/api/threads")
      .then(async (r) => r.ok && setThreads((await r.json()) as ThreadSummary[]))
      .catch(() => {});
    void fetch("/api/groups")
      .then(async (r) => r.ok && setGroups((await r.json()) as Group[]))
      .catch(() => {});
    void fetch("/api/approvals")
      .then(async (r) => setPending(r.ok ? ((await r.json()) as unknown[]).length : 0))
      .catch(() => setPending(0));
  }, []);

  const shell = useMemo<Shell>(
    () => ({
      refresh,
      report(id, answering) {
        setActive(id);
        setBusy(answering);
      },
      attach(next) {
        control.current = next;
      },
    }),
    [refresh],
  );

  // Reload on every screen change: a decision elsewhere (or another tab) may have changed the count.
  useEffect(refresh, [refresh, pathname]);

  /** Expanded from now on in this browser (a moved-into or deleted group). */
  function expand(groupId: string) {
    if (!collapsed.has(groupId)) return;
    const next = new Set(collapsed);
    next.delete(groupId);
    saveCollapsed(next);
  }

  function toggle(groupId: string) {
    const next = new Set(collapsed);
    if (!next.delete(groupId)) next.add(groupId);
    saveCollapsed(next);
  }

  const returnFocus = useRef(false);
  const closeDrawer = useCallback((andReturnFocus: boolean) => {
    // Focused once closed (the effect below): until then the Menu button's top bar is inert and can't take focus.
    returnFocus.current = andReturnFocus;
    setDrawerOpen(false);
  }, []);

  // A drawer left open while the window widens would leave the screen inert.
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const narrow = window.matchMedia(DRAWER_QUERY);
    const onChange = () => !narrow.matches && setDrawerOpen(false);
    narrow.addEventListener("change", onChange);
    return () => narrow.removeEventListener("change", onChange);
  }, []);

  useEffect(() => {
    if (drawerOpen) drawer.current?.querySelector<HTMLElement>(FOCUSABLE)?.focus();
    else if (returnFocus.current) {
      returnFocus.current = false;
      menuButton.current?.focus();
    }
  }, [drawerOpen]);

  function onDrawerKey(event: React.KeyboardEvent<HTMLDivElement>) {
    if (!drawerOpen || event.defaultPrevented) return; // e.g. Escape already closed a conversation's menu
    if (event.key === "Escape") {
      event.preventDefault();
      closeDrawer(true);
    } else if (event.key === "Tab") {
      // Keep focus inside the open drawer.
      const items = [...(drawer.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? [])];
      const first = items[0];
      const last = items.at(-1);
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    }
  }

  /** Opens a conversation on the Ask screen: at once if it is shown, else by going there (it reopens the handed-over one). */
  function pick(threadId: string) {
    closeDrawer(false);
    if (control.current) return control.current.open(threadId);
    sessionStorage.setItem(ACTIVE_THREAD, threadId);
    router.push("/");
  }

  function startNew() {
    closeDrawer(false);
    if (control.current) return control.current.startNew();
    sessionStorage.removeItem(ACTIVE_THREAD);
    router.push("/");
  }

  function renamed(threadId: string, title: string) {
    setThreads((all) => all.map((t) => (t.thread_id === threadId ? { ...t, title } : t)));
    setAnnouncement(`Renamed to ${title}`);
  }

  function deleted(thread: ThreadSummary) {
    setThreads((all) => all.filter((t) => t.thread_id !== thread.thread_id));
    setAnnouncement(`Deleted ${thread.title}`);
    conversationsHeading.current?.focus();
    // The deleted conversation can't stay open (or be reopened on the way back to Ask).
    if (sessionStorage.getItem(ACTIVE_THREAD) === thread.thread_id) sessionStorage.removeItem(ACTIVE_THREAD);
    if (thread.thread_id === active) control.current?.startNew();
    refresh();
  }

  function moved(thread: ThreadSummary, groupId: string | null) {
    setThreads((all) => all.map((t) => (t.thread_id === thread.thread_id ? { ...t, group_id: groupId } : t)));
    const destination = groups.find((g) => g.group_id === groupId);
    setAnnouncement(`Moved ${thread.title} to ${destination?.name ?? "Recent"}`);
    if (groupId) expand(groupId); // so the moved conversation is shown, and keeps focus
    setMoving(thread.thread_id);
  }

  function created(group: Group) {
    setGroups((all) => [...all, group]);
    setAnnouncement(`Created group ${group.name}`);
  }

  function renamedGroup(groupId: string, name: string) {
    setGroups((all) => all.map((g) => (g.group_id === groupId ? { ...g, name } : g)));
    setAnnouncement(`Renamed group to ${name}`);
  }

  function deletedGroup(group: Group) {
    setGroups((all) => all.filter((g) => g.group_id !== group.group_id));
    setThreads((all) => all.map((t) => (t.group_id === group.group_id ? { ...t, group_id: null } : t)));
    expand(group.group_id); // forget it
    setAnnouncement(`Deleted group ${group.name}. Its conversations are back in Recent.`);
    groupsHeading.current?.focus();
    refresh();
  }

  const onAsk = pathname === "/";
  const known = new Set(groups.map((g) => g.group_id));
  /** A conversation whose group is unknown here (e.g. deleted in another browser) is shown under Recent. */
  const groupOf = (t: ThreadSummary) => (t.group_id && known.has(t.group_id) ? t.group_id : null);
  const ungrouped = threads.filter((t) => groupOf(t) === null);

  const conversationItem = (t: ThreadSummary) => (
    <ConversationItem
      key={t.thread_id}
      thread={{ ...t, group_id: groupOf(t) }}
      groups={groups}
      disabled={busy && onAsk}
      current={onAsk && t.thread_id === active}
      focusOptions={moving === t.thread_id}
      onFocused={() => setMoving(null)}
      onPick={() => pick(t.thread_id)}
      onRenamed={(title) => renamed(t.thread_id, title)}
      onMoved={(groupId) => moved(t, groupId)}
      onDeleted={() => deleted(t)}
    />
  );

  return (
    <ShellProvider value={shell}>
      <div className={styles.shell}>
        <a href="#content" className={styles.skip}>
          Skip to content
        </a>
        <header className={styles.topbar} inert={drawerOpen || undefined}>
          <button
            ref={menuButton}
            type="button"
            className={styles.iconButton}
            aria-expanded={drawerOpen}
            aria-controls="app-sidebar"
            onClick={() => setDrawerOpen(true)}
          >
            <MenuIcon />
            <span>Menu</span>
          </button>
          <span className={styles.product}>PLG Super-Librarian</span>
        </header>

        {drawerOpen && <div className={styles.backdrop} onClick={() => closeDrawer(true)} aria-hidden="true" />}

        <div
          id="app-sidebar"
          ref={drawer}
          className={styles.sidebar}
          data-open={drawerOpen || undefined}
          onKeyDown={onDrawerKey}
          {...(drawerOpen ? { role: "dialog", "aria-modal": true, "aria-label": "Menu" } : {})}
        >
          <div className={styles.brand}>
            <span className={styles.product}>PLG Super-Librarian</span>
            {drawerOpen && (
              <button type="button" className={styles.iconButton} onClick={() => closeDrawer(true)}>
                <CloseIcon />
                <span className={styles.visuallyHidden}>Close menu</span>
              </button>
            )}
          </div>

          <button type="button" className={styles.newConversation} onClick={startNew} disabled={busy && onAsk}>
            <PlusIcon />
            New conversation
          </button>

          <nav aria-label="Main" className={styles.sections}>
            <ul>
              {SECTIONS.map(({ href, label, Icon }) => (
                <li key={href}>
                  <Link
                    href={href}
                    aria-current={current(pathname, href) ? "page" : undefined}
                    onClick={() => closeDrawer(false)}
                  >
                    <Icon />
                    <span className={styles.sectionLabel}>{label}</span>
                    {href === "/approvals" && pending > 0 && (
                      <>
                        <span className={styles.badge} aria-hidden="true">
                          {pending}
                        </span>
                        <span className={styles.visuallyHidden}>{`, ${pending} pending`}</span>
                      </>
                    )}
                  </Link>
                </li>
              ))}
            </ul>
          </nav>

          <nav aria-label="Conversations" className={styles.conversations}>
            <p role="status" aria-label="Conversation updates" className={styles.visuallyHidden}>
              {announcement}
            </p>
            <h2 ref={groupsHeading} tabIndex={-1} className={styles.groupHeading}>
              Groups
            </h2>
            {groups.length > 0 && (
              <ul className={styles.groups}>
                {groups.map((g) => {
                  const members = threads.filter((t) => groupOf(t) === g.group_id);
                  return (
                    <GroupSection
                      key={g.group_id}
                      group={g}
                      count={members.length}
                      expanded={!collapsed.has(g.group_id)}
                      onToggle={() => toggle(g.group_id)}
                      onRenamed={(name) => renamedGroup(g.group_id, name)}
                      onDeleted={() => deletedGroup(g)}
                    >
                      {members.map(conversationItem)}
                    </GroupSection>
                  );
                })}
              </ul>
            )}
            <NewGroup onCreated={created} />
            <h2 ref={conversationsHeading} id="recent-conversations" tabIndex={-1} className={styles.groupHeading}>
              Recent conversations
            </h2>
            {threads.length === 0 ? (
              <p className={styles.empty}>No conversations yet.</p>
            ) : ungrouped.length === 0 ? (
              <p className={styles.empty}>Every conversation is in a group.</p>
            ) : (
              <ul aria-labelledby="recent-conversations">{ungrouped.map(conversationItem)}</ul>
            )}
          </nav>

          <ThemeToggle theme={theme} />

          <div className={styles.persona}>
            <p>
              Signed in as <strong>{user.name}</strong>
            </p>
            <p className={styles.role}>
              {user.title} · {roleLabel(user.role)}
            </p>
            <SignOutButton />
          </div>
        </div>

        <main id="content" className={styles.content} tabIndex={-1} inert={drawerOpen || undefined}>
          {children}
        </main>
      </div>
    </ShellProvider>
  );
}
