import { FileUp, LoaderCircle, UploadCloud } from "lucide-react";
import { useState, type ChangeEvent, type FormEvent } from "react";
import { Link } from "react-router-dom";

import { processPayrollImport, uploadPayrollImport } from "../api/payrollImports";
import type { PayrollImport } from "../api/types";
import { ImportStatusBadge } from "../components/ImportStatusBadge";
import { friendlyError, type FriendlyError } from "../utils/errors";
import { formatFileSize } from "../utils/formatters";

const accepted = ".pdf,.jpg,.jpeg,.png,.bmp,.tif,.tiff,.webp";

export function PayrollUploadPage() {
  const [file, setFile] = useState<File | null>(null);
  const [uploaded, setUploaded] = useState<PayrollImport | null>(null);
  const [busy, setBusy] = useState<"upload" | "process" | null>(null);
  const [error, setError] = useState<FriendlyError | null>(null);

  function chooseFile(event: ChangeEvent<HTMLInputElement>) {
    setFile(event.target.files?.[0] ?? null);
    setUploaded(null);
    setError(null);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!file) return;
    setBusy("upload");
    setError(null);
    try {
      setUploaded(await uploadPayrollImport(file));
    } catch (reason) {
      setError(friendlyError(reason));
    } finally {
      setBusy(null);
    }
  }

  async function processDocument() {
    if (!uploaded) return;
    setBusy("process");
    setError(null);
    try {
      setUploaded(await processPayrollImport(uploaded.id));
    } catch (reason) {
      setError(friendlyError(reason));
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="mx-auto max-w-3xl space-y-6">
      <div>
        <p className="text-sm font-semibold text-teal-700">Yeni içe aktarım</p>
        <h2 className="mt-1 text-2xl font-bold text-slate-950">Bordro Yükle</h2>
        <p className="mt-2 text-sm text-slate-500">
          PDF, JPG, PNG, BMP, TIFF veya WebP belge yükleyin. Varsayılan yükleme sınırı 25 MB'dır; kurulum ayarına göre değişebilir.
        </p>
      </div>

      <form onSubmit={submit} className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <label
          htmlFor="payroll-file"
          className="flex cursor-pointer flex-col items-center rounded-2xl border-2 border-dashed border-slate-300 bg-slate-50 px-6 py-12 text-center hover:border-teal-400 hover:bg-teal-50/40"
        >
          <UploadCloud size={38} className="text-teal-600" aria-hidden="true" />
          <span className="mt-4 font-semibold text-slate-900">Bordro belgesi seçin</span>
          <span className="mt-1 text-sm text-slate-500">Dosya seçiciyi açmak için tıklayın</span>
        </label>
        <input id="payroll-file" type="file" accept={accepted} onChange={chooseFile} className="sr-only" />

        {file && (
          <div className="mt-5 flex items-center gap-3 rounded-xl border border-slate-200 p-4">
            <FileUp className="shrink-0 text-teal-600" aria-hidden="true" />
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-semibold text-slate-900">{file.name}</p>
              <p className="text-xs text-slate-500">{formatFileSize(file.size)}</p>
            </div>
          </div>
        )}

        <button
          type="submit"
          disabled={!file || busy !== null || uploaded !== null}
          className="mt-5 inline-flex w-full items-center justify-center gap-2 rounded-xl bg-teal-600 px-4 py-3 text-sm font-semibold text-white hover:bg-teal-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {busy === "upload" && <LoaderCircle className="animate-spin" size={18} aria-hidden="true" />}
          {busy === "upload" ? "Belge yükleniyor" : "Belgeyi Yükle"}
        </button>
      </form>

      {error && (
        <div role="alert" className="rounded-2xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">
          <p className="font-semibold">{error.title}</p><p className="mt-1">{error.message}</p>
        </div>
      )}

      {uploaded && (
        <div className="rounded-2xl border border-emerald-200 bg-white p-6 shadow-sm" aria-live="polite">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div><h3 className="font-semibold text-slate-950">Belge güvenle kaydedildi</h3><p className="mt-1 text-sm text-slate-500">İçeriği çıkarmak için belgeyi açıkça işleyin.</p></div>
            <ImportStatusBadge status={uploaded.status} />
          </div>
          {uploaded.status === "UPLOADED" || uploaded.status === "FAILED" ? (
            <button
              type="button"
              onClick={processDocument}
              disabled={busy !== null}
              className="mt-5 inline-flex items-center gap-2 rounded-xl bg-slate-900 px-4 py-3 text-sm font-semibold text-white hover:bg-slate-800 disabled:opacity-50"
            >
              {busy === "process" && <LoaderCircle className="animate-spin" size={18} aria-hidden="true" />}
              {busy === "process" ? "Belge işleniyor" : "Belgeyi İşle"}
            </button>
          ) : (
            <Link to={`/imports/${uploaded.id}`} className="mt-5 inline-flex rounded-xl bg-teal-600 px-4 py-3 text-sm font-semibold text-white hover:bg-teal-700">
              İncelemeye Devam Et
            </Link>
          )}
        </div>
      )}
    </section>
  );
}
