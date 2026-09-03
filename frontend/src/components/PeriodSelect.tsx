import { CalendarDays, ChevronDown } from "lucide-react";

import type { PayrollPeriod } from "../api/types";
import { formatPeriod } from "../utils/formatters";

export function PeriodSelect({
  periods,
  value,
  onChange,
}: {
  periods: PayrollPeriod[];
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="relative flex min-w-48 items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 shadow-sm">
      <CalendarDays size={17} className="shrink-0 text-teal-600" aria-hidden="true" />
      <span className="sr-only">Dönem</span>
      <select
        aria-label="Dönem"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="h-11 w-full appearance-none bg-transparent pr-6 text-sm font-semibold text-slate-700 outline-none"
      >
        {periods.map((period) => {
          const key = `${period.year}-${period.month}`;
          return (
            <option key={key} value={key}>
              {formatPeriod(period.year, period.month)}
            </option>
          );
        })}
      </select>
      <ChevronDown size={15} className="pointer-events-none absolute right-3 text-slate-400" />
    </label>
  );
}
