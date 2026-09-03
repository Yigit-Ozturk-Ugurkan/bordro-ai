import { Link } from "react-router-dom";

export function NotFoundPage() {
  return (
    <main className="grid min-h-screen place-items-center bg-slate-950 px-6 text-center text-white">
      <div>
        <p className="text-sm font-bold tracking-widest text-teal-300">404</p>
        <h1 className="mt-3 text-3xl font-bold">Sayfa bulunamadı</h1>
        <Link
          to="/dashboard"
          className="mt-6 inline-block rounded-xl bg-white px-4 py-2.5 text-sm font-semibold text-slate-900"
        >
          Genel bakışa dön
        </Link>
      </div>
    </main>
  );
}
