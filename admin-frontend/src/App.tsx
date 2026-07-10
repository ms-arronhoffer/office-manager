import { useEffect, useMemo, useState } from "react"
import {
  BrowserRouter,
  Link,
  Navigate,
  Outlet,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from "react-router-dom"

import { getConsoleMe } from "./api"
import { useAuth } from "./context/AuthContext"
import type { ConsoleMe, ConsoleRole } from "./types"
import AuditPage from "./pages/AuditPage"
import BillingPage from "./pages/BillingPage"
import DashboardPage from "./pages/DashboardPage"
import DunningPage from "./pages/DunningPage"
import LoginPage from "./pages/LoginPage"
import OrgDetailPage from "./pages/OrgDetailPage"
import OrgsPage from "./pages/OrgsPage"
import SupportRequestsPage from "./pages/SupportRequestsPage"
import UsagePage from "./pages/UsagePage"
import UsersPage from "./pages/UsersPage"

const roleRank: Record<ConsoleRole, number> = {
  support: 1,
  finance: 1,
  super_admin: 2,
}

function hasAnyRole(role: ConsoleRole | null | undefined, allowed: ConsoleRole[]) {
  return !!role && allowed.includes(role)
}

function RequireAdminConsole() {
  const { payload } = useAuth()
  const location = useLocation()
  if (!payload) return <Navigate to="/login" state={{ from: location }} replace />
  if (!payload.console_role) return <Navigate to="/login" replace />
  return <Outlet />
}

function RequireConsoleRole({ allowed }: { allowed: ConsoleRole[] }) {
  const { payload } = useAuth()
  if (!hasAnyRole(payload?.console_role, allowed)) return <Navigate to="/" replace />
  return <Outlet />
}

function Shell() {
  const { logout, payload } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [me, setMe] = useState<ConsoleMe | null>(null)

  useEffect(() => {
    getConsoleMe().then(setMe).catch(() => undefined)
  }, [])

  const consoleRole = payload?.console_role ?? me?.console_role ?? null
  const navItems = useMemo(() => {
    const items = [
      { text: "Dashboard", href: "/", roles: ["super_admin", "support", "finance"] as ConsoleRole[] },
      { text: "Organizations", href: "/orgs", roles: ["super_admin", "support", "finance"] as ConsoleRole[] },
      { text: "Usage", href: "/usage", roles: ["super_admin", "support"] as ConsoleRole[] },
      { text: "Billing", href: "/billing", roles: ["super_admin", "finance"] as ConsoleRole[] },
      { text: "Dunning", href: "/dunning", roles: ["super_admin", "finance"] as ConsoleRole[] },
      { text: "Users", href: "/users", roles: ["super_admin"] as ConsoleRole[] },
      { text: "Audit Log", href: "/audit", roles: ["super_admin", "support"] as ConsoleRole[] },
      { text: "Support", href: "/support-requests", roles: ["super_admin", "support"] as ConsoleRole[] },
    ]
    return items.filter((item) => hasAnyRole(consoleRole, item.roles))
  }, [consoleRole])

  return (
    <div className="flex h-screen bg-slate-50">
      <div className="w-72 bg-slate-950 text-white shadow-lg flex flex-col">
        <div className="p-6 border-b border-slate-800">
          <h1 className="text-2xl font-serif font-semibold tracking-tight">Portfolio Desk</h1>
          <p className="mt-1 text-sm text-slate-400">Admin console</p>
          {me && (
            <div className="mt-4 rounded-md border border-slate-800 bg-slate-900/70 p-3 text-xs text-slate-300">
              <p className="font-medium text-slate-100">{me.display_name}</p>
              <p className="capitalize text-[11px] tracking-[0.16em] text-amber-300/80">
                {me.console_role.replace("_", " ")}
              </p>
            </div>
          )}
        </div>
        <nav className="flex-1 p-4 space-y-1">
          {navItems.map((item) => {
            const active = location.pathname === item.href || (item.href !== "/" && location.pathname.startsWith(item.href))
            return (
              <Link
                key={item.href}
                to={item.href}
                className={`block rounded-md px-4 py-2.5 text-sm font-medium transition-colors ${
                  active
                    ? "bg-slate-800 text-white shadow-[inset_0_-2px_0_hsl(var(--accent))]"
                    : "text-slate-300 hover:bg-slate-900 hover:text-white"
                }`}
              >
                {item.text}
              </Link>
            )
          })}
        </nav>
        <div className="p-4 border-t border-slate-800">
          <button
            onClick={() => {
              logout()
              navigate("/login")
            }}
            className="w-full rounded-md px-4 py-2 text-left text-sm font-medium text-slate-300 transition-colors hover:bg-slate-900 hover:text-white"
          >
            Sign Out
          </button>
        </div>
      </div>
      <div className="flex-1 overflow-auto">
        <Outlet />
      </div>
    </div>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route element={<RequireAdminConsole />}>
          <Route element={<Shell />}>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/orgs" element={<OrgsPage />} />
            <Route path="/orgs/:orgId" element={<OrgDetailPage />} />
            <Route element={<RequireConsoleRole allowed={["super_admin", "support"]} />}>
              <Route path="/usage" element={<UsagePage />} />
              <Route path="/audit" element={<AuditPage />} />
              <Route path="/support-requests" element={<SupportRequestsPage />} />
            </Route>
            <Route element={<RequireConsoleRole allowed={["super_admin", "finance"]} />}>
              <Route path="/billing" element={<BillingPage />} />
              <Route path="/dunning" element={<DunningPage />} />
            </Route>
            <Route element={<RequireConsoleRole allowed={["super_admin"]} />}>
              <Route path="/users" element={<UsersPage />} />
            </Route>
          </Route>
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
