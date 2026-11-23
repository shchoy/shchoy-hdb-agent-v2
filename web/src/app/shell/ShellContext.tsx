"use client";

import { createContext, useContext, useEffect, useRef } from "react";

/** What the Ask screen lets the sidebar do with its conversation, while it is shown. */
export type ConversationControl = { open(threadId: string): void; startNew(): void };

/** What the screens tell the app shell's sidebar. Stable: the shell provides one object for its lifetime. */
export type Shell = {
  /** Reloads what the sidebar shows (conversations, pending-approvals count): after a run or a decision. */
  refresh(): void;
  /** The Ask screen's open conversation and whether it is answering (the sidebar can't switch meanwhile). */
  report(active: string | null, busy: boolean): void;
  attach(control: ConversationControl | null): void;
};

/** Outside the shell (a screen rendered on its own) the sidebar's half does nothing. */
const ShellContext = createContext<Shell>({ refresh() {}, report() {}, attach() {} });

export const ShellProvider = ShellContext.Provider;

export function useShell(): Shell {
  return useContext(ShellContext);
}

/**
 * Hands the sidebar the Ask screen's conversation controls while the screen is mounted. `control` may change on
 * every render; the sidebar always calls the latest.
 */
export function useConversationControl(control: ConversationControl, active: string | null, busy: boolean): void {
  const shell = useShell();
  const latest = useRef(control);
  useEffect(() => {
    latest.current = control;
  });
  useEffect(() => {
    shell.attach({
      open: (id) => latest.current.open(id),
      startNew: () => latest.current.startNew(),
    });
    return () => shell.attach(null);
  }, [shell]);
  useEffect(() => {
    shell.report(active, busy);
  }, [shell, active, busy]);
  useEffect(() => () => shell.report(null, false), [shell]);
}
