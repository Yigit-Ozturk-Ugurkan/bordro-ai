const moneyFormatter = new Intl.NumberFormat("tr-TR", {
  style: "currency",
  currency: "TRY",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const decimalFormatter = new Intl.NumberFormat("tr-TR", {
  minimumFractionDigits: 0,
  maximumFractionDigits: 2,
});

const percentFormatter = new Intl.NumberFormat("tr-TR", {
  style: "percent",
  minimumFractionDigits: 0,
  maximumFractionDigits: 2,
});

export const monthNames = [
  "Ocak",
  "Şubat",
  "Mart",
  "Nisan",
  "Mayıs",
  "Haziran",
  "Temmuz",
  "Ağustos",
  "Eylül",
  "Ekim",
  "Kasım",
  "Aralık",
];

export function formatMoney(value: string | null | undefined): string {
  if (value == null || value === "") return "—";
  return moneyFormatter.format(Number(value));
}

export function formatDays(value: string | null | undefined): string {
  if (value == null || value === "") return "—";
  return `${decimalFormatter.format(Number(value))} gün`;
}

export function formatRate(value: string | null | undefined): string {
  if (value == null || value === "") return "—";
  return percentFormatter.format(Number(value));
}

export function formatPercentage(value: string | null | undefined): string {
  if (value == null || value === "") return "—";
  return `${decimalFormatter.format(Number(value))}%`;
}

export function formatPeriod(year: number, month: number): string {
  return `${monthNames[month - 1]} ${year}`;
}

export function decimalSign(value: string | null | undefined): -1 | 0 | 1 {
  if (!value) return 0;
  const sign = Number(value);
  if (sign < 0) return -1;
  if (sign > 0) return 1;
  return 0;
}

export function roleLabel(role: string): string {
  const labels: Record<string, string> = {
    EMPLOYEE: "Çalışan",
    HR_ADMIN: "İK yöneticisi",
    PAYROLL_ADMIN: "Bordro yöneticisi",
    AUDITOR: "Denetçi",
    SYSTEM_ADMIN: "Sistem yöneticisi",
  };
  return labels[role] ?? role;
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat("tr-TR", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
