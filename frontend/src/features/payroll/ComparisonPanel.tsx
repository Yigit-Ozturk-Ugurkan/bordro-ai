import { ArrowDownRight, ArrowRight, ArrowUpRight, GitCompareArrows } from "lucide-react";

import type { PayrollComparison } from "../../api/types";
import {
  decimalSign,
  formatDays,
  formatMoney,
  formatPercentage,
} from "../../utils/formatters";

function DeltaValue({ value, percentage }: { value: string; percentage?: string | null }) {
  const sign = decimalSign(value);
  const Icon = sign > 0 ? ArrowUpRight : sign < 0 ? ArrowDownRight : ArrowRight;
  const color = sign > 0 ? "text-teal-700" : sign < 0 ? "text-rose-700" : "text-slate-600";

  return (
    <span className={`inline-flex items-center gap-1 font-bold tabular-nums ${color}`}>
      <Icon size={15} aria-hidden="true" />
      {formatMoney(value)}
      {percentage != null && (
        <span className="ml-1 text-xs font-semibold">({formatPercentage(percentage)})</span>
      )}
    </span>
  );
}

function CodeChanges({
  title,
  changes,
}: {
  title: string;
  changes: PayrollComparison["earnings"]["by_code"];
}) {
  const entries = Object.entries(changes);
  if (!entries.length) return null;

  return (
    <div>
      <h3 className="mb-2 text-xs font-bold uppercase tracking-[0.1em] text-slate-400">{title}</h3>
      <div className="divide-y divide-slate-100 rounded-xl border border-slate-100">
        {entries.map(([code, values]) => (
          <div key={code} className="grid grid-cols-[1fr_auto] items-center gap-3 px-3 py-2.5 text-sm">
            <span className="font-medium text-slate-600">{code}</span>
            <DeltaValue value={values.delta} />
          </div>
        ))}
      </div>
    </div>
  );
}

export function ComparisonPanel({ comparison }: { comparison: PayrollComparison }) {
  return (
    <section className="rounded-2xl border border-slate-200/80 bg-white p-5 shadow-[0_1px_2px_rgba(15,23,42,0.03)] sm:p-6">
      <div className="flex items-start gap-3">
        <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-teal-50 text-teal-700">
          <GitCompareArrows size={19} aria-hidden="true" />
        </span>
        <div>
          <h2 className="font-bold text-slate-900">Önceki Dönem Karşılaştırması</h2>
          <p className="mt-1 text-xs text-slate-500">Yalnızca dönemler arasındaki sayısal farklar</p>
        </div>
      </div>

      <div className="mt-5 grid gap-3 sm:grid-cols-3">
        <div className="rounded-xl bg-slate-50 p-4">
          <p className="text-xs text-slate-500">Önceki net</p>
          <p className="mt-2 font-bold tabular-nums text-slate-900">{formatMoney(comparison.net.previous)}</p>
        </div>
        <div className="rounded-xl bg-slate-50 p-4">
          <p className="text-xs text-slate-500">Güncel net</p>
          <p className="mt-2 font-bold tabular-nums text-slate-900">{formatMoney(comparison.net.current)}</p>
        </div>
        <div className="rounded-xl bg-slate-50 p-4">
          <p className="text-xs text-slate-500">Net fark</p>
          <p className="mt-2 text-sm">
            <DeltaValue value={comparison.net.delta} percentage={comparison.net.delta_percent} />
          </p>
        </div>
      </div>

      <div className="mt-5 grid gap-5 lg:grid-cols-2">
        <CodeChanges title="Kazanç değişimleri" changes={comparison.earnings.by_code} />
        <CodeChanges title="Kesinti değişimleri" changes={comparison.deductions.by_code} />
      </div>

      <div className="mt-5 flex flex-wrap items-center justify-between gap-2 border-t border-slate-100 pt-4 text-sm">
        <span className="text-slate-500">Eksik gün değişimi</span>
        <span className="font-bold text-slate-800">
          {formatDays(comparison.attendance.missing_days_delta)}
        </span>
      </div>
    </section>
  );
}
