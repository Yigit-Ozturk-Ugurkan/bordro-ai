import { ApiError } from "../api/client";

export interface FriendlyError {
  title: string;
  message: string;
}

export function friendlyError(error: unknown): FriendlyError {
  if (error instanceof ApiError) {
    if (error.status === 403) {
      return {
        title: "Erişim izniniz yok",
        message: "Bu bordro bilgisini görüntüleme yetkiniz bulunmuyor.",
      };
    }
    if (error.status === 404) {
      return {
        title: "Kayıt bulunamadı",
        message: "İstenen bordro dönemi bulunamadı veya artık kullanılamıyor.",
      };
    }
  }
  return {
    title: "Bilgiler alınamadı",
    message: "Sunucuya şu anda ulaşılamıyor. Lütfen biraz sonra yeniden deneyin.",
  };
}
