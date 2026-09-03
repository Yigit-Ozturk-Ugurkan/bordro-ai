import { Landmark, TrendingUp } from "lucide-react";

import type { TaxBracket } from "../../api/types";
import { formatMoney, formatRate } from "../../utils/formatters";

export function TaxPanel({
  currentBracket,
  nextBracket,
  cumulativeBase,
  distanceToNext,
  monthlyBase,
}: {
  currentBracket: TaxBracket | null;
  nextBracket: TaxBracket | null;
  cumulativeBase: string;
  distanceToNext: string | null;
  monthlyBase?: string | null;
}) {
  return (
    <section className="rounded-2xl border border-slate-200/80 bg-white p-5 shadow-[0_1px_2px_rgba(15,23,42,0.03)] sm:p-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="font-bold text-slate-900">Vergi Durumu</h2>
          <p className="mt-1 text-xs text-slate-500">Kümülatif matrahınıza göre güncel konum</p>
        </div>
        <span className="grid size-10 place-items-center rounded-xl bg-indigo-50 text-indigo-600">
          <Landmark size={19} aria-hidden="true" />
        </span>
      </div>

      <div className="mt-6 grid gap-4 sm:grid-cols-2">
        <div className="rounded-xl bg-slate-950 p-4 text-white">
          <p className="text-xs font-medium text-slate-400">Mevcut vergi dilimi</p>
          <p className="mt-2 text-2xl font-bold">{formatRate(currentBracket?.rate)}</p>
          {currentBracket && (
            <p className="mt-1 text-xs text-slate-400">
              {formatMoney(currentBracket.lower_limit)} – {formatMoney(currentBracket.upper_limit)}
            </p>
          )}
        </div>
        <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
          <p className="text-xs font-medium text-slate-500">Sonraki vergi dilimi</p>
          {nextBracket ? (
            <>
              <p className="mt-2 text-2xl font-bold text-slate-900">{formatRate(nextBracket.rate)}</p>
              <p className="mt-1 text-xs text-slate-500">
                Kalan: {formatMoney(distanceToNext)}
              </p>
            </>
          ) : (
            <p className="mt-3 text-sm font-semibold leading-5 text-slate-700">
              En yüksek vergi dilimindesiniz.
            </p>
          )}
        </div>
      </div>

      <dl className="mt-5 divide-y divide-slate-100 border-t border-slate-100">
        <div className="flex items-center justify-between py-3 text-sm">
          <dt className="text-slate-500">Kümülatif vergi matrahı</dt>
          <dd className="font-bold tabular-nums text-slate-900">{formatMoney(cumulativeBase)}</dd>
        </div>
        {monthlyBase != null && (
          <div className="flex items-center justify-between py-3 text-sm">
            <dt className="text-slate-500">Aylık vergi matrahı</dt>
            <dd className="font-semibold tabular-nums text-slate-700">{formatMoney(monthlyBase)}</dd>
          </div>
        )}
        <div className="flex items-center justify-between pt-3 text-sm">
          <dt className="flex items-center gap-2 text-slate-500">
            <TrendingUp size={15} aria-hidden="true" /> Sonraki dilime kalan
          </dt>
          <dd className="font-semibold tabular-nums text-slate-700">
            {nextBracket ? formatMoney(distanceToNext) : "—"}
          </dd>
        </div>
      </dl>
    </section>
  );
}
