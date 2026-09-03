import { Landmark } from "lucide-react";

export function BrandMark({ compact = false }: { compact?: boolean }) {
  return (
    <div className="flex items-center gap-3">
      <span className="grid size-10 place-items-center rounded-xl bg-teal-400 text-slate-950 shadow-[0_8px_24px_rgba(45,212,191,0.24)]">
        <Landmark size={21} strokeWidth={2.3} aria-hidden="true" />
      </span>
      {!compact && (
        <span>
          <span className="block text-[17px] font-bold tracking-tight text-white">
            Bordro AI
          </span>
          <span className="block text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-400">
            Çalışan portalı
          </span>
        </span>
      )}
    </div>
  );
}
