import { AlertOctagon, AlertTriangle, CheckCircle2, Info, LoaderCircle, ShieldCheck } from "lucide-react";
import { useState } from "react";

import type { PayrollApprovalState, PayrollValidationRun, ValidationSeverity } from "../../api/types";

const severityConfig: Record<ValidationSeverity, { label: string; style: string; icon: typeof Info }> = {
  BLOCKING: { label: "ENGELLEYİCİ", style: "border-rose-300 bg-rose-50 text-rose-900", icon: AlertOctagon },
  ERROR: { label: "HATA", style: "border-orange-300 bg-orange-50 text-orange-900", icon: AlertTriangle },
  WARNING: { label: "UYARI", style: "border-amber-300 bg-amber-50 text-amber-900", icon: AlertTriangle },
  INFO: { label: "BİLGİ", style: "border-sky-300 bg-sky-50 text-sky-900", icon: Info },
};

interface Props {
  run: PayrollValidationRun | null;
  approval: PayrollApprovalState | null;
  canValidate: boolean;
  isPayrollAdmin: boolean;
  snapshotReady: boolean;
  detailReady: boolean;
  busy: string | null;
  acknowledgedWarningIds: string[];
  onValidate: () => Promise<void>;
  onAcknowledge: (resultId: string, note: string) => Promise<void>;
  onApprove: (note: string) => Promise<void>;
  onReject: (reason: string) => Promise<void>;
}

export function ValidationApprovalSection(props: Props) {
  const { run, approval, canValidate, isPayrollAdmin, snapshotReady, detailReady, busy, acknowledgedWarningIds, onValidate, onAcknowledge, onApprove, onReject } = props;
  const [note, setNote] = useState("");
  const [rejectReason, setRejectReason] = useState("");
  const acknowledged = new Set(acknowledgedWarningIds);

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div><h3 className="text-lg font-bold text-slate-950">Doğrulama ve Onay</h3><p className="mt-1 text-sm text-slate-500">Sunucunun ürettiği bulgular ve karar hazırlığı burada gösterilir.</p></div>
        {canValidate && <button type="button" onClick={() => void onValidate()} disabled={!snapshotReady || busy !== null} className="inline-flex items-center gap-2 rounded-xl bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50">{busy === "validate" && <LoaderCircle className="animate-spin" size={16} />} Doğrulamayı Çalıştır</button>}
      </div>

      {!run ? <p className="mt-4 rounded-xl bg-slate-50 p-4 text-sm text-slate-600">Skaler inceleme tamamlandıktan sonra doğrulama çalıştırılabilir.</p> : (
        <>
          <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
            {(["BLOCKING", "ERROR", "WARNING", "INFO"] as ValidationSeverity[]).map((severity) => {
              const count = run.results.filter((item) => item.severity === severity).length;
              return <div key={severity} className={`rounded-xl border p-3 ${severityConfig[severity].style}`}><p className="text-xs font-bold">{severityConfig[severity].label}</p><p className="mt-1 text-2xl font-bold">{count}</p></div>;
            })}
          </div>
          <div className="mt-4 space-y-4">
            {(["BLOCKING", "ERROR", "WARNING", "INFO"] as ValidationSeverity[]).map((severity) => {
              const results = run.results.filter((item) => item.severity === severity);
              if (results.length === 0) return null;
              return <div key={severity} className="space-y-2"><h4 className="text-sm font-bold text-slate-800">{severityConfig[severity].label}</h4>{results.map((result) => {
              const config = severityConfig[result.severity];
              const Icon = config.icon;
              const isAcknowledged = acknowledged.has(result.id);
              return (
                <article key={result.id} className={`rounded-xl border p-4 ${config.style}`}>
                  <div className="flex items-start gap-3"><Icon size={19} className="mt-0.5 shrink-0" /><div className="min-w-0 flex-1"><p className="text-xs font-bold">{config.label} · {result.category} · {result.validation_code}</p><p className="mt-1 text-sm">{result.message}</p>{result.canonical_key && <p className="mt-1 font-mono text-xs">{result.canonical_key}</p>}</div></div>
                  {result.severity === "WARNING" && isPayrollAdmin && !isAcknowledged && approval?.approval_status === "NOT_DECIDED" && (
                    <button type="button" disabled={busy !== null} onClick={() => void onAcknowledge(result.id, note)} className="mt-3 rounded-lg border border-amber-400 bg-white px-3 py-2 text-xs font-semibold">Uyarıyı Kabul Et</button>
                  )}
                  {result.severity === "WARNING" && isAcknowledged && <p className="mt-2 flex items-center gap-1 text-xs font-semibold"><CheckCircle2 size={14} /> Kabul edildi</p>}
                </article>
              );
            })}</div>; })}
          </div>
        </>
      )}

      {run && <div className="mt-5 rounded-xl border border-slate-200 bg-slate-50 p-4">
        <div className="flex items-center gap-2"><ShieldCheck className="text-teal-700" /><p className="font-semibold text-slate-950">Karar durumu: {approval?.approval_status ?? "NOT_DECIDED"}</p></div>
        <p className="mt-1 text-sm text-slate-600">Hazırlık: {run.readiness} · Bekleyen uyarı: {approval?.warnings.remaining ?? run.warning_count}</p>
        {!detailReady && <p className="mt-2 text-sm font-semibold text-amber-700">Onaydan önce detay incelemesi tamamlanmalıdır.</p>}
        {isPayrollAdmin && approval?.approval_status === "NOT_DECIDED" && (
          <div className="mt-4 grid gap-3 md:grid-cols-2">
            <label className="text-sm font-medium text-slate-700 md:col-span-2">Karar notu<input value={note} maxLength={1000} onChange={(event) => setNote(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2" /></label>
            <button type="button" disabled={run.readiness !== "READY_FOR_FUTURE_APPROVAL" || (approval?.warnings.remaining ?? 0) > 0 || !detailReady || busy !== null} onClick={() => void onApprove(note)} className="rounded-lg bg-emerald-600 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50">Onayla</button>
            <div className="flex gap-2"><input aria-label="Reddetme gerekçesi" placeholder="Reddetme gerekçesi" required value={rejectReason} onChange={(event) => setRejectReason(event.target.value)} className="min-w-0 flex-1 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm" /><button type="button" disabled={!rejectReason.trim() || busy !== null} onClick={() => void onReject(rejectReason)} className="rounded-lg bg-rose-600 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50">Reddet</button></div>
          </div>
        )}
        {!isPayrollAdmin && <p className="mt-3 text-sm text-slate-600">Onay, ret ve uyarı kabulü yalnızca PAYROLL_ADMIN yetkisindedir.</p>}
      </div>}
    </section>
  );
}
