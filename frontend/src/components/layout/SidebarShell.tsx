import React, { useState, useEffect, useCallback } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import {
  LayoutDashboard, FolderKanban, Bot, GitBranch, Terminal,
  FileText, Activity, Key, LogOut, ChevronLeft, Search, X,
  PanelsLeftRight, RadioTower,
} from "lucide-react";
import { cn } from "../../lib/utils";
import { ThemeToggle } from "../ThemeToggle";
import { useFeatureFlags } from "../../hooks/useFeatureFlags";

const BASE_NAV_ITEMS = [
  { to: "/dashboard", icon: LayoutDashboard, label: "Dashboard" },
  { to: "/projects", icon: FolderKanban, label: "Projects" },
  { to: "/agents", icon: Bot, label: "Agents" },
  { to: "/workflows", icon: GitBranch, label: "Workflows" },
  { to: "/sessions", icon: Terminal, label: "Sessions" },
  { to: "/reports", icon: FileText, label: "Reports" },
  { to: "/health", icon: Activity, label: "Health" },
];

// v4.0 P3-main — flag-gated entry to the new /flow shell. Prepended to the
// nav list so it sits at the top once `osa_flow_ui_enabled=true`.
const FLOW_NAV_ITEM = { to: "/flow", icon: PanelsLeftRight, label: "Flow Console" };

const CREDENTIALS_NAV_ITEM = { to: "/credentials", icon: Key, label: "Credentials" };

// Coordinator is session-scoped. Extract the active session id from any
// session-shaped route (/pentest-sessions/:id, /flow/:id,
// /sessions/:id/{monitor,dashboard}, /coordinator/:id). Requires a uuid-ish
// segment so literals like /pentest-sessions/new never match.
const SESSION_ID_RE =
  /\/(?:pentest-sessions|flow|coordinator)\/([0-9a-fA-F-]{8,})|\/sessions\/([0-9a-fA-F-]{8,})\//;

interface Props {
  children: React.ReactNode;
}

