import { ChevronDown, ChevronUp, LoaderCircle } from "lucide-react";
import { useMemo, useState, type FormEvent } from "react";

import type {
  DetailType,
  PayrollDetailCorrectionInput,
  PayrollDetailReview,
  PayrollMappedDetail,
  PayrollMappedDetailList,
} from "../../api/types";

interface Props {
  mapped: PayrollMappedDetailList;
  review: PayrollDetailReview;
  canEdit: boolean;
  busy: string | null;
  onCorrect: (rowId: string, input: PayrollDetailCorrectionInput) => Promise<void>;
  onFinalize: () => Promise<void>;
}

function optional(value: FormDataEntryValue | null) {
  const text = String(value ?? "").trim();
  return text || null;
}

function DetailRow({ row, review, correction, canEdit, busy, onCorrect }: {
  row: PayrollMappedDetail;
  review: PayrollDetailReview;
  correction: PayrollDetailReview["corrections"][number] | undefined;
  canEdit: boolean;
  busy: string | null;
  onCorrect: Props["onCorrect"];
}) {
  const [open, setOpen] = useState(false);
  const initialType = correction?.detail_type ?? row.detail_type;
  const [detailType, setDetailType] = useState<DetailType>(initialType);
  const [ignored, setIgnored] = useState(correction?.ignored ?? false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const targetValues: Record<string, unknown> = {};
    if (!ignored && detailType === "EARNING") {
      targetValues.sgk_subject_amount = String(data.get("sgk_subject_amount") ?? "").trim();
      targetValues.income_tax_subject_amount = String(data.get("income_tax_subject_amount") ?? "").trim();
      targetValues.stamp_tax_subject_amount = String(data.get("stamp_tax_subject_amount") ?? "").trim();
      const unit = optional(data.get("unit_amount"));
      if (unit) targetValues.unit_amount = unit;
    }
    if (!ignored && detailType === "DEDUCTION") {
      targetValues.is_statutory = data.get("is_statutory") === "on";
      targetValues.is_sensitive = data.get("is_sensitive") === "on";
      const base = optional(data.get("base_amount"));
      if (base) targetValues.base_amount = base;
    }
    if (!ignored && detailType === "ABSENCE") targetValues.is_paid = data.get("is_paid") === "on";

    await onCorrect(row.id, {
      expected_row_version: review.row_version,
      expected_source_checksum: row.source_checksum,
      detail_type: ignored ? "UNMAPPED" : detailType,
      canonical_code: ignored ? null : optional(data.get("canonical_code")),
      canonical_name: ignored ? null : optional(data.get("canonical_name")),
      category: ignored ? null : optional(data.get("category")),
      amount: ignored ? null : optional(data.get("amount")),
      quantity: ignored ? null : optional(data.get("quantity")),
      rate: ignored ? null : optional(data.get("rate")),
      target_values: targetValues,
      ignored,
      reason: String(data.get("reason") ?? "").trim(),
    });
    setOpen(false);
  }

  const effective = correction ?? row;
  return (
    <div className={`rounded-xl border ${correction ? "border-emerald-200" : "border-amber-200"}`}>
      <button type="button" onClick={() => setOpen((value) => !value)} className="flex w-full items-start gap-3 p-4 text-left">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2"><span className="font-semibold text-slate-950">{row.source_label ?? `Satır ${row.source_row_index + 1}`}</span><span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${correction ? "bg-emerald-100 text-emerald-800" : "bg-amber-100 text-amber-800"}`}>{correction ? "İnsan tarafından incelendi" : "Açık inceleme"}</span></div>
          <p className="mt-2 text-sm text-slate-600">{effective.detail_type} · {effective.canonical_name ?? "Eşleşmedi"} · {effective.amount ?? effective.quantity ?? "—"}</p>
          <p className="mt-1 truncate text-xs text-slate-500">{row.source_values.map((value) => `${value.column_label}: ${value.raw_value ?? "—"}`).join(" · ")}</p>
        </div>
        {open ? <ChevronUp size={18} /> : <ChevronDown size={18} />}
      </button>
      {open && (
        <div className="border-t border-slate-200 bg-slate-50 p-4">
          <div className="mb-4 overflow-x-auto rounded-lg border border-slate-200 bg-white p-3 text-xs text-slate-700">{row.source_values.map((value) => <p key={value.source_column_id}><span className="font-semibold">{value.column_label}:</span> {value.raw_value ?? "—"}</p>)}</div>
          {canEdit ? (
            <form onSubmit={submit} className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              <label className="text-sm font-medium">Satır türü<select name="detail_type" value={detailType} disabled={ignored} onChange={(event) => setDetailType(event.target.value as DetailType)} className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2"><option value="EARNING">Kazanç</option><option value="DEDUCTION">Kesinti</option><option value="ABSENCE">Devamsızlık</option><option value="UNMAPPED">Eşleşmemiş</option></select></label>
              <label className="text-sm font-medium">Kod<input name="canonical_code" disabled={ignored} required={!ignored} defaultValue={effective.canonical_code ?? ""} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" /></label>
              <label className="text-sm font-medium">Ad<input name="canonical_name" disabled={ignored} required={!ignored} defaultValue={effective.canonical_name ?? ""} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" /></label>
              <label className="text-sm font-medium">Kategori<input name="category" disabled={ignored} required={!ignored} defaultValue={effective.category ?? ""} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" /></label>
              <label className="text-sm font-medium">Tutar<input name="amount" inputMode="decimal" disabled={ignored || detailType === "ABSENCE"} required={!ignored && (detailType === "EARNING" || detailType === "DEDUCTION")} defaultValue={effective.amount ?? ""} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" /></label>
              <label className="text-sm font-medium">Miktar / gün<input name="quantity" inputMode="decimal" disabled={ignored} required={!ignored && detailType === "ABSENCE"} defaultValue={effective.quantity ?? ""} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" /></label>
              <label className="text-sm font-medium">Oran<input name="rate" inputMode="decimal" disabled={ignored} defaultValue={effective.rate ?? ""} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" /></label>
              {detailType === "EARNING" && !ignored && <>
                <label className="text-sm font-medium">SGK'ya tabi tutar<input name="sgk_subject_amount" inputMode="decimal" required defaultValue={String(effective.target_values.sgk_subject_amount ?? "")} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" /></label>
                <label className="text-sm font-medium">Gelir vergisine tabi<input name="income_tax_subject_amount" inputMode="decimal" required defaultValue={String(effective.target_values.income_tax_subject_amount ?? "")} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" /></label>
                <label className="text-sm font-medium">Damga vergisine tabi<input name="stamp_tax_subject_amount" inputMode="decimal" required defaultValue={String(effective.target_values.stamp_tax_subject_amount ?? "")} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" /></label>
                <label className="text-sm font-medium">Birim tutar<input name="unit_amount" inputMode="decimal" defaultValue={String(effective.target_values.unit_amount ?? "")} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" /></label>
              </>}
              {detailType === "DEDUCTION" && !ignored && <div className="flex items-end gap-5 pb-2"><label className="flex items-center gap-2 text-sm"><input name="is_statutory" type="checkbox" defaultChecked={effective.target_values.is_statutory === true} /> Yasal</label><label className="flex items-center gap-2 text-sm"><input name="is_sensitive" type="checkbox" defaultChecked={effective.target_values.is_sensitive === true} /> Hassas</label><label className="text-sm">Matrah<input name="base_amount" inputMode="decimal" defaultValue={String(effective.target_values.base_amount ?? "")} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" /></label></div>}
              {detailType === "ABSENCE" && !ignored && <label className="flex items-center gap-2 self-end pb-3 text-sm"><input name="is_paid" type="checkbox" defaultChecked={effective.target_values.is_paid === true} /> Ücretli izin</label>}
              <label className="flex items-center gap-2 self-end pb-3 text-sm"><input type="checkbox" checked={ignored} onChange={(event) => { setIgnored(event.target.checked); if (event.target.checked) setDetailType("UNMAPPED"); }} /> Bu satırı yok say</label>
              <label className="text-sm font-medium sm:col-span-2 lg:col-span-3">İnceleme gerekçesi<textarea name="reason" required maxLength={1000} defaultValue={correction?.reason ?? ""} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" /></label>
              <button disabled={busy !== null} className="inline-flex items-center justify-center gap-2 rounded-lg bg-teal-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50 sm:col-span-2 lg:col-span-3">{busy === `detail-${row.id}` && <LoaderCircle className="animate-spin" size={16} />} Satır İncelemesini Kaydet</button>
            </form>
          ) : <p className="text-sm text-slate-600">Salt okunur görünüm. Düzenleme yetkiniz yok.</p>}
        </div>
      )}
    </div>
  );
}

export function DetailReviewSection({ mapped, review, canEdit, busy, onCorrect, onFinalize }: Props) {
  const corrections = useMemo(() => new Map(review.corrections.map((item) => [item.mapped_detail_id, item])), [review.corrections]);
  const editable = canEdit && !review.current_snapshot_id;
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3"><div><h3 className="text-lg font-bold text-slate-950">Detay Satırı İncelemesi</h3><p className="mt-1 text-sm text-slate-500">Her çıkarılmış satır açıkça onaylanmalı, düzeltilmeli veya yok sayılmalıdır.</p></div><span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-700">{review.corrected_count}/{review.mapped_count} incelendi</span></div>
      {review.unresolved_count > 0 && <p role="alert" className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm font-semibold text-amber-900">{review.unresolved_count} detay satırı hâlâ açık.</p>}
      {mapped.count === 0 ? <p className="mt-4 rounded-xl bg-slate-50 p-4 text-sm text-slate-600">İncelenecek detay satırı çıkarılmadı.</p> : <div className="mt-4 space-y-3">{mapped.items.map((row) => <DetailRow key={row.id} row={row} review={review} correction={corrections.get(row.id)} canEdit={editable} busy={busy} onCorrect={onCorrect} />)}</div>}
      {canEdit && !review.current_snapshot_id && <button type="button" onClick={() => void onFinalize()} disabled={review.unresolved_count > 0 || mapped.count === 0 || busy !== null} className="mt-5 inline-flex items-center gap-2 rounded-xl bg-slate-900 px-4 py-3 text-sm font-semibold text-white disabled:opacity-50">{busy === "finalize-detail" && <LoaderCircle className="animate-spin" size={17} />} Detay İncelemesini Tamamla</button>}
      {review.current_snapshot_id && <p className="mt-5 text-sm font-semibold text-emerald-700">Detay inceleme kanıt anlık görüntüsü oluşturuldu.</p>}
    </section>
  );
}
