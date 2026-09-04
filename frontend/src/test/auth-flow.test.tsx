import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AuthProvider } from "../auth/AuthContext";
import { AppRoutes } from "../routes/AppRoutes";
import { currentUser } from "./fixtures";

const authMocks = vi.hoisted(() => ({
  restoreSession: vi.fn(),
  login: vi.fn(),
  logout: vi.fn(),
}));

const payrollMocks = vi.hoisted(() => ({
  getPayrollPeriods: vi.fn(),
  getDashboard: vi.fn(),
  getPayrollDetail: vi.fn(),
  getPayrollComparison: vi.fn(),
  getTaxStatus: vi.fn(),
}));

vi.mock("../api/auth", () => authMocks);
vi.mock("../api/payroll", () => payrollMocks);

function renderApplication(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <AppRoutes />
      </AuthProvider>
    </MemoryRouter>,
  );
}

describe("authentication routes", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    authMocks.restoreSession.mockRejectedValue(new Error("No session"));
    payrollMocks.getPayrollPeriods.mockResolvedValue({
      employee_id: currentUser.employee_id,
      count: 0,
      periods: [],
    });
  });

  it("redirects an unauthenticated protected route to login", async () => {
    renderApplication("/dashboard");

    expect(await screen.findByRole("heading", { name: "Hesabınıza giriş yapın" })).toBeInTheDocument();
  });

  it("restores a cookie-backed session on page reload", async () => {
    authMocks.restoreSession.mockResolvedValue(currentUser);
    renderApplication("/dashboard");

    expect(await screen.findByText("Henüz bordro yok")).toBeInTheDocument();
    expect(authMocks.restoreSession).toHaveBeenCalledOnce();
  });

  it("submits login credentials and opens the dashboard", async () => {
    const user = userEvent.setup();
    authMocks.login.mockResolvedValue(currentUser);
    renderApplication("/login");

    await user.type(await screen.findByLabelText("E-posta"), "employee@demo.local");
    await user.type(screen.getByLabelText("Şifre"), "demo-password");
    await user.click(screen.getByRole("button", { name: "Giriş yap" }));

    await waitFor(() => {
      expect(authMocks.login).toHaveBeenCalledWith(
        "employee@demo.local",
        "demo-password",
      );
    });
    expect(await screen.findByText("Henüz bordro yok")).toBeInTheDocument();
  });

  it("shows a safe message when login fails", async () => {
    const user = userEvent.setup();
    authMocks.login.mockRejectedValue(new Error("backend details"));
    renderApplication("/login");

    await user.type(await screen.findByLabelText("E-posta"), "employee@demo.local");
    await user.type(screen.getByLabelText("Şifre"), "wrong-password");
    await user.click(screen.getByRole("button", { name: "Giriş yap" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "E-posta veya şifre hatalı",
    );
    expect(screen.queryByText("backend details")).not.toBeInTheDocument();
  });

  it("logs out and returns to login", async () => {
    const user = userEvent.setup();
    authMocks.restoreSession.mockResolvedValue(currentUser);
    renderApplication("/dashboard");

    const logoutButton = await screen.findByRole("button", { name: /Çıkış/ });
    await user.click(logoutButton);

    expect(authMocks.logout).toHaveBeenCalledOnce();
    expect(await screen.findByRole("heading", { name: "Hesabınıza giriş yapın" })).toBeInTheDocument();
  });
});
