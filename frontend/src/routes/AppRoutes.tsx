import { Navigate, Route, Routes } from "react-router-dom";

import { AppShell } from "../layouts/AppShell";
import { DashboardPage } from "../pages/DashboardPage";
import { LoginPage } from "../pages/LoginPage";
import { NotFoundPage } from "../pages/NotFoundPage";
import { PayrollDetailPage } from "../pages/PayrollDetailPage";
import { PayrollListPage } from "../pages/PayrollListPage";
import { ProtectedRoute, PublicOnlyRoute } from "./RouteGuards";

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<PublicOnlyRoute />}>
        <Route path="/login" element={<LoginPage />} />
      </Route>

      <Route element={<ProtectedRoute />}>
        <Route element={<AppShell />}>
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="/payrolls" element={<PayrollListPage />} />
          <Route path="/payrolls/:year/:month" element={<PayrollDetailPage />} />
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
        </Route>
      </Route>

      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
}
