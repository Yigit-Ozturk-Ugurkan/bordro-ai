import type { LucideIcon } from "lucide-react";

export function MetricCard({
  label,
  value,
  hint,
  icon: Icon,
  tone = "slate",
}: {
  label: string;
  value: string;
  hint?: string;
  icon: LucideIcon;
  tone?: "slate" | "teal" | "rose" | "amber";
}) {
  const toneClasses = {
    slate: "bg-slate-100 text-slate-600",
    teal: "bg-teal-50 text-teal-700",
    rose: "bg-rose-50 text-rose-600",
    amber: "bg-amber-50 text-amber-700",
  };

  return (
    <article className="rounded-2xl border border-slate-200/80 bg-white p-5 shadow-[0_1px_2px_rgba(15,23,42,0.03)]">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.1em] text-slate-400">
            {label}
          </p>
          <p className="mt-3 text-xl font-bold tracking-tight text-slate-900">{value}</p>
          {hint && <p className="mt-1 text-xs text-slate-500">{hint}</p>}
        </div>
        <span className={`grid size-10 shrink-0 place-items-center rounded-xl ${toneClasses[tone]}`}>
          <Icon size={19} aria-hidden="true" />
        </span>
      </div>
    </article>
  );
}
