import { Navigate, Outlet, useLocation } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";
import { PageLoader } from "../components/AsyncState";

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
