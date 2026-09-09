import { useState } from "react";
import {
  FileText,
  LayoutDashboard,
  LogOut,
  Menu,
  ShieldCheck,
  Upload,
  X,
} from "lucide-react";
import { NavLink, Outlet, useLocation } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";
import { BrandMark } from "../components/BrandMark";
import { roleLabel } from "../utils/formatters";
import type { UserRole } from "../api/types";

const navigation: Array<{
  to: string;
  label: string;
  icon: typeof FileText;
  roles?: readonly UserRole[];
}> = [
  { to: "/dashboard", label: "Genel Bakış", icon: LayoutDashboard },
  { to: "/payrolls", label: "Bordrolarım", icon: FileText },
  {
    to: "/imports",
    label: "Bordro İçe Aktarma",
    icon: Upload,
    roles: ["PAYROLL_ADMIN", "HR_ADMIN", "AUDITOR"],
  },
];

function Navigation({ roles, onNavigate }: { roles: UserRole[]; onNavigate?: () => void }) {
  return (
    <nav className="mt-9 space-y-1.5" aria-label="Ana menü">
      {navigation
        .filter((item) => !item.roles || roles.some((role) => item.roles?.includes(role)))
        .map(({ to, label, icon: Icon }) => (
        <NavLink
          key={to}
          to={to}
          onClick={onNavigate}
          className={({ isActive }) =>
            `flex items-center gap-3 rounded-xl px-3.5 py-3 text-sm font-medium transition-colors ${
              isActive
                ? "bg-white/10 text-white"
                : "text-slate-400 hover:bg-white/5 hover:text-white"
            }`
          }
        >
          {({ isActive }) => (
            <>
              <Icon
                size={19}
                className={isActive ? "text-teal-300" : "text-slate-500"}
                aria-hidden="true"
              />
              {label}
            </>
          )}
        </NavLink>
        ))}
    </nav>
  );
}

function pageTitle(pathname: string): string {
  if (pathname === "/imports/upload") return "Bordro Yükle";
  if (pathname.startsWith("/imports/")) return "Bordro İncele";
  if (pathname === "/imports") return "Bordro İçe Aktarma";
  if (pathname.startsWith("/payrolls/") || pathname.includes("/payrolls/")) return "Bordro Detayı";
  if (pathname === "/payrolls") return "Bordrolarım";
  return "Genel Bakış";
}

export function AppShell() {
  const { user, logout } = useAuth();
  const { pathname } = useLocation();
  const [drawerOpen, setDrawerOpen] = useState(false);

  const primaryRole = user?.roles[0] ?? "EMPLOYEE";

  return (
    <div className="min-h-screen bg-slate-50">
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 flex-col bg-slate-950 px-5 py-6 lg:flex">
        <BrandMark />
        <Navigation roles={user?.roles ?? []} />
        <div className="mt-auto rounded-2xl border border-white/10 bg-white/5 p-4">
          <div className="flex items-center gap-2 text-xs font-medium text-teal-300">
            <ShieldCheck size={15} aria-hidden="true" />
            Güvenli oturum
          </div>
          <p className="mt-2 truncate text-sm font-medium text-white">{user?.email}</p>
          <p className="mt-0.5 text-xs text-slate-500">{roleLabel(primaryRole)}</p>
        </div>
      </aside>

      {drawerOpen && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <button
            type="button"
            aria-label="Menüyü kapat"
            className="absolute inset-0 bg-slate-950/55"
            onClick={() => setDrawerOpen(false)}
          />
          <aside className="relative flex h-full w-72 flex-col bg-slate-950 px-5 py-6 shadow-2xl">
            <div className="flex items-center justify-between">
              <BrandMark />
              <button
                type="button"
                aria-label="Menüyü kapat"
                onClick={() => setDrawerOpen(false)}
                className="rounded-lg p-2 text-slate-400 hover:bg-white/10 hover:text-white"
              >
                <X size={20} />
              </button>
            </div>
            <Navigation roles={user?.roles ?? []} onNavigate={() => setDrawerOpen(false)} />
          </aside>
        </div>
      )}

      <div className="lg:pl-64">
        <header className="sticky top-0 z-20 border-b border-slate-200/80 bg-white/90 backdrop-blur">
          <div className="flex h-17 items-center justify-between px-4 sm:px-6 lg:px-8">
            <div className="flex items-center gap-3">
              <button
                type="button"
                aria-label="Menüyü aç"
                onClick={() => setDrawerOpen(true)}
                className="rounded-xl border border-slate-200 p-2 text-slate-600 lg:hidden"
              >
                <Menu size={20} />
              </button>
              <div>
                <h1 className="text-base font-bold text-slate-900 sm:text-lg">
                  {pageTitle(pathname)}
                </h1>
                <p className="hidden text-xs text-slate-500 sm:block">
                  Bordro ve vergi bilgileriniz
                </p>
              </div>
            </div>

            <div className="flex items-center gap-3">
              <div className="hidden text-right sm:block">
                <p className="max-w-52 truncate text-sm font-semibold text-slate-800">
                  {user?.email}
                </p>
                <p className="text-xs text-slate-500">{roleLabel(primaryRole)}</p>
              </div>
              <button
                type="button"
                onClick={logout}
                className="flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm font-semibold text-slate-600 hover:border-slate-300 hover:bg-slate-50 hover:text-slate-900"
              >
                <LogOut size={17} aria-hidden="true" />
                <span className="hidden sm:inline">Çıkış</span>
              </button>
            </div>
          </div>
        </header>

        <main className="mx-auto max-w-[1500px] px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
