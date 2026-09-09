import { ArrowLeft, Banknote, CalendarCheck, CalendarX, CircleDollarSign, ReceiptText } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { ApiError } from "../api/client";
import {
  getDashboard,
  getEmployeeDashboard,
  getEmployeePayrollComparison,
  getEmployeePayrollDetail,
  getEmployeeTaxStatus,
  getPayrollComparison,
  getPayrollDetail,
  getTaxStatus,
} from "../api/payroll";
import type { DashboardData, PayrollComparison, PayrollDetail, TaxStatus } from "../api/types";
import { BreakdownTable } from "../components/BreakdownTable";
import { ErrorState, PageLoader } from "../components/AsyncState";
import { MetricCard } from "../components/MetricCard";
import { ComparisonPanel } from "../features/payroll/ComparisonPanel";
import { TaxPanel } from "../features/tax/TaxPanel";
import { friendlyError, type FriendlyError } from "../utils/errors";
import { formatDays, formatMoney, formatPeriod } from "../utils/formatters";

interface DetailState {
  detail: PayrollDetail;
  tax: TaxStatus;
  comparison: PayrollComparison | null;
  dashboard: DashboardData;
}

export function PayrollDetailPage() {
  const params = useParams();
  const year = Number(params.year);
  const month = Number(params.month);
  const employeeId = params.employeeId;
  const validPeriod = Number.isInteger(year) && Number.isInteger(month) && month >= 1 && month <= 12;
  const [data, setData] = useState<DetailState | null>(null);
  const [error, setError] = useState<FriendlyError | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    if (!validPeriod) {
      setError({ title: "Geçersiz dönem", message: "Bordro dönemi doğru biçimde belirtilmedi." });
      setLoading(false);
      return;
    }

    setLoading(true);
    setError(null);
    setData(null);
    try {
      const detailRequest = employeeId
        ? getEmployeePayrollDetail(employeeId, year, month)
        : getPayrollDetail(year, month);
      const taxRequest = employeeId
        ? getEmployeeTaxStatus(employeeId, year, month)
        : getTaxStatus(year, month);
      const dashboardRequest = employeeId
        ? getEmployeeDashboard(employeeId, year, month)
        : getDashboard(year, month);
      const comparisonRequest =
        month === 1
          ? Promise.resolve(null)
          : (employeeId
              ? getEmployeePayrollComparison(employeeId, year, month)
              : getPayrollComparison(year, month)
            ).catch((requestError: unknown) => {
              if (requestError instanceof ApiError && [400, 404].includes(requestError.status)) return null;
              throw requestError;
            });
      const [detail, tax, dashboard, comparison] = await Promise.all([
        detailRequest, taxRequest, dashboardRequest, comparisonRequest,
      ]);
      setData({ detail, tax, dashboard, comparison });
    } catch (requestError) {
      setError(friendlyError(requestError));
    } finally {
      setLoading(false);
    }
  }, [employeeId, month, validPeriod, year]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) return <PageLoader label="Bordro detayı yükleniyor" />;
  if (error) return <ErrorState {...error} onRetry={validPeriod ? () => void load() : undefined} />;
  if (!data) return null;

  const { detail, tax, dashboard, comparison } = data;

  return (
    <div className="space-y-6">
      <div>
        <Link to={employeeId ? "/imports" : "/payrolls"} className="inline-flex items-center gap-2 text-sm font-semibold text-slate-500 hover:text-teal-700">
          <ArrowLeft size={17} aria-hidden="true" /> {employeeId ? "İçe aktarımlara dön" : "Bordrolarıma dön"}
        </Link>
        <div className="mt-4 flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
          <div>
            <p className="text-sm font-semibold text-teal-700">Bordro detayı</p>
            <h2 className="mt-1 text-2xl font-bold tracking-tight text-slate-950">
              {formatPeriod(detail.year, detail.month)}
            </h2>
          </div>
          <span className="w-fit rounded-full bg-emerald-50 px-3 py-1.5 text-xs font-bold text-emerald-700">
            {detail.revision.status === "ACTIVE" ? "Yayınlandı" : detail.revision.status}
          </span>
        </div>
      </div>

      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        <MetricCard label="Brüt ücret" value={formatMoney(detail.gross)} icon={CircleDollarSign} tone="teal" />
        <MetricCard label="Toplam kazanç" value={formatMoney(detail.earnings.total)} icon={CircleDollarSign} />
        <MetricCard label="Toplam kesinti" value={formatMoney(detail.deductions.total)} icon={ReceiptText} tone="rose" />
        <MetricCard label="Net ücret" value={formatMoney(detail.net)} icon={ReceiptText} />
        <MetricCard label="Gelir vergisi" value={formatMoney(dashboard.tax.income_tax)} icon={Banknote} tone="amber" />
        <MetricCard label="Ücretli gün" value={formatDays(detail.attendance.paid_days)} icon={CalendarCheck} />
        <MetricCard label="Eksik gün" value={formatDays(detail.attendance.missing_days)} icon={CalendarX} tone="amber" />
      </section>

      <div className="grid gap-6 xl:grid-cols-2">
        <BreakdownTable
          title="Kazanç Kalemleri"
          subtitle="Bordroya yansıyan kazançlar"
          items={detail.earnings.items}
          total={detail.earnings.total}
          totalTone="teal"
        />
        <BreakdownTable
          title="Kesinti Kalemleri"
          subtitle="Bordroya yansıyan kesintiler"
          items={detail.deductions.items}
          total={detail.deductions.total}
          totalTone="rose"
        />
      </div>

      {detail.attendance.absences.length > 0 ? (
        <section className="rounded-2xl border border-amber-100 bg-amber-50/70 p-5 sm:p-6">
          <h2 className="font-bold text-slate-900">Eksik Gün Kayıtları</h2>
          <div className="mt-4 divide-y divide-amber-100">
            {detail.attendance.absences.map((absence) => (
              <div key={absence.reason_code} className="flex flex-wrap items-center justify-between gap-3 py-3 text-sm">
                <div>
                  <p className="font-semibold text-slate-800">{absence.description || absence.reason_code}</p>
                  <p className="mt-0.5 text-xs text-slate-500">{absence.reason_code}</p>
                </div>
                <span className="font-bold text-amber-800">{formatDays(absence.day_count)}</span>
              </div>
            ))}
          </div>
        </section>
      ) : (
        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
          <h2 className="font-bold text-slate-900">Devamsızlık Kayıtları</h2>
          <p className="mt-3 text-sm text-slate-500">Bu bordroda devamsızlık kaydı bulunmuyor.</p>
        </section>
      )}

      <TaxPanel
        currentBracket={tax.current_bracket}
        nextBracket={tax.next_bracket}
        cumulativeBase={tax.cumulative_taxable_base}
        distanceToNext={tax.distance_to_next_bracket}
        monthlyBase={tax.monthly_taxable_base}
      />

      {comparison ? (
        <ComparisonPanel comparison={comparison} />
      ) : (
        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
          <h2 className="font-bold text-slate-900">Önceki Dönem Karşılaştırması</h2>
          <p className="mt-3 text-sm text-slate-500">Karşılaştırılacak önceki bordro bulunamadı.</p>
        </section>
      )}
    </div>
  );
}
