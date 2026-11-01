import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import {
  Activity,
  BookOpen,
  FileText,
  LogOut,
  PhoneCall,
  Radar,
  ShieldCheck,
  Ticket,
  Volume2,
  VolumeX,
  type LucideIcon,
} from "lucide-react";
import { Suspense } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { qk } from "../api/queryKeys";
import { AlertProvider, useAlerts } from "../alerts/AlertContext";
import { useAuth } from "../auth/AuthContext";
import { LoadingState, ModeBadge } from "../components";
import { EventStreamProvider } from "../stream/EventStreamContext";
import { AlertBanner } from "./AlertBanner";
import { ConnectionPill } from "./ConnectionPill";

interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  end?: boolean;
}

export const NAV_ITEMS: readonly NavItem[] = [
  { to: "/", label: "Live board", icon: Activity, end: true },
  { to: "/tickets", label: "Tickets", icon: Ticket },
  { to: "/calls", label: "Calls", icon: PhoneCall },
  { to: "/gaps", label: "Gaps", icon: Radar },
  { to: "/kb", label: "KB", icon: BookOpen },
  { to: "/rules", label: "Rules", icon: FileText },
];

function MuteToggle() {
  const { muted, toggleMuted } = useAlerts();
  const Icon = muted ? VolumeX : Volume2;
  return (
    <button
      type="button"
      onClick={toggleMuted}
      className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs text-[#E9DDD0] hover:bg-white/10"
      aria-pressed={muted}
      aria-label={muted ? "Unmute P1 alert sound" : "Mute P1 alert sound"}
      title={muted ? "P1 alert sound is muted" : "P1 alert sound is on"}
    >
      <Icon size={16} aria-hidden />
      <span className="hidden xl:inline">{muted ? "Muted" : "Sound on"}</span>
    </button>
  );
}

function Shell() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const health = useQuery({
    queryKey: qk.health,
    queryFn: ({ signal }) => api.healthz(signal),
    refetchInterval: 60_000,
    retry: false,
  });

  return (
    <div className="flex min-h-full flex-col">
      <header className="bg-header text-[#F4EFEA] shadow">
        <div className="mx-auto flex max-w-[1800px] items-center gap-4 px-4 py-2">
          <div className="flex items-center gap-2 font-semibold tracking-wide">
            <ShieldCheck size={20} aria-hidden />
            <span>Resolvix Ops</span>
          </div>
          <nav aria-label="Main" className="flex flex-1 items-center gap-1">
            {NAV_ITEMS.map(({ to, label, icon: Icon, end }) => (
              <NavLink
                key={to}
                to={to}
                end={end}
                className={({ isActive }) =>
                  clsx(
                    "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm transition-colors",
                    isActive ? "bg-white/15 font-medium text-white" : "text-[#E3D6C8] hover:bg-white/10",
                  )
                }
              >
                <Icon size={15} aria-hidden />
                {label}
              </NavLink>
            ))}
          </nav>
          <div className="flex items-center gap-3">
            {health.data ? (
              <span data-testid="header-mode">
                <ModeBadge mode={health.data.notify_mode} />
              </span>
            ) : null}
            <ConnectionPill />
            <MuteToggle />
            <div className="hidden text-right text-xs leading-tight lg:block">
              <div className="font-medium">{user?.email}</div>
              <div className="text-[#CBA982]">
                {user?.role}
                {user?.department ? ` · ${user.department}` : ""}
              </div>
            </div>
            <button
              type="button"
              className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs hover:bg-white/10"
              onClick={async () => {
                await logout();
                navigate("/login", { replace: true });
              }}
              aria-label="Sign out"
            >
              <LogOut size={16} aria-hidden />
              <span className="hidden xl:inline">Sign out</span>
            </button>
          </div>
        </div>
      </header>
      <AlertBanner />
      <main className="mx-auto w-full max-w-[1800px] flex-1 px-4 py-4">
        <Suspense fallback={<LoadingState label="Loading page…" />}>
          <Outlet />
        </Suspense>
      </main>
    </div>
  );
}

/** Authenticated shell: header + navigation + P1 banner, with the SSE connection and alert state mounted once. */
export function AppLayout() {
  return (
    <EventStreamProvider>
      <AlertProvider>
        <Shell />
      </AlertProvider>
    </EventStreamProvider>
  );
}
