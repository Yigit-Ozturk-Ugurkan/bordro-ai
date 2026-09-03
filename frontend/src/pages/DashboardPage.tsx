import { useCallback, useEffect, useState } from "react";
import {
  ArrowDownRight,
  ArrowRight,
  ArrowUpRight,
  Banknote,
  CalendarCheck,
  CalendarX,
  CircleDollarSign,
  ReceiptText,
} from "lucide-react";

import { getDashboard, getPayrollPeriods } from "../api/payroll";
import type { DashboardData, PayrollPeriod } from "../api/types";
import { BreakdownTable } from "../components/BreakdownTable";
import { EmptyState, ErrorState, PageLoader } from "../components/AsyncState";
import { MetricCard } from "../components/MetricCard";
import { PeriodSelect } from "../components/PeriodSelect";
import { TaxPanel } from "../features/tax/TaxPanel";
import { friendlyError, type FriendlyError } from "../utils/errors";
import {
  decimalSign,
  formatDays,
  formatMoney,
  formatPercentage,
  formatPeriod,
  formatRate,
} from "../utils/formatters";

function SalaryDelta({ data }: { data: DashboardData }) {
  const sign = decimalSign(data.salary.net_delta);
  const Icon = sign > 0 ? ArrowUpRight : sign < 0 ? ArrowDownRight : ArrowRight;
  const tone = sign > 0 ? "text-teal-300" : sign < 0 ? "text-rose-300" : "text-slate-300";

  if (data.salary.net_delta == null) {
    return <span className="text-sm font-medium text-slate-400">İlk kayıtlı dönem</span>;
  }

  return (
    <span className={`inline-flex items-center gap-1.5 text-sm font-bold ${tone}`}>
      <Icon size={17} aria-hidden="true" />
      {formatMoney(data.salary.net_delta)}
      {data.salary.net_delta_percent != null && (
        <span className="font-semibold">· {formatPercentage(data.salary.net_delta_percent)}</span>
      )}
    </span>
  );
}

