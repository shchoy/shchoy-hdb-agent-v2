"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore, type ReactNode } from "react";
import { roleLabel, type ConversationHit, type Group, type ThreadSummary, type UserCtx } from "@/lib/events";
import type { Theme } from "@/lib/theme";
import { ACTIVE_THREAD, ACTIVE_TURN } from "../runClient";
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
  SearchIcon,
  TasksIcon,
} from "./icons";
import { ConversationItem } from "./ConversationItem";
import { GroupSection, NewGroup } from "./GroupSection";
import { DRAG_TYPE, moveThread, refusalDetail, type DragHandle, type DropZone } from "./menu";
import { SearchDialog } from "./SearchDialog";
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

/** The drop zone key of Recent (group IDs are UUIDs). */
const RECENT = "recent";

type Dragged = { kind: "thread"; thread: ThreadSummary } | { kind: "group"; group: Group };

function current(pathname: string, href: string): boolean {
  return href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`);
}

/**
 * The signed-in app's frame: a left sidebar (product, New conversation, sections, pending-approvals count, the officer's
 * pinned conversations and groups (#102, in pin order; a pinned conversation shows only there), then their other groups
 * and the rest under Recent, theme toggle, persona) beside the screen. Conversations are dragged onto a group or Recent,
 * unpinned groups onto another to reorder them (#101); each has a menu way too. Below a tablet width the sidebar is a drawer behind a Menu button.
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
  /** Likewise for a group just pinned or unpinned (#102). */
  const [movingGroup, setMovingGroup] = useState<string | null>(null);
  const [pending, setPending] = useState(0);
  const [active, setActive] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  /** The search dialog (#107) is open; focus goes back to `searchOpener` when it closes. */
  const [searching, setSearching] = useState(false);
  const searchOpener = useRef<HTMLElement | null>(null);
  /** A conversation opened from search: its sidebar row is scrolled into view once shown. */
  const [revealing, setRevealing] = useState<string | null>(null);
  const [announcement, setAnnouncement] = useState("");
  /** What is being dragged (#101; a browser's drag data can't be read until the drop) and the drop zone it is over. */
  const [dragged, setDragged] = useState<Dragged | null>(null);
  const [over, setOver] = useState<string | null>(null);
  /** A refused drop, shown until the next drag. */
  const [dropError, setDropError] = useState<string | null>(null);
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

  /** Opens a conversation on the Ask screen (at `turn`, else its end): at once if it is shown, else by going there
   * (it reopens the handed-over one). */
  function pick(threadId: string, turn?: number | null) {
    closeDrawer(false);
    if (control.current) return control.current.open(threadId, turn);
    sessionStorage.setItem(ACTIVE_THREAD, threadId);
    if (turn != null) sessionStorage.setItem(ACTIVE_TURN, String(turn));
    else sessionStorage.removeItem(ACTIVE_TURN);
    router.push("/");
  }

  const openSearch = useCallback(() => {
    if (searching) return; // Ctrl/⌘K again: already open, its focus stays put
    // From the phone drawer: it closes, and focus returns to its Menu button.
    const from = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    searchOpener.current = drawer.current?.contains(from) && drawerOpen ? menuButton.current : from;
    if (drawerOpen) closeDrawer(false);
    setSearching(true);
  }, [searching, drawerOpen, closeDrawer]);

  function closeSearch() {
    setSearching(false);
  }

  // Closed (Escape, Close, the backdrop): focus back where it was, once the shell is no longer inert. Not after a
  // result opened: the Ask screen moves focus to the matching turn.
  useEffect(() => {
    if (searching || !searchOpener.current) return;
    const opener = searchOpener.current;
    searchOpener.current = null;
    if (opener.isConnected) opener.focus();
  }, [searching]);

  /** A search result: its conversation opens at the matching turn, shown (group expanded) and current in the sidebar. */
  function found(hit: ConversationHit) {
    setSearching(false);
    if (busy && onAsk) {
      // The open conversation is answering: the sidebar can't switch now (focus goes back to the opener).
      setAnnouncement("Wait for the answer to finish, then open the conversation.");
      return;
    }
    searchOpener.current = null;
    const thread = threads.find((t) => t.thread_id === hit.thread_id);
    const group = thread ? groupOf(thread) : null;
    if (group && thread?.pinned == null) expand(group);
    setRevealing(hit.thread_id);
    pick(hit.thread_id, hit.message_index);
  }

  // Ctrl/⌘K opens the search dialog from anywhere in the app.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && !event.altKey && event.key.toLowerCase() === "k") {
        event.preventDefault();
        openSearch();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [openSearch]);

  useEffect(() => {
    if (!revealing) return;
    const row = drawer.current?.querySelector(`[data-thread-id="${CSS.escape(revealing)}"]`);
    if (!row) return;
    row.scrollIntoView?.({ block: "nearest" });
    setRevealing(null);
  }, [revealing, threads, collapsed]);

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

  function moved(thread: ThreadSummary, groupId: string | null, { focus = true } = {}) {
    setThreads((all) => all.map((t) => (t.thread_id === thread.thread_id ? { ...t, group_id: groupId } : t)));
    const destination = groups.find((g) => g.group_id === groupId);
    // A pinned one stays in Pinned: the move is where unpinning will put it back.
    const stays = thread.pinned != null ? ". It stays pinned." : "";
    setAnnouncement(`Moved ${thread.title} to ${destination?.name ?? "Recent"}${stays}`);
    if (groupId) expand(groupId); // so the moved conversation is shown (and keeps focus, when moved by its menu)
    if (focus) setMoving(thread.thread_id);
    setDropError(null); // an earlier refused drop is no longer news
  }

  function pinned(thread: ThreadSummary, place: number | null) {
    setThreads((all) => all.map((t) => (t.thread_id === thread.thread_id ? { ...t, pinned: place } : t)));
    if (place == null && thread.group_id) expand(thread.group_id); // back in its group: shown, so it keeps focus
    setAnnouncement(`${place == null ? "Unpinned" : "Pinned"} ${thread.title}`);
    setMoving(thread.thread_id);
  }

  function pinnedGroup(group: Group, place: number | null) {
    setGroups((all) => all.map((g) => (g.group_id === group.group_id ? { ...g, pinned: place } : g)));
    setAnnouncement(`${place == null ? "Unpinned" : "Pinned"} group ${group.name}`);
    setMovingGroup(group.group_id);
  }

  /** A conversation dropped on a group (or Recent: null). */
  async function dropThread(thread: ThreadSummary, groupId: string | null) {
    const refusal = await moveThread(thread.thread_id, groupId);
    if (!refusal) return moved(thread, groupId, { focus: false });
    if (refusal.stale) refresh();
    setDropError(refusal.refused);
  }

  /** Puts an unpinned group at `index` among the unpinned groups (pinned ones keep their place in the officer's order,
   * which is theirs again once unpinned); resolves to the refusal, or null once reordered (and announced). */
  async function reorder(group: Group, index: number): Promise<string | null> {
    const shown = unpinnedGroups.map((g) => g.group_id).filter((id) => id !== group.group_id);
    shown.splice(index, 0, group.group_id);
    const next = shown[Symbol.iterator]();
    const order = groups.map((g) => (g.pinned == null ? (next.next().value as string) : g.group_id));
    try {
      const response = await fetch("/api/groups/order", {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ group_ids: order }),
      });
      if (!response.ok) {
        refresh(); // 409: groups were created or deleted elsewhere
        return await refusalDetail(response, "The groups couldn't be reordered.");
      }
      setGroups((await response.json()) as Group[]);
      setDropError(null);
      setAnnouncement(`Moved group ${group.name} to position ${index + 1} of ${shown.length}`);
      return null;
    } catch {
      return "The groups couldn't be reordered. Try again.";
    }
  }

  /** Where the dragged row could be dropped: a group's ID, or RECENT. Dropping it where it already is does nothing. */
  function accepts(zone: string): boolean {
    if (dragged?.kind === "thread") return zone !== (groupOf(dragged.thread) ?? RECENT);
    if (dragged?.kind === "group") return unpinnedGroups.some((g) => g.group_id === zone && g.group_id !== dragged.group.group_id);
    return false;
  }

  function dragHandle(next: Dragged, label: string): DragHandle {
    return {
      onDragStart(event) {
        // Some browsers start a drag only with data set; the shell reads `dragged`, not this.
        event.dataTransfer?.setData(DRAG_TYPE, label);
        if (event.dataTransfer) event.dataTransfer.effectAllowed = "move";
        setDropError(null);
        setDragged(next);
      },
      onDragEnd() {
        setDragged(null);
        setOver(null);
      },
    };
  }

  function dropZone(zone: string): DropZone {
    const allowed = accepts(zone);
    const take = (event: React.DragEvent<HTMLElement>) => {
      if (!allowed) return;
      event.preventDefault(); // allows the drop
      if (event.dataTransfer) event.dataTransfer.dropEffect = "move";
      if (over !== zone) setOver(zone);
    };
    return {
      "data-drop": !allowed ? "none" : over === zone ? "over" : "available",
      onDragEnter: take,
      onDragOver: take,
      onDragLeave(event) {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setOver((o) => (o === zone ? null : o));
      },
      onDrop(event) {
        if (!allowed || !dragged) return;
        event.preventDefault();
        event.stopPropagation(); // a group inside the sidebar: handled once
        setOver(null);
        setDragged(null);
        if (dragged.kind === "thread") void dropThread(dragged.thread, zone === RECENT ? null : zone);
        else {
          const target = unpinnedGroups.findIndex((g) => g.group_id === zone);
          void reorder(dragged.group, target).then((refused) => refused && setDropError(refused));
        }
      },
    };
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
  /** The shortcut's hint: ⌘K on a Mac (read after hydration, so the server's Ctrl K paints first). */
  const mac = useSyncExternalStore(
    () => () => {},
    () => /Mac|iPhone|iPad/.test(navigator.platform),
    () => false,
  );
  const known = new Set(groups.map((g) => g.group_id));
  /** A conversation whose group is unknown here (e.g. deleted in another browser) is shown under Recent. */
  const groupOf = (t: ThreadSummary) => (t.group_id && known.has(t.group_id) ? t.group_id : null);
  const unpinned = threads.filter((t) => t.pinned == null);
  const ungrouped = unpinned.filter((t) => groupOf(t) === null);
  const unpinnedGroups = groups.filter((g) => g.pinned == null);
  /** Pinned conversations and groups together, in pin order. */
  const pins = [
    ...threads.filter((t) => t.pinned != null).map((t) => ({ place: t.pinned!, thread: t })),
    ...groups.filter((g) => g.pinned != null).map((g) => ({ place: g.pinned!, group: g })),
  ].sort((a, b) => a.place - b.place);

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
      onPinned={(place) => pinned(t, place)}
      onDeleted={() => deleted(t)}
      drag={t.pinned == null ? dragHandle({ kind: "thread", thread: t }, t.title) : undefined}
    />
  );

  /** A group and its unpinned conversations; `index` among the unpinned groups (none for a pinned one: no Move up/down). */
  const groupSection = (g: Group, index?: number) => {
    const members = unpinned.filter((t) => groupOf(t) === g.group_id);
    const reorderable = index !== undefined;
    return (
      <GroupSection
        key={g.group_id}
        group={g}
        count={members.length}
        expanded={!collapsed.has(g.group_id)}
        onToggle={() => toggle(g.group_id)}
        onRenamed={(name) => renamedGroup(g.group_id, name)}
        onDeleted={() => deletedGroup(g)}
        onPinned={(place) => pinnedGroup(g, place)}
        focusOptions={movingGroup === g.group_id}
        onFocused={() => setMovingGroup(null)}
        position={reorderable ? { index, total: unpinnedGroups.length } : undefined}
        onMove={reorderable ? (to) => reorder(g, to) : undefined}
        drag={reorderable ? dragHandle({ kind: "group", group: g }, g.name) : undefined}
        drop={dropZone(g.group_id)}
      >
        {members.map(conversationItem)}
      </GroupSection>
    );
  };

  return (
    <ShellProvider value={shell}>
      <div className={styles.shell}>
        <a href="#content" className={styles.skip}>
          Skip to content
        </a>
        <header className={styles.topbar} inert={drawerOpen || searching || undefined}>
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
          inert={searching || undefined}
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

          <button type="button" className={styles.searchBox} onClick={openSearch} aria-keyshortcuts="Control+K Meta+K">
            <SearchIcon />
            <span>Search conversations</span>
            <kbd aria-hidden="true">{mac ? "⌘K" : "Ctrl K"}</kbd>
          </button>

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
            {pins.length > 0 && (
              <div className={styles.pinned}>
                <h2 id="pinned-conversations" className={styles.groupHeading}>
                  Pinned
                </h2>
                <ul aria-labelledby="pinned-conversations" className={styles.groups}>
                  {pins.map((pin) => ("thread" in pin ? conversationItem(pin.thread) : groupSection(pin.group)))}
                </ul>
              </div>
            )}
            <h2 ref={groupsHeading} id="conversation-groups" tabIndex={-1} className={styles.groupHeading}>
              Groups
            </h2>
            {unpinnedGroups.length > 0 && (
              <ul aria-labelledby="conversation-groups" className={styles.groups}>
                {unpinnedGroups.map((g, index) => groupSection(g, index))}
              </ul>
            )}
            <NewGroup onCreated={created} />
            {dropError && (
              <p role="alert" className={styles.rowError}>
                {dropError}
              </p>
            )}
            <div className={styles.recent} {...dropZone(RECENT)}>
              <h2 ref={conversationsHeading} id="recent-conversations" tabIndex={-1} className={styles.groupHeading}>
                Recent conversations
              </h2>
              {threads.length === 0 ? (
                <p className={styles.empty}>No conversations yet.</p>
              ) : ungrouped.length === 0 ? (
                <p className={styles.empty}>
                  {pins.some((p) => "thread" in p) ? "Every conversation is pinned or in a group." : "Every conversation is in a group."}
                </p>
              ) : (
                <ul aria-labelledby="recent-conversations">{ungrouped.map(conversationItem)}</ul>
              )}
            </div>
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

        <main id="content" className={styles.content} tabIndex={-1} inert={drawerOpen || searching || undefined}>
          {children}
        </main>

        {searching && <SearchDialog onClose={closeSearch} onOpen={found} />}
      </div>
    </ShellProvider>
  );
}
