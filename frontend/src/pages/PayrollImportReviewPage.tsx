import { ArrowLeft, ArrowRight, FileText, LoaderCircle, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { ApiError } from "../api/client";
import {
  acknowledgeWarning,
  approveImport,
  correctDetailRow,
  correctScalarField,
  finalizeDetailReview,
  finalizeScalarReview,
  getApproval,
  getApprovalHistory,
  getDetailMaterialization,
  getDetailReview,
  getMappedDetails,
  getMaterialization,
  getPayrollImport,
  getScalarReview,
  listValidations,
  materializeDetails,
  materializePayroll,
  optionalNotFound,
  processPayrollImport,
  rejectImport,
  runDetailMapping,
  runScalarMapping,
  runValidation,
  startScalarReview,
} from "../api/payrollImports";
import type {
  PayrollApprovalState,
  PayrollApprovalHistory,
  PayrollDetailCorrectionInput,
  PayrollDetailMaterialization,
  PayrollDetailReview,
  PayrollImport,
  PayrollMappedDetailList,
  PayrollMaterializationState,
  PayrollReview,
  PayrollValidationRun,
} from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { ErrorState, PageLoader } from "../components/AsyncState";
import { ImportStatusBadge } from "../components/ImportStatusBadge";
import { DetailReviewSection } from "../features/imports/DetailReviewSection";
import { ScalarReviewSection } from "../features/imports/ScalarReviewSection";
import { ValidationApprovalSection } from "../features/imports/ValidationApprovalSection";
import { friendlyError, type FriendlyError } from "../utils/errors";
import { formatDateTime, formatFileSize } from "../utils/formatters";

interface WorkspaceData {
  item: PayrollImport;
  scalarReview: PayrollReview | null;
  mappedDetails: PayrollMappedDetailList | null;
  detailReview: PayrollDetailReview | null;
  validation: PayrollValidationRun | null;
  approval: PayrollApprovalState | null;
  approvalHistory: PayrollApprovalHistory;
  materialization: PayrollMaterializationState | null;
  detailMaterialization: PayrollDetailMaterialization | null;
}

export function PayrollImportReviewPage() {
  const { importId = "" } = useParams();
  const { user } = useAuth();
  const [data, setData] = useState<WorkspaceData | null>(null);
  const [loadError, setLoadError] = useState<FriendlyError | null>(null);
  const [actionError, setActionError] = useState<FriendlyError | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const isPayrollAdmin = user?.roles.includes("PAYROLL_ADMIN") ?? false;
  const canEdit = user?.roles.some((role) => role === "PAYROLL_ADMIN" || role === "HR_ADMIN") ?? false;

  const load = useCallback(async () => {
    setLoadError(null);
    try {
      const item = await getPayrollImport(importId);
      const [scalarReview, mappedDetails, detailReview, validations, approval, approvalHistory, materialization, detailMaterialization] = await Promise.all([
        optionalNotFound(getScalarReview(importId)),
        optionalNotFound(getMappedDetails(importId)),
        optionalNotFound(getDetailReview(importId)),
        listValidations(importId),
        getApproval(importId),
        getApprovalHistory(importId),
        getMaterialization(importId),
        optionalNotFound(getDetailMaterialization(importId)),
      ]);
      setData({
        item,
        scalarReview,
        mappedDetails,
        detailReview,
        validation: validations.items[0] ?? null,
        approval,
        approvalHistory,
        materialization,
        detailMaterialization,
      });
    } catch (reason) {
      setLoadError(friendlyError(reason));
    }
  }, [importId]);

  useEffect(() => { void load(); }, [load]);

  async function act(key: string, action: () => Promise<unknown>, success: string) {
    setBusy(key);
    setActionError(null);
    setNotice(null);
    try {
      await action();
      setNotice(success);
      await load();
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 409) {
        setActionError({ title: "İnceleme güncellendi", message: "Başka bir değişiklik kaydedildi. En güncel veriler yeniden yüklendi; lütfen işlemi tekrar kontrol edin." });
        await load();
      } else {
        setActionError(friendlyError(reason));
      }
    } finally {
      setBusy(null);
    }
  }

  const payrollPath = useMemo(() => {
    const materialized = data?.materialization?.materialization;
    return materialized
      ? `/employees/${materialized.employee_id}/payrolls/${materialized.period_year}/${materialized.period_month}`
      : null;
  }, [data]);

  if (!data && !loadError) return <PageLoader label="İnceleme çalışma alanı yükleniyor" />;
  if (loadError || !data) return <ErrorState {...(loadError ?? { title: "İçe aktarım bulunamadı", message: "Kayıt yüklenemedi." })} onRetry={() => void load()} />;

  const { item, scalarReview, mappedDetails, detailReview, validation, approval, approvalHistory, materialization, detailMaterialization } = data;
  const needsDetails = item.reader_table_count > 0;
  const fullyMaterialized = materialization?.materialized && (!needsDetails || Boolean(detailMaterialization));

  return (
    <section className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Link to="/imports" className="inline-flex items-center gap-2 text-sm font-semibold text-slate-600 hover:text-teal-700"><ArrowLeft size={17} /> İçe aktarımlara dön</Link>
        <button type="button" onClick={() => void load()} disabled={busy !== null} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700"><RefreshCw size={16} /> Yenile</button>
      </div>

      <header className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex min-w-0 gap-3"><span className="rounded-xl bg-teal-50 p-3 text-teal-700"><FileText aria-hidden="true" /></span><div className="min-w-0"><p className="text-sm font-semibold text-teal-700">Bordro belgesi</p><h2 className="truncate text-xl font-bold text-slate-950">{item.document.original_filename}</h2><p className="mt-1 text-sm text-slate-500">{item.document.detected_mime_type} · {formatFileSize(item.document.size_bytes)} · {formatDateTime(item.created_at)}</p></div></div>
          <ImportStatusBadge status={item.status} />
        </div>
        <dl className="mt-5 grid gap-3 rounded-xl bg-slate-50 p-4 text-sm sm:grid-cols-2 lg:grid-cols-4">
          <div><dt className="text-xs text-slate-500">Çalışan</dt><dd className="mt-1 font-semibold text-slate-800">{item.detected_employee_id ?? "Henüz belirlenmedi"}</dd></div>
          <div><dt className="text-xs text-slate-500">Dönem</dt><dd className="mt-1 font-semibold text-slate-800">{item.detected_year && item.detected_month ? `${item.detected_month}/${item.detected_year}` : "Henüz belirlenmedi"}</dd></div>
          <div><dt className="text-xs text-slate-500">Alan / tablo</dt><dd className="mt-1 font-semibold text-slate-800">{scalarReview?.fields.length ?? 0} alan · {item.reader_table_count} tablo</dd></div>
          <div><dt className="text-xs text-slate-500">Sağlayıcı</dt><dd className="mt-1 font-semibold text-slate-800">{item.reader_provider}</dd></div>
        </dl>
        {item.reader_warning_codes.length > 0 && <p role="alert" className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">Belge uyarıları: {item.reader_warning_codes.join(" · ")}</p>}
        {item.last_error_code && <p role="alert" className="mt-4 rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm text-rose-900">İşleme başarısız oldu ({item.last_error_code}). Belgeyi yeniden işleyebilirsiniz.</p>}
        {canEdit && (item.status === "UPLOADED" || item.status === "FAILED") && <button type="button" disabled={busy !== null} onClick={() => void act("process", () => processPayrollImport(importId), "Belge işlendi.")} className="mt-4 inline-flex items-center gap-2 rounded-xl bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50">{busy === "process" && <LoaderCircle className="animate-spin" size={16} />} Belgeyi İşle</button>}
      </header>

      {actionError && <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-900"><p className="font-semibold">{actionError.title}</p><p className="mt-1">{actionError.message}</p></div>}
      {notice && <p role="status" className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm font-semibold text-emerald-800">{notice}</p>}

      {!scalarReview && canEdit && (item.status === "EXTRACTED" || item.status === "REVIEW_REQUIRED") && (
        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"><h3 className="font-bold text-slate-950">Skaler incelemeyi başlatın</h3><p className="mt-1 text-sm text-slate-500">Çıkarılan alanlar kurallı eşlemeden geçirilip insan incelemesine açılır.</p><button type="button" disabled={busy !== null} onClick={() => void act("start-scalar", async () => { await runScalarMapping(importId); await startScalarReview(importId); }, "Skaler inceleme başlatıldı.")} className="mt-4 inline-flex items-center gap-2 rounded-xl bg-teal-600 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50">{busy === "start-scalar" && <LoaderCircle className="animate-spin" size={16} />} Eşle ve İncelemeyi Başlat</button></section>
      )}

      {scalarReview && <ScalarReviewSection review={scalarReview} canEdit={canEdit} busy={busy} onCorrect={(fieldId, canonicalKey, value, reason) => act(`scalar-${fieldId}`, () => correctScalarField(importId, fieldId, { expected_review_version: scalarReview.version, canonical_key: canonicalKey, value, reason }), "Alan düzeltmesi kaydedildi.")} onFinalize={() => act("finalize-scalar", () => finalizeScalarReview(importId, scalarReview.version), "Skaler inceleme tamamlandı.")} />}

      {needsDetails && !mappedDetails && (
        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"><h3 className="font-bold text-slate-950">Detay eşleme</h3><p className="mt-1 text-sm text-slate-500">Belgedeki genel tablo satırları kazanç, kesinti veya devamsızlık ayrıntılarına eşlenir.</p>{isPayrollAdmin ? <button type="button" disabled={busy !== null} onClick={() => void act("map-details", () => runDetailMapping(importId), "Detay satırları eşlendi.")} className="mt-4 inline-flex items-center gap-2 rounded-xl bg-teal-600 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50">{busy === "map-details" && <LoaderCircle className="animate-spin" size={16} />} Detayları Eşle</button> : <p className="mt-3 text-sm text-slate-600">İlk detay eşlemesi PAYROLL_ADMIN tarafından başlatılmalıdır.</p>}</section>
      )}

      {!needsDetails && <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"><h3 className="font-bold text-slate-950">Detay Satırları</h3><p className="mt-2 text-sm text-slate-600">Bu belgeden tablo veya detay satırı çıkarılmadı.</p></section>}

      {mappedDetails && detailReview && <DetailReviewSection mapped={mappedDetails} review={detailReview} canEdit={canEdit} busy={busy} onCorrect={(rowId, input: PayrollDetailCorrectionInput) => act(`detail-${rowId}`, () => correctDetailRow(importId, rowId, input), "Detay satırı kaydedildi.")} onFinalize={() => act("finalize-detail", () => finalizeDetailReview(importId, detailReview.row_version), "Detay inceleme tamamlandı.")} />}

      <ValidationApprovalSection run={validation} approval={approval} acknowledgedWarningIds={approvalHistory.acknowledgements.filter((item) => item.validation_run_id === validation?.id).map((item) => item.validation_result_id)} canValidate={canEdit} isPayrollAdmin={isPayrollAdmin} snapshotReady={Boolean(scalarReview?.current_snapshot_id)} detailReady={!needsDetails || Boolean(detailReview?.current_snapshot_id)} busy={busy} onValidate={() => act("validate", () => runValidation(importId, scalarReview?.current_snapshot_id ?? ""), "Doğrulama tamamlandı.")} onAcknowledge={(resultId, note) => act(`ack-${resultId}`, () => acknowledgeWarning(importId, validation?.id ?? "", resultId, note.trim() || null), "Uyarı kabul edildi.")} onApprove={(note) => act("approve", () => approveImport(importId, validation?.id ?? "", note.trim() || null), "İçe aktarım onaylandı.")} onReject={(reason) => act("reject", () => rejectImport(importId, validation?.id ?? "", reason), "İçe aktarım reddedildi.")} />

      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <h3 className="text-lg font-bold text-slate-950">Bordroya Aktarım</h3>
        <p className="mt-1 text-sm text-slate-500">Onaylı skaler kanıt önce bordro sürümüne, varsa onaylı detay kanıtı daha sonra o sürüme aktarılır.</p>
        <div className="mt-4 flex flex-wrap gap-3">
          {isPayrollAdmin && approval?.approval_status === "APPROVED" && approval.decision && !materialization?.materialized && <button type="button" disabled={busy !== null} onClick={() => void act("materialize", () => materializePayroll(importId, approval.decision!.id), "Skaler bordro verileri aktarıldı.")} className="inline-flex items-center gap-2 rounded-xl bg-teal-600 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50">{busy === "materialize" && <LoaderCircle className="animate-spin" size={16} />} Skaler Bordroyu Aktar</button>}
          {isPayrollAdmin && materialization?.materialized && needsDetails && detailReview?.current_snapshot_id && !detailMaterialization && <button type="button" disabled={busy !== null} onClick={() => void act("materialize-details", () => materializeDetails(importId), "Detay bordro verileri aktarıldı.")} className="inline-flex items-center gap-2 rounded-xl bg-teal-600 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50">{busy === "materialize-details" && <LoaderCircle className="animate-spin" size={16} />} Detayları Bordroya Aktar</button>}
          {fullyMaterialized && payrollPath && <Link to={payrollPath} className="inline-flex items-center gap-2 rounded-xl bg-emerald-600 px-4 py-2.5 text-sm font-semibold text-white">Bordroyu Gör <ArrowRight size={17} /></Link>}
        </div>
        {materialization?.materialized && <p className="mt-3 text-sm text-emerald-700">Skaler aktarım tamamlandı: revizyon {materialization.materialization?.revision_no}.</p>}
        {detailMaterialization && <p className="mt-1 text-sm text-emerald-700">Detay aktarımı tamamlandı: {detailMaterialization.earning_count} kazanç, {detailMaterialization.deduction_count} kesinti, {detailMaterialization.absence_count} devamsızlık.</p>}
        {fullyMaterialized && <p className="mt-2 text-sm font-semibold text-emerald-800">Bordro sisteme aktarıldı.</p>}
        {!isPayrollAdmin && <p className="mt-3 text-sm text-slate-600">Onay ve aktarım kontrolleri yalnızca PAYROLL_ADMIN rolüne açıktır.</p>}
      </section>
    </section>
  );
}
