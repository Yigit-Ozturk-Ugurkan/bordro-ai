import { useState, type FormEvent } from "react";
import { ArrowRight, Eye, EyeOff, LockKeyhole, Mail } from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";
import { BrandMark } from "../components/BrandMark";

export function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await login(email, password);
      const requestedPath = (location.state as { from?: { pathname?: string } } | null)
        ?.from?.pathname;
      navigate(requestedPath || "/dashboard", { replace: true });
    } catch {
      setError("E-posta veya şifre hatalı. Bilgilerinizi kontrol edin.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="grid min-h-screen bg-white lg:grid-cols-[0.95fr_1.05fr]">
      <section className="relative hidden overflow-hidden bg-slate-950 p-12 lg:flex lg:flex-col">
        <div className="absolute -right-28 top-16 size-96 rounded-full border border-teal-400/15" />
        <div className="absolute -right-8 top-36 size-64 rounded-full border border-teal-400/10" />
        <BrandMark />

        <div className="relative my-auto max-w-xl">
          <p className="mb-5 text-xs font-bold uppercase tracking-[0.26em] text-teal-300">
            Bordronuz, net ve anlaşılır
          </p>
          <h1 className="text-5xl font-bold leading-[1.08] tracking-tight text-white">
            Finansal bilgilerinize güvenli erişim.
          </h1>
          <p className="mt-6 max-w-lg text-base leading-7 text-slate-400">
            Net ücretinizi, kesintilerinizi ve vergi durumunuzu tek bir yerde,
            dönem dönem inceleyin.
          </p>

          <div className="mt-10 grid max-w-lg grid-cols-3 gap-3">
            {["Bordro özeti", "Vergi durumu", "Dönem karşılaştırma"].map(
              (label, index) => (
                <div key={label} className="border-l border-white/15 pl-4">
                  <span className="text-xs font-semibold text-teal-300">0{index + 1}</span>
                  <p className="mt-1 text-sm leading-5 text-slate-300">{label}</p>
                </div>
              ),
            )}
          </div>
        </div>

        <p className="text-xs text-slate-600">Bordro AI · Çalışan Self Servis</p>
      </section>

      <section className="flex min-h-screen items-center justify-center px-5 py-10 sm:px-10">
        <div className="w-full max-w-md">
          <div className="mb-10 lg:hidden">
            <div className="inline-flex rounded-xl bg-slate-950 p-2.5">
              <BrandMark compact />
            </div>
            <p className="mt-3 text-lg font-bold text-slate-950">Bordro AI</p>
          </div>

          <div>
            <p className="text-sm font-semibold text-teal-700">Tekrar hoş geldiniz</p>
            <h2 className="mt-2 text-3xl font-bold tracking-tight text-slate-950">
              Hesabınıza giriş yapın
            </h2>
            <p className="mt-3 text-sm leading-6 text-slate-500">
              Bordro ve vergi bilgilerinizi görüntülemek için kurum hesabınızı kullanın.
            </p>
          </div>

          <form className="mt-9 space-y-5" onSubmit={handleSubmit}>
            <label className="block">
              <span className="text-sm font-semibold text-slate-700">E-posta</span>
              <span className="relative mt-2 block">
                <Mail className="absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400" size={18} />
                <input
                  type="email"
                  autoComplete="email"
                  required
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  placeholder="ornek@kurum.com"
                  className="h-12 w-full rounded-xl border border-slate-200 bg-slate-50 pl-11 pr-4 text-sm text-slate-900 outline-none placeholder:text-slate-400 focus:border-teal-500 focus:bg-white"
                />
              </span>
            </label>

            <label className="block">
              <span className="text-sm font-semibold text-slate-700">Şifre</span>
              <span className="relative mt-2 block">
                <LockKeyhole className="absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400" size={18} />
                <input
                  type={showPassword ? "text" : "password"}
                  autoComplete="current-password"
                  required
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  className="h-12 w-full rounded-xl border border-slate-200 bg-slate-50 pl-11 pr-12 text-sm text-slate-900 outline-none focus:border-teal-500 focus:bg-white"
                />
                <button
                  type="button"
                  aria-label={showPassword ? "Şifreyi gizle" : "Şifreyi göster"}
                  onClick={() => setShowPassword((current) => !current)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 rounded-lg p-1 text-slate-400 hover:text-slate-700"
                >
                  {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                </button>
              </span>
            </label>

            {error && (
              <p className="rounded-xl border border-rose-100 bg-rose-50 px-4 py-3 text-sm text-rose-700" role="alert">
                {error}
              </p>
            )}

            <button
              type="submit"
              disabled={loading}
              className="flex h-12 w-full items-center justify-center gap-2 rounded-xl bg-slate-950 text-sm font-bold text-white shadow-lg shadow-slate-950/10 hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {loading ? "Giriş yapılıyor…" : "Giriş yap"}
              {!loading && <ArrowRight size={18} aria-hidden="true" />}
            </button>
          </form>

          <p className="mt-8 text-center text-xs leading-5 text-slate-400">
            Yenileme oturumunuz güvenli, HTTP-only bir tanımlama bilgisiyle korunur.
          </p>
        </div>
      </section>
    </main>
  );
}