export function SidebarShell({ children }: Props) {
  const location = useLocation();
  const navigate = useNavigate();
  const [collapsed, setCollapsed] = useState(false);
  const [palette, setPalette] = useState(false);
  const [query, setQuery] = useState("");
  const flags = useFeatureFlags();

  // Coordinator nav only appears when viewing a specific session, and links
  // to that session's coordinator page (gap #5 fix — the old static item
  // pointed at /sessions and could never reach /coordinator/:sessionId).
  const sessionMatch = location.pathname.match(SESSION_ID_RE);
  const activeSessionId = sessionMatch?.[1] ?? sessionMatch?.[2];
  const coordinatorItem = activeSessionId
    ? { to: `/coordinator/${activeSessionId}`, icon: RadioTower, label: "Coordinator" }
    : null;

  // Dynamic nav list — prepend Flow Console when v4.0 flag is ON; append
  // Credentials when osa_multi_provider_llm is ON; append Coordinator when
  // the flag is ON AND a session is in scope.
  const NAV_ITEMS = [
    ...(flags?.osa_flow_ui_enabled ? [FLOW_NAV_ITEM] : []),
    ...BASE_NAV_ITEMS,
    ...(flags?.osa_multi_provider_llm ? [CREDENTIALS_NAV_ITEM] : []),
    ...(flags?.osa_coordinator_enabled && coordinatorItem ? [coordinatorItem] : []),
  ];

  const handleKeyDown = useCallback((e: KeyboardEvent) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "k") {
      e.preventDefault();
      setPalette(p => !p);
    }
    if (e.key === "Escape") setPalette(false);
  }, []);

  useEffect(() => {
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [handleKeyDown]);

  const filtered = NAV_ITEMS.filter(i =>
    i.label.toLowerCase().includes(query.toLowerCase())
  );

  const handleLogout = () => {
    localStorage.removeItem("token");
    navigate("/login");
  };

  return (
    <div className="flex min-h-screen bg-background">
      {/* Sidebar */}
      <aside className={cn(
        "flex flex-col border-r border-border bg-card transition-all duration-200",
        collapsed ? "w-16" : "w-56"
      )}>
        {/* Logo */}
        <div className="flex items-center gap-3 px-4 py-5 border-b border-border">
          <div className="w-8 h-8 rounded-lg bg-background border border-border flex items-center justify-center flex-shrink-0 shadow-[0_0_18px_rgba(239,68,68,0.18)]">
            <img src="/favicon.svg" alt="OSA" className="w-5 h-5" />
          </div>
          {!collapsed && (
            <span className="font-bold text-sm tracking-tight text-foreground">OSA Platform</span>
          )}
        </div>

        {/* Nav */}
        <nav className="flex-1 px-2 py-4 space-y-0.5 overflow-y-auto">
          {NAV_ITEMS.map(({ to, icon: Icon, label }) => {
            const active = location.pathname.startsWith(to);
            return (
              <Link
                key={to}
                to={to}
                className={cn(
                  "flex items-center gap-3 px-3 py-2.5 rounded-md text-sm font-medium transition-colors",
                  active
                    ? "bg-primary/10 text-primary"
                    : "text-muted-foreground hover:bg-accent hover:text-foreground"
                )}
              >
                <Icon className="w-4 h-4 flex-shrink-0" />
                {!collapsed && <span>{label}</span>}
              </Link>
            );
          })}
        </nav>

        {/* Bottom controls */}
        <div className="px-2 py-4 border-t border-border space-y-0.5">
          {!collapsed && (
            <button
              onClick={() => setPalette(true)}
              className="w-full flex items-center gap-3 px-3 py-2.5 rounded-md text-sm text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
            >
              <Search className="w-4 h-4 flex-shrink-0" />
              <span className="flex-1 text-left">Search</span>
              <kbd className="text-xs bg-muted px-1.5 py-0.5 rounded">⌘K</kbd>
            </button>
          )}
          <button
            onClick={() => setCollapsed(c => !c)}
            className="w-full flex items-center gap-3 px-3 py-2.5 rounded-md text-sm text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
          >
            <ChevronLeft className={cn("w-4 h-4 flex-shrink-0 transition-transform", collapsed && "rotate-180")} />
            {!collapsed && <span>Collapse</span>}
          </button>
          <ThemeToggle collapsed={collapsed} />
          <button
            onClick={handleLogout}
            className="w-full flex items-center gap-3 px-3 py-2.5 rounded-md text-sm text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
          >
            <LogOut className="w-4 h-4 flex-shrink-0" />
            {!collapsed && <span>Logout</span>}
          </button>
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 overflow-auto">
        {children}
      </main>

      {/* Command Palette */}
      {palette && (
        <div
          className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-start justify-center pt-24"
          onClick={() => setPalette(false)}
        >
          <div
            className="w-full max-w-lg bg-card border border-border rounded-xl shadow-2xl overflow-hidden"
            onClick={e => e.stopPropagation()}
          >
            <div className="flex items-center gap-3 px-4 py-3 border-b border-border">
              <Search className="w-4 h-4 text-muted-foreground" />
              <input
                autoFocus
                value={query}
                onChange={e => setQuery(e.target.value)}
                placeholder="Navigate to..."
                className="flex-1 bg-transparent text-sm text-foreground placeholder:text-muted-foreground focus:outline-none"
              />
              <button onClick={() => setPalette(false)}>
                <X className="w-4 h-4 text-muted-foreground" />
              </button>
            </div>
            <div className="py-2 max-h-72 overflow-y-auto">
              {filtered.map(({ to, icon: Icon, label }) => (
                <button
                  key={to}
                  onClick={() => { navigate(to); setPalette(false); setQuery(""); }}
                  className="w-full flex items-center gap-3 px-4 py-2.5 text-sm text-foreground hover:bg-accent transition-colors"
                >
                  <Icon className="w-4 h-4 text-muted-foreground" />
                  {label}
                </button>
              ))}
              {filtered.length === 0 && (
                <p className="px-4 py-6 text-center text-sm text-muted-foreground">No results</p>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
