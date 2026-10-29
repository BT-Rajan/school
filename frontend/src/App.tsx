import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Navigate, NavLink, Route, Routes, useLocation } from "react-router-dom";

import { LanguageSwitch } from "./components";
import Account from "./pages/Account";
import Clusters from "./pages/Clusters";
import CustomFields from "./pages/CustomFields";
import Home from "./pages/Home";
import Imports from "./pages/Imports";
import Invitation from "./pages/Invitation";
import Login from "./pages/Login";
import ReferenceLists from "./pages/ReferenceLists";
import ResetPassword from "./pages/ResetPassword";
import Schools from "./pages/Schools";
import Settings from "./pages/Settings";
import Staff from "./pages/Staff";
import Supervisors from "./pages/Supervisors";
import Teachers from "./pages/Teachers";
import { districtName, useSession } from "./session";
import type { Role } from "./types";

const ADMIN: Role[] = ["district_admin"];
const MANAGERS: Role[] = ["district_admin", "cluster_head"];

const NAV: { to: string; key: string; roles?: Role[] }[] = [
  { to: "/", key: "nav.home" },
  { to: "/clusters", key: "nav.clusters", roles: MANAGERS },
  { to: "/schools", key: "nav.schools", roles: MANAGERS },
  { to: "/teachers", key: "nav.teachers", roles: MANAGERS },
  { to: "/supervisors", key: "nav.supervisors", roles: MANAGERS },
  { to: "/staff", key: "nav.staff", roles: ADMIN },
  { to: "/reference", key: "nav.reference", roles: ADMIN },
  { to: "/custom-fields", key: "nav.customFields", roles: ADMIN },
  { to: "/imports", key: "nav.imports", roles: MANAGERS },
  { to: "/settings", key: "nav.settings", roles: ADMIN },
  { to: "/account", key: "nav.account" },
];

function Shell({ children }: { children: ReactNode }) {
  const { t, i18n } = useTranslation();
  const { me, district, signOut } = useSession();
  return (
    <>
      <a className="skip-link" href="#main">
        {t("app.title")}
      </a>
      <header className="topbar">
        <div className="brand">
          {t("app.title")}
          <small>{districtName(district, i18n.language)}</small>
        </div>
        <LanguageSwitch />
        {me && (
          <>
            <span>
              {me.name} · {t(`roles.${me.role}`)}
            </span>
            <button type="button" onClick={() => void signOut()}>
              {t("common.signOut")}
            </button>
          </>
        )}
      </header>
      {me && (
        <nav className="nav" aria-label={t("nav.menu")}>
          {NAV.filter((item) => !item.roles || item.roles.includes(me.role)).map((item) => (
            <NavLink key={item.to} to={item.to} end={item.to === "/"}>
              {t(item.key)}
            </NavLink>
          ))}
        </nav>
      )}
      <main id="main">{children}</main>
    </>
  );
}

function Protected({ roles, children }: { roles?: Role[]; children: ReactNode }) {
  const { me, loading } = useSession();
  const { t } = useTranslation();
  const location = useLocation();
  if (loading) return <p>{t("common.loading")}</p>;
  if (!me) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  if (roles && !roles.includes(me.role)) return <Navigate to="/" replace />;
  return <>{children}</>;
}

export default function App() {
  return (
    <Shell>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/reset-password" element={<ResetPassword />} />
        <Route path="/invite/:token" element={<Invitation />} />
        <Route path="/" element={<Protected><Home /></Protected>} />
        <Route path="/account" element={<Protected><Account /></Protected>} />
        <Route path="/clusters" element={<Protected roles={MANAGERS}><Clusters /></Protected>} />
        <Route path="/schools" element={<Protected roles={MANAGERS}><Schools /></Protected>} />
        <Route path="/teachers" element={<Protected roles={MANAGERS}><Teachers /></Protected>} />
        <Route path="/supervisors" element={<Protected roles={MANAGERS}><Supervisors /></Protected>} />
        <Route path="/imports" element={<Protected roles={MANAGERS}><Imports /></Protected>} />
        <Route path="/staff" element={<Protected roles={ADMIN}><Staff /></Protected>} />
        <Route path="/reference" element={<Protected roles={ADMIN}><ReferenceLists /></Protected>} />
        <Route path="/custom-fields" element={<Protected roles={ADMIN}><CustomFields /></Protected>} />
        <Route path="/settings" element={<Protected roles={ADMIN}><Settings /></Protected>} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Shell>
  );
}
