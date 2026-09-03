import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../api/client";
import { DashboardPage } from "../pages/DashboardPage";
import { dashboardData, payrollPeriods } from "./fixtures";

const payrollMocks = vi.hoisted(() => ({
  getPayrollPeriods: vi.fn(),
  getDashboard: vi.fn(),
}));

vi.mock("../api/payroll", () => payrollMocks);

function renderDashboard() {
  return render(
    <MemoryRouter>
      <DashboardPage />
    </MemoryRouter>,
  );
}

describe("dashboard data states", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows a loading state while periods are requested", () => {
    payrollMocks.getPayrollPeriods.mockReturnValue(new Promise(() => undefined));
    renderDashboard();

    expect(screen.getByText("Bordro dönemleri yükleniyor")).toBeInTheDocument();
  });

  it("renders salary, earnings, deductions, attendance, and tax data", async () => {
    payrollMocks.getPayrollPeriods.mockResolvedValue(payrollPeriods);
    payrollMocks.getDashboard.mockResolvedValue(dashboardData);
    renderDashboard();

    expect(await screen.findByText("Güncel net ücret")).toBeInTheDocument();
    expect(screen.getAllByText(/84\.400,00/).length).toBeGreaterThan(0);
    expect(screen.getByText("Temel Maaş")).toBeInTheDocument();
    expect(screen.getByText("SGK İşçi Payı")).toBeInTheDocument();
    expect(screen.getByText("2 gün")).toBeInTheDocument();
    expect(screen.getByText("Vergi Durumu")).toBeInTheDocument();
    expect(screen.getAllByText(/210\.000,00/).length).toBeGreaterThan(0);
  });

  it("shows a safe dashboard failure state", async () => {
    payrollMocks.getPayrollPeriods.mockResolvedValue(payrollPeriods);
    payrollMocks.getDashboard.mockRejectedValue(new ApiError(500));
    renderDashboard();

    expect(await screen.findByRole("alert")).toHaveTextContent("Bilgiler alınamadı");
  });

  it("refetches dashboard data when the selected period changes", async () => {
    const user = userEvent.setup();
    const january = {
      ...dashboardData,
      period: { year: 2026, month: 1 },
      salary: {
        ...dashboardData.salary,
        net: "80000.00",
        previous_net: null,
        net_delta: null,
        net_delta_percent: null,
      },
    };
    payrollMocks.getPayrollPeriods.mockResolvedValue(payrollPeriods);
    payrollMocks.getDashboard.mockImplementation((year: number, month: number) =>
      Promise.resolve(month === 1 ? january : dashboardData),
    );
    renderDashboard();

    await screen.findByText("Güncel net ücret");
    await user.selectOptions(screen.getByRole("combobox", { name: "Dönem" }), "2026-1");

    await waitFor(() => expect(payrollMocks.getDashboard).toHaveBeenCalledWith(2026, 1));
    expect(await screen.findByText(/80\.000,00/)).toBeInTheDocument();
    expect(screen.getByText("İlk kayıtlı dönem")).toBeInTheDocument();
  });
});
