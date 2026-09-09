import { ChevronDown, ChevronUp, LoaderCircle } from "lucide-react";
import { useState, type FormEvent } from "react";

import type { PayrollReview, PayrollReviewField } from "../../api/types";

const canonicalFields = [
  "employee_identifier", "period_year", "period_month", "gross_earnings",
  "sgk_base", "income_tax_base", "stamp_tax_base", "employee_sgk",
  "employee_unemployment", "income_tax", "stamp_tax", "total_earnings",
  "total_deductions", "net_pay", "paid_days", "missing_days",
  "cumulative_income_tax_base",
];

interface Props {
  review: PayrollReview;
  canEdit: boolean;
  busy: string | null;
  onCorrect: (fieldId: string, canonicalKey: string, value: string, reason: string) => Promise<void>;
  onFinalize: () => Promise<void>;
}

function valueText(field: PayrollReviewField) {
  const value = field.effective.typed_value?.value;
  return value === null || value === undefined ? "—" : String(value);
}

function ScalarRow({ field, review, canEdit, busy, onCorrect }: {
  field: PayrollReviewField;
  review: PayrollReview;
  canEdit: boolean;
  busy: string | null;
  onCorrect: Props["onCorrect"];
}) {
  const [open, setOpen] = useState(false);
  const [canonicalKey, setCanonicalKey] = useState(field.effective.canonical_key ?? field.adapter.candidate_canonical_keys[0] ?? "");
  const [value, setValue] = useState(valueText(field) === "—" ? field.source.raw_value ?? "" : valueText(field));
  const [reason, setReason] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    await onCorrect(field.adapter.mapped_field_id, canonicalKey, value, reason);
    setReason("");
    setOpen(false);
  }

  const needsAttention = field.review_status !== "RESOLVED" || field.issue_codes.length > 0;
  return (
    <div className={`rounded-xl border ${needsAttention ? "border-amber-200" : "border-slate-200"}`}>
      <button type="button" onClick={() => setOpen((value) => !value)} className="flex w-full items-start gap-3 p-4 text-left">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-semibold text-slate-950">{field.source.label}</span>
            <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${needsAttention ? "bg-amber-100 text-amber-800" : "bg-emerald-100 text-emerald-800"}`}>
              {field.review_status === "RESOLVED" ? "Çözüldü" : "İnceleme gerekli"}
            </span>
          </div>
          <dl className="mt-2 grid gap-2 text-sm sm:grid-cols-3">
            <div><dt className="text-xs text-slate-500">Belgedeki değer</dt><dd className="break-words text-slate-800">{field.source.raw_value ?? "—"}</dd></div>
            <div><dt className="text-xs text-slate-500">Hedef alan</dt><dd className="font-mono text-xs text-slate-800">{field.effective.canonical_key ?? "Eşleşmedi"}</dd></div>
            <div><dt className="text-xs text-slate-500">Etkin değer</dt><dd className="text-slate-800">{valueText(field)}</dd></div>
          </dl>
          {field.issue_codes.length > 0 && <p className="mt-2 text-xs text-amber-800">{field.issue_codes.join(" · ")}</p>}
        </div>
        {open ? <ChevronUp size={18} /> : <ChevronDown size={18} />}
      </button>

      {open && (
        <div className="border-t border-slate-200 bg-slate-50 p-4">
          <div className="mb-4 grid gap-3 text-xs text-slate-600 sm:grid-cols-3">
            <p><span className="block font-semibold text-slate-700">Kaynak metin</span>{field.source.source_text ?? "—"}</p>
            <p><span className="block font-semibold text-slate-700">Güven</span>{field.source.confidence ?? "—"}</p>
            <p><span className="block font-semibold text-slate-700">Sayfa</span>{field.source.page_number ?? "—"}</p>
          </div>
          {canEdit ? (
            <form onSubmit={submit} className="grid gap-3 md:grid-cols-2">
              <label className="text-sm font-medium text-slate-700">Hedef alan
                <select aria-label={`${field.source.label} hedef alan`} required value={canonicalKey} onChange={(event) => setCanonicalKey(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2">
                  <option value="">Alan seçin</option>
                  {canonicalFields.map((key) => <option key={key} value={key}>{key}</option>)}
                </select>
              </label>
              <label className="text-sm font-medium text-slate-700">Düzeltilmiş değer
                <input aria-label={`${field.source.label} düzeltilmiş değer`} required value={value} onChange={(event) => setValue(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" />
              </label>
              <label className="text-sm font-medium text-slate-700 md:col-span-2">Düzeltme gerekçesi
                <textarea aria-label={`${field.source.label} düzeltme gerekçesi`} required minLength={1} maxLength={1000} value={reason} onChange={(event) => setReason(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" />
              </label>
              <button disabled={busy !== null} className="inline-flex items-center justify-center gap-2 rounded-lg bg-teal-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50 md:col-span-2">
                {busy === `scalar-${field.adapter.mapped_field_id}` && <LoaderCircle className="animate-spin" size={16} />} Düzeltmeyi Kaydet
              </button>
            </form>
          ) : <p className="text-sm text-slate-600">Salt okunur görünüm. Düzenleme yetkiniz yok.</p>}
        </div>
      )}
    </div>
  );
}

export function ScalarReviewSection({ review, canEdit, busy, onCorrect, onFinalize }: Props) {
  const editable = canEdit && !review.current_snapshot_id;
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div><h3 className="text-lg font-bold text-slate-950">Skaler Alan İncelemesi</h3><p className="mt-1 text-sm text-slate-500">Belgedeki ham değer ile sisteme aktarılacak etkin değeri karşılaştırın.</p></div>
        <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-700">Sürüm {review.version}</span>
      </div>
      {review.issues.length > 0 && (
        <div role="alert" className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
          <p className="font-semibold">Çözülmemiş sorunlar</p>
          <ul className="mt-1 list-disc pl-5">{review.issues.map((issue, index) => <li key={`${issue.code}-${index}`}>{issue.code}{issue.canonical_key ? ` · ${issue.canonical_key}` : ""}</li>)}</ul>
        </div>
      )}
      <div className="mt-4 space-y-3">
        {review.fields.map((field) => <ScalarRow key={field.adapter.mapped_field_id} field={field} review={review} canEdit={editable} busy={busy} onCorrect={onCorrect} />)}
      </div>
      {canEdit && !review.current_snapshot_id && (
        <button type="button" onClick={() => void onFinalize()} disabled={!review.complete || busy !== null} className="mt-5 inline-flex items-center gap-2 rounded-xl bg-slate-900 px-4 py-3 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50">
          {busy === "finalize-scalar" && <LoaderCircle className="animate-spin" size={17} />} Skaler İncelemeyi Tamamla
        </button>
      )}
      {review.current_snapshot_id && <p className="mt-5 text-sm font-semibold text-emerald-700">Skaler inceleme kanıt anlık görüntüsü oluşturuldu.</p>}
    </section>
  );
}
