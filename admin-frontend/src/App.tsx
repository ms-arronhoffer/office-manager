import {
  BrowserRouter,
  Navigate,
  Outlet,
  Route,
  Routes,
  useLocation,
  Link,
} from "react-router-dom";
import { useNavigate } from "react-router-dom";

import { useAuth } from "./context/AuthContext";
import LoginPage from "./pages/LoginPage";
import DashboardPage from "./pages/DashboardPage";
import OrgsPage from "./pages/OrgsPage";
import OrgDetailPage from "./pages/OrgDetailPage";
import BillingPage from "./pages/BillingPage";
import UsersPage from "./pages/UsersPage";
import AuditPage from "./pages/AuditPage";
import UsagePage from "./pages/UsagePage";

// ── Auth Guard ────────────────────────────────────────────────────────────────

function RequireSuperAdmin() {
  const { payload } = useAuth();
  const location = useLocation();
  if (!payload) return <Navigate to="/login" state={{ from: location }} replace />;
  if (!payload.is_super_admin) return <Navigate to="/login" replace />;
  return <Outlet />;
}

// ── Shell ─────────────────────────────────────────────────────────────────────

function Shell() {
  const { logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const navItems = [
    { text: "Dashboard", href: "/" },
    { text: "Organizations", href: "/orgs" },
    { text: "Usage", href: "/usage" },
    { text: "Billing", href: "/billing" },
    { text: "Users", href: "/users" },
    { text: "Audit Log", href: "/audit" },
  ];

  return (
    <div className="flex h-screen bg-slate-50">
      {/* Sidebar */}
      <div className="w-64 bg-slate-900 text-white shadow-lg flex flex-col">
        <div className="p-6 border-b border-slate-800">
          <h1 className="text-xl font-bold">Portfolio Desk</h1>
          <p className="text-sm text-slate-400">Admin Portal</p>
        </div>
        <nav className="flex-1 p-4 space-y-1">
          {navItems.map((item) => (
            <Link
              key={item.href}
              to={item.href}
              className={`block px-4 py-2 rounded-md text-sm font-medium transition-colors ${
                location.pathname === item.href
                  ? "bg-slate-700 text-white"
                  : "text-slate-300 hover:bg-slate-800 hover:text-white"
              }`}
            >
              {item.text}
            </Link>
          ))}
        </nav>
        <div className="p-4 border-t border-slate-800">
          <button
            onClick={() => {
              logout();
              navigate("/login");
            }}
            className="w-full px-4 py-2 rounded-md text-sm font-medium text-slate-300 hover:bg-slate-800 hover:text-white transition-colors text-left"
          >
            Sign Out
          </button>
        </div>
      </div>

      {/* Main content */}
      <div className="flex-1 overflow-auto">
        <Outlet />
      </div>
    </div>
  );
}

// ── App ───────────────────────────────────────────────────────────────────────

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route element={<RequireSuperAdmin />}>
          <Route element={<Shell />}>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/orgs" element={<OrgsPage />} />
            <Route path="/orgs/:orgId" element={<OrgDetailPage />} />
            <Route path="/usage" element={<UsagePage />} />
            <Route path="/billing" element={<BillingPage />} />
            <Route path="/users" element={<UsersPage />} />
            <Route path="/audit" element={<AuditPage />} />
          </Route>
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
