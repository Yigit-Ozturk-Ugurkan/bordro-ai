import { AlertCircle, FileQuestion, LoaderCircle } from "lucide-react";

export function PageLoader({ label = "Bilgiler yükleniyor" }: { label?: string }) {
  return (
    <div className="grid min-h-[340px] place-items-center" role="status">
      <div className="text-center text-slate-500">
        <LoaderCircle className="mx-auto mb-3 animate-spin text-teal-600" size={28} />
        <p className="text-sm font-medium">{label}</p>
      </div>
    </div>
  );
}

export function ErrorState({
  title = "Bilgiler alınamadı",
  message = "Lütfen bağlantınızı kontrol edip yeniden deneyin.",
  onRetry,
}: {
  title?: string;
  message?: string;
  onRetry?: () => void;
}) {
  return (
    <div className="rounded-2xl border border-rose-100 bg-white px-6 py-12 text-center shadow-sm" role="alert">
      <AlertCircle className="mx-auto mb-3 text-rose-500" size={30} />
      <h2 className="font-semibold text-slate-900">{title}</h2>
      <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-slate-500">{message}</p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-5 rounded-xl bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white hover:bg-slate-800"
        >
          Yeniden dene
        </button>
      )}
    </div>
  );
}

export function EmptyState({
  title,
  message,
}: {
  title: string;
  message: string;
}) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white px-6 py-14 text-center shadow-sm">
      <FileQuestion className="mx-auto mb-3 text-slate-400" size={30} />
      <h2 className="font-semibold text-slate-900">{title}</h2>
      <p className="mt-2 text-sm text-slate-500">{message}</p>
    </div>
  );
}