export function DashboardPage() {
  const [periods, setPeriods] = useState<PayrollPeriod[] | null>(null);
  const [selectedPeriod, setSelectedPeriod] = useState("");
  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  const [periodError, setPeriodError] = useState<FriendlyError | null>(null);
  const [dashboardError, setDashboardError] = useState<FriendlyError | null>(null);
  const [dashboardLoading, setDashboardLoading] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  const loadPeriods = useCallback(async () => {
    setPeriodError(null);
    setPeriods(null);
    try {
      const result = await getPayrollPeriods();
      setPeriods(result.periods);
      if (result.periods.length) {
        setSelectedPeriod(`${result.periods[0].year}-${result.periods[0].month}`);
      }
    } catch (error) {
      setPeriodError(friendlyError(error));
    }
  }, []);

  useEffect(() => {
    void loadPeriods();
  }, [loadPeriods]);

  useEffect(() => {
    if (!selectedPeriod) return;
    let active = true;
    const [year, month] = selectedPeriod.split("-").map(Number);
    setDashboardLoading(true);
    setDashboardError(null);
    setDashboard(null);

    getDashboard(year, month)
      .then((result) => {
        if (active) setDashboard(result);
      })
      .catch((error) => {
        if (active) setDashboardError(friendlyError(error));
      })
      .finally(() => {
        if (active) setDashboardLoading(false);
      });

    return () => {
      active = false;
    };
  }, [selectedPeriod, reloadKey]);

  if (periods === null && !periodError) return <PageLoader label="Bordro dönemleri yükleniyor" />;
  if (periodError) return <ErrorState {...periodError} onRetry={() => void loadPeriods()} />;
  if (!periods?.length) {
    return <EmptyState title="Henüz bordro yok" message="Görüntülenebilecek bir bordro dönemi bulunmuyor." />;
  }

  const [selectedYear, selectedMonth] = selectedPeriod.split("-").map(Number);

  return (
    <div className="space-y-6">
      <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
        <div>
          <p className="text-sm font-semibold text-teal-700">Finansal özetiniz</p>
          <h2 className="mt-1 text-2xl font-bold tracking-tight text-slate-950">
            {selectedPeriod ? formatPeriod(selectedYear, selectedMonth) : "Bordro özeti"}
          </h2>
          <p className="mt-1 text-sm text-slate-500">Tutarlar bordro kayıtlarınızdan doğrudan alınır.</p>
        </div>
        <PeriodSelect periods={periods} value={selectedPeriod} onChange={setSelectedPeriod} />
      </div>

      {dashboardLoading && <PageLoader label="Dönem özeti yükleniyor" />}
      {dashboardError && (
        <ErrorState {...dashboardError} onRetry={() => setReloadKey((key) => key + 1)} />
      )}

      {dashboard && (
        <>
          <section className="overflow-hidden rounded-3xl bg-slate-950 text-white shadow-[0_18px_45px_rgba(15,23,42,0.12)]">
            <div className="grid lg:grid-cols-[1.45fr_1fr_1fr]">
              <div className="border-b border-white/10 p-6 sm:p-8 lg:border-b-0 lg:border-r">
                <p className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-400">Güncel net ücret</p>
                <p className="mt-4 text-4xl font-bold tracking-tight tabular-nums sm:text-5xl">
                  {formatMoney(dashboard.salary.net)}
                </p>
                <p className="mt-4 text-xs text-slate-500">Hesabınıza geçen bordro net tutarı</p>
              </div>
              <div className="border-b border-white/10 p-6 lg:border-b-0 lg:border-r lg:p-8">
                <p className="text-xs font-semibold uppercase tracking-[0.12em] text-slate-500">Önceki ay</p>
                <p className="mt-4 text-2xl font-bold tabular-nums text-slate-100">
                  {formatMoney(dashboard.salary.previous_net)}
                </p>
                <p className="mt-3 text-xs text-slate-500">Önceki dönem net ücreti</p>
              </div>
              <div className="p-6 lg:p-8">
                <p className="text-xs font-semibold uppercase tracking-[0.12em] text-slate-500">Aylık fark</p>
                <div className="mt-4"><SalaryDelta data={dashboard} /></div>
                <p className="mt-3 text-xs text-slate-500">Önceki döneme göre değişim</p>
              </div>
            </div>
          </section>

          <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
            <MetricCard label="Brüt / Kazanç" value={formatMoney(dashboard.salary.gross)} icon={CircleDollarSign} tone="teal" />
            <MetricCard label="Toplam Kesinti" value={formatMoney(dashboard.deductions.total)} icon={ReceiptText} tone="rose" />
            <MetricCard label="Ücretli Gün" value={formatDays(dashboard.attendance.paid_days)} icon={CalendarCheck} />
            <MetricCard label="Eksik Gün" value={formatDays(dashboard.attendance.missing_days)} icon={CalendarX} tone="amber" />
            <MetricCard label="Vergi Dilimi" value={formatRate(dashboard.tax.current_bracket_rate)} icon={Banknote} />
          </section>

          <div className="grid gap-6 xl:grid-cols-2">
            <BreakdownTable
              title="Kazanç Dağılımı"
              subtitle="Bu dönemdeki brüt kazanç kalemleri"
              items={dashboard.earnings.items}
              total={dashboard.earnings.total}
              totalTone="teal"
            />
            <BreakdownTable
              title="Kesinti Dağılımı"
              subtitle="Bu dönemdeki yasal ve diğer kesintiler"
              items={dashboard.deductions.items}
              total={dashboard.deductions.total}
              totalTone="rose"
            />
          </div>

          <TaxPanel
            currentBracket={dashboard.tax.current_bracket}
            nextBracket={dashboard.tax.next_bracket}
            cumulativeBase={dashboard.tax.cumulative_tax_base}
            distanceToNext={dashboard.tax.distance_to_next_bracket}
            monthlyBase={dashboard.tax.monthly_taxable_base}
          />
        </>
      )}
    </div>
  );
}
