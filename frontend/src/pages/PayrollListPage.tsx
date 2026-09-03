import { ArrowRight, CalendarRange, FileText } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { getPayrollPeriods } from "../api/payroll";
import type { PayrollPeriod } from "../api/types";
import { EmptyState, ErrorState, PageLoader } from "../components/AsyncState";
import { friendlyError, type FriendlyError } from "../utils/errors";
import { formatMoney, formatPeriod } from "../utils/formatters";

function statusLabel(status: string | null): string {
  const labels: Record<string, string> = {
    ACTIVE: "Yayınlandı",
    VALIDATED: "Doğrulandı",
    DRAFT: "Taslak",
    SUPERSEDED: "Güncellendi",
    REJECTED: "Reddedildi",
  };
  return status ? labels[status] ?? status : "Hazırlanıyor";
}

export function PayrollListPage() {
  const [periods, setPeriods] = useState<PayrollPeriod[] | null>(null);
  const [error, setError] = useState<FriendlyError | null>(null);

  const load = useCallback(async () => {
    setPeriods(null);
    setError(null);
    try {
      setPeriods((await getPayrollPeriods()).periods);
    } catch (requestError) {
      setError(friendlyError(requestError));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (periods === null && !error) return <PageLoader label="Bordrolar yükleniyor" />;
  if (error) return <ErrorState {...error} onRetry={() => void load()} />;
  if (!periods?.length) {
    return <EmptyState title="Henüz bordro yok" message="Yayınlanmış bir bordro döneminiz bulunmuyor." />;
  }

  return (
    <div className="space-y-6">
      <div>
        <p className="text-sm font-semibold text-teal-700">Dönem arşivi</p>
        <h2 className="mt-1 text-2xl font-bold tracking-tight text-slate-950">Tüm Bordrolarım</h2>
        <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-500">
          Yayınlanan bordrolarınızı dönem bazında görüntüleyin ve detaylarını inceleyin.
        </p>
      </div>

      <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div className="hidden grid-cols-[1.4fr_1fr_1fr_0.8fr_40px] gap-4 border-b border-slate-100 bg-slate-50/80 px-6 py-3 text-xs font-bold uppercase tracking-[0.08em] text-slate-400 md:grid">
          <span>Dönem</span>
          <span>Brüt kazanç</span>
          <span>Net ücret</span>
          <span>Durum</span>
          <span />
        </div>
        <div className="divide-y divide-slate-100">
          {periods.map((period) => (
            <Link
              key={`${period.year}-${period.month}`}
              to={`/payrolls/${period.year}/${period.month}`}
              className="group grid gap-4 px-5 py-5 hover:bg-slate-50/80 md:grid-cols-[1.4fr_1fr_1fr_0.8fr_40px] md:items-center md:px-6"
            >
              <div className="flex items-center gap-3">
                <span className="grid size-10 place-items-center rounded-xl bg-slate-100 text-slate-600 group-hover:bg-teal-50 group-hover:text-teal-700">
                  <FileText size={18} aria-hidden="true" />
                </span>
                <div>
                  <p className="font-bold text-slate-900">{formatPeriod(period.year, period.month)}</p>
                  <p className="mt-0.5 text-xs text-slate-400">Revizyon {period.revision_no ?? "—"}</p>
                </div>
              </div>
              <div>
                <span className="text-xs text-slate-400 md:hidden">Brüt</span>
                <p className="font-semibold tabular-nums text-slate-700">{formatMoney(period.gross_earnings)}</p>
              </div>
              <div>
                <span className="text-xs text-slate-400 md:hidden">Net</span>
                <p className="font-bold tabular-nums text-slate-950">{formatMoney(period.net_pay)}</p>
              </div>
              <div>
                <span className="inline-flex rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-bold text-emerald-700">
                  {statusLabel(period.status)}
                </span>
              </div>
              <ArrowRight className="hidden text-slate-300 group-hover:text-teal-600 md:block" size={18} />
            </Link>
          ))}
        </div>
      </section>

      <div className="flex items-center gap-2 text-xs text-slate-400">
        <CalendarRange size={15} aria-hidden="true" />
        Toplam {periods.length} bordro dönemi
      </div>
    </div>
  );
}
