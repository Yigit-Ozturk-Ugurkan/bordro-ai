const labels: Record<string, string> = {
  UPLOADED: "Yüklendi",
  PROCESSING: "İşleniyor",
  EXTRACTED: "Çıkarım tamamlandı",
  REVIEW_REQUIRED: "İnceleme gerekli",
  FAILED: "Başarısız",
  REJECTED: "Reddedildi",
  IN_PROGRESS: "İnceleniyor",
  READY_FOR_SNAPSHOT: "Tamamlanmaya hazır",
  SNAPSHOTTED: "İnceleme tamamlandı",
  MAPPED: "Eşlendi",
  UNMAPPED: "Eşlenmedi",
  AMBIGUOUS: "Belirsiz",
  PARSE_FAILED: "Değer okunamadı",
  PENDING: "Bekliyor",
  RESOLVED: "Çözüldü",
  STALE: "Güncelliğini yitirdi",
  NOT_DECIDED: "Karar bekliyor",
  APPROVED: "Onaylandı",
  BLOCKING: "Engelleyici",
  ERROR: "Hata",
  WARNING: "Uyarı",
  INFO: "Bilgi",
  EARNING: "Kazanç",
  DEDUCTION: "Kesinti",
  ABSENCE: "Devamsızlık",
};

const colors: Record<string, string> = {
  APPROVED: "border-emerald-200 bg-emerald-50 text-emerald-700",
  EXTRACTED: "border-emerald-200 bg-emerald-50 text-emerald-700",
  SNAPSHOTTED: "border-emerald-200 bg-emerald-50 text-emerald-700",
  RESOLVED: "border-emerald-200 bg-emerald-50 text-emerald-700",
  MAPPED: "border-sky-200 bg-sky-50 text-sky-700",
  READY_FOR_SNAPSHOT: "border-sky-200 bg-sky-50 text-sky-700",
  EARNING: "border-teal-200 bg-teal-50 text-teal-700",
  DEDUCTION: "border-violet-200 bg-violet-50 text-violet-700",
  ABSENCE: "border-amber-200 bg-amber-50 text-amber-800",
  WARNING: "border-amber-200 bg-amber-50 text-amber-800",
  REVIEW_REQUIRED: "border-amber-200 bg-amber-50 text-amber-800",
  AMBIGUOUS: "border-amber-200 bg-amber-50 text-amber-800",
  FAILED: "border-rose-200 bg-rose-50 text-rose-700",
  REJECTED: "border-rose-200 bg-rose-50 text-rose-700",
  ERROR: "border-rose-200 bg-rose-50 text-rose-700",
  BLOCKING: "border-rose-200 bg-rose-50 text-rose-700",
  PARSE_FAILED: "border-rose-200 bg-rose-50 text-rose-700",
  STALE: "border-rose-200 bg-rose-50 text-rose-700",
};

export function statusLabel(status: string): string {
  return labels[status] ?? status;
}

export function ImportStatusBadge({ status }: { status: string }) {
  return (
    <span
      className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold ${
        colors[status] ?? "border-slate-200 bg-slate-50 text-slate-600"
      }`}
    >
      {statusLabel(status)}
    </span>
  );
}
