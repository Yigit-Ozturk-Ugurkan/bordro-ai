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

function formatDecimalString(value: string, minimumFractionDigits = 0): string {
  const match = value.trim().match(/^([+-]?)(\d+)(?:\.(\d+))?$/);
  if (!match) return value;
  const [, sign, rawInteger, rawFraction = ""] = match;
  const integer = rawInteger.replace(/^0+(?=\d)/, "").replace(/\B(?=(\d{3})+(?!\d))/g, ".");
  let fraction = rawFraction;
  while (fraction.length > minimumFractionDigits && fraction.endsWith("0")) {
    fraction = fraction.slice(0, -1);
  }
  fraction = fraction.padEnd(minimumFractionDigits, "0");
  const prefix = sign === "-" ? "-" : "";
  return `${prefix}${integer}${fraction ? `,${fraction}` : ""}`;
}

function rateAsPercentage(value: string): string {
  const match = value.trim().match(/^([+-]?)(\d+)(?:\.(\d+))?$/);
  if (!match) return value;
  const [, sign, integer, fraction = ""] = match;
  const digits = `${integer}${fraction}`.padEnd(integer.length + 2, "0");
  const decimalIndex = integer.length + 2;
  const scaledInteger = digits.slice(0, decimalIndex);
  const scaledFraction = digits.slice(decimalIndex);
  return `${sign}${scaledInteger}${scaledFraction ? `.${scaledFraction}` : ""}`;
}

export function formatMoney(value: string | null | undefined): string {
  if (value == null || value === "") return "—";
  return `${formatDecimalString(value, 2)} ₺`;
}

export function formatDays(value: string | null | undefined): string {
  if (value == null || value === "") return "—";
  return `${formatDecimalString(value)} gün`;
}

export function formatRate(value: string | null | undefined): string {
  if (value == null || value === "") return "—";
  return `${formatDecimalString(rateAsPercentage(value))}%`;
}

export function formatPercentage(value: string | null | undefined): string {
  if (value == null || value === "") return "—";
  return `${formatDecimalString(value)}%`;
}

export function formatPeriod(year: number, month: number): string {
  return `${monthNames[month - 1]} ${year}`;
}

export function decimalSign(value: string | null | undefined): -1 | 0 | 1 {
  if (!value) return 0;
  const normalized = value.trim();
  const magnitude = normalized.replace(/^[+-]/, "").replace(/[.]/g, "");
  if (!/^\d+$/.test(magnitude) || /^0+$/.test(magnitude)) return 0;
  if (normalized.startsWith("-")) return -1;
  return 1;
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
