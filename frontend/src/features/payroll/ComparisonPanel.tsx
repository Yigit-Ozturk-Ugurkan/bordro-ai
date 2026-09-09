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
  const summary = [
    { label: "Net Ücret", values: comparison.net },
    { label: "Toplam Kazanç", values: comparison.earnings },
    { label: "Toplam Kesinti", values: comparison.deductions },
    { label: "Gelir Vergisi", values: comparison.income_tax },
  ];

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

      <div className="mt-5 overflow-x-auto rounded-xl border border-slate-200">
        <table className="min-w-full text-left text-sm">
          <thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
            <tr><th className="px-4 py-3">Kalem</th><th className="px-4 py-3">Güncel dönem</th><th className="px-4 py-3">Önceki dönem</th><th className="px-4 py-3">Fark</th></tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {summary.map(({ label, values }) => (
              <tr key={label}>
                <th scope="row" className="whitespace-nowrap px-4 py-3 font-semibold text-slate-800">{label}</th>
                <td className="whitespace-nowrap px-4 py-3 font-semibold tabular-nums text-slate-900">{formatMoney(values.current)}</td>
                <td className="whitespace-nowrap px-4 py-3 tabular-nums text-slate-600">{formatMoney(values.previous)}</td>
                <td className="whitespace-nowrap px-4 py-3"><DeltaValue value={values.delta} percentage={values.delta_percent} /></td>
              </tr>
            ))}
          </tbody>
        </table>
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
