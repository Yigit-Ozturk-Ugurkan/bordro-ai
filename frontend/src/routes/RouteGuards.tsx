import { Navigate, Outlet, useLocation } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";
import type { UserRole } from "../api/types";
import { ErrorState, PageLoader } from "../components/AsyncState";

export function ProtectedRoute() {
  const { user, loading } = useAuth();
  const location = useLocation();

  if (loading) return <PageLoader label="Oturum doğrulanıyor" />;
  if (!user) return <Navigate to="/login" replace state={{ from: location }} />;
  return <Outlet />;
}

export function PublicOnlyRoute() {
  const { user, loading } = useAuth();
  if (loading) return <PageLoader label="Oturum doğrulanıyor" />;
  if (user) return <Navigate to="/dashboard" replace />;
  return <Outlet />;
}

export function RoleRoute({ allowed }: { allowed: readonly UserRole[] }) {
  const { user, loading } = useAuth();
  if (loading) return <PageLoader label="Yetkiler doğrulanıyor" />;
  if (!user) return <Navigate to="/login" replace />;
  if (!user.roles.some((role) => allowed.includes(role))) {
    return (
      <ErrorState
        title="Erişim izniniz yok"
        message="Bordro içe aktarma alanını görüntüleme yetkiniz bulunmuyor."
      />
    );
  }
  return <Outlet />;
}
