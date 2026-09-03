import type { MoneyLine } from "../api/types";
import { formatMoney } from "../utils/formatters";

export function BreakdownTable({
  title,
  subtitle,
  items,
  total,
  totalTone = "slate",
}: {
  title: string;
  subtitle: string;
  items: MoneyLine[];
  total: string;
  totalTone?: "slate" | "teal" | "rose";
}) {
  const totalClass = {
    slate: "text-slate-900",
    teal: "text-teal-700",
    rose: "text-rose-700",
  }[totalTone];

  return (
    <section className="overflow-hidden rounded-2xl border border-slate-200/80 bg-white shadow-[0_1px_2px_rgba(15,23,42,0.03)]">
      <div className="border-b border-slate-100 px-5 py-4 sm:px-6">
        <h2 className="font-bold text-slate-900">{title}</h2>
        <p className="mt-1 text-xs text-slate-500">{subtitle}</p>
      </div>
      {items.length === 0 ? (
        <p className="px-6 py-8 text-center text-sm text-slate-500">Kayıt bulunmuyor.</p>
      ) : (
        <div className="divide-y divide-slate-100">
          {items.map((item) => (
            <div key={item.code} className="flex items-center justify-between gap-4 px-5 py-3.5 sm:px-6">
              <div className="min-w-0">
                <p className="truncate text-sm font-semibold text-slate-700">
                  {item.description || item.label || item.code}
                </p>
                <p className="mt-0.5 text-[11px] font-medium uppercase tracking-wide text-slate-400">
                  {item.code}{item.category ? ` · ${item.category}` : ""}
                </p>
              </div>
              <span className="shrink-0 text-sm font-bold tabular-nums text-slate-900">
                {formatMoney(item.amount)}
              </span>
            </div>
          ))}
        </div>
      )}
      <div className="flex items-center justify-between border-t border-slate-200 bg-slate-50/70 px-5 py-4 sm:px-6">
        <span className="text-sm font-semibold text-slate-600">Toplam</span>
        <span className={`text-base font-bold tabular-nums ${totalClass}`}>
          {formatMoney(total)}
        </span>
      </div>
    </section>
  );
}
