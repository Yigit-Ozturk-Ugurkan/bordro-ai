import { ArrowRight, Plus } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { listPayrollImports } from "../api/payrollImports";
import type { PayrollImportList } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { EmptyState, ErrorState, PageLoader } from "../components/AsyncState";
import { ImportStatusBadge } from "../components/ImportStatusBadge";
import { friendlyError, type FriendlyError } from "../utils/errors";
import { formatDateTime, formatFileSize } from "../utils/formatters";

export function PayrollImportsPage() {
  const { user } = useAuth();
  const [data, setData] = useState<PayrollImportList | null>(null);
  const [error, setError] = useState<FriendlyError | null>(null);
  const canUpload = user?.roles.some((role) => role === "PAYROLL_ADMIN" || role === "HR_ADMIN");

  const load = useCallback(() => {
    setError(null);
    listPayrollImports().then(setData).catch((reason: unknown) => setError(friendlyError(reason)));
  }, []);

  useEffect(load, [load]);

  if (!data && !error) return <PageLoader label="İçe aktarımlar yükleniyor" />;
  if (error) return <ErrorState {...error} onRetry={load} />;

  return (
    <section className="space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-sm font-semibold text-teal-700">Belge iş akışı</p>
          <h2 className="mt-1 text-2xl font-bold tracking-tight text-slate-950">Bordro İçe Aktarımları</h2>
          <p className="mt-2 max-w-2xl text-sm text-slate-500">
            Yüklenen bordro belgelerini inceleyin, doğrulayın ve sisteme aktarın.
          </p>
        </div>
        {canUpload && (
          <Link
            to="/imports/upload"
            className="inline-flex items-center justify-center gap-2 rounded-xl bg-teal-600 px-4 py-3 text-sm font-semibold text-white hover:bg-teal-700"
          >
            <Plus size={18} aria-hidden="true" /> Yeni Bordro Yükle
          </Link>
        )}
      </div>

      {data?.count === 0 ? (
        <EmptyState
          title="Henüz bordro içe aktarımı yok"
          message="İlk bordro belgesini yükleyerek inceleme sürecini başlatabilirsiniz."
        />
      ) : (
        <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-slate-200 text-left text-sm">
              <thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-5 py-3">Belge</th>
                  <th className="px-5 py-3">Yükleme tarihi</th>
                  <th className="px-5 py-3">Boyut</th>
                  <th className="px-5 py-3">Durum</th>
                  <th className="px-5 py-3 text-right">İşlem</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {data?.items.map((item) => (
                  <tr key={item.id} className="hover:bg-slate-50/70">
                    <td className="px-5 py-4">
                      <p className="max-w-sm truncate font-semibold text-slate-900">{item.original_filename}</p>
                      <p className="mt-1 text-xs text-slate-500">İşleme denemesi: {item.processing_attempt}</p>
                    </td>
                    <td className="whitespace-nowrap px-5 py-4 text-slate-600">{formatDateTime(item.created_at)}</td>
                    <td className="whitespace-nowrap px-5 py-4 text-slate-600">{formatFileSize(item.size_bytes)}</td>
                    <td className="px-5 py-4"><ImportStatusBadge status={item.status} /></td>
                    <td className="px-5 py-4 text-right">
                      <Link
                        to={`/imports/${item.id}`}
                        className="inline-flex items-center gap-1.5 font-semibold text-teal-700 hover:text-teal-800"
                      >
                        {item.status === "UPLOADED" ? "İncelemeye devam et" : "Görüntüle"}
                        <ArrowRight size={16} aria-hidden="true" />
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  );
}
