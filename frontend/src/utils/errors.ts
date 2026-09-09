import { ApiError } from "../api/client";

export interface FriendlyError {
  title: string;
  message: string;
}

export function friendlyError(error: unknown): FriendlyError {
  if (error instanceof ApiError) {
    if (error.status === 401) {
      return {
        title: "Oturum süresi doldu",
        message: "Devam etmek için yeniden giriş yapın.",
      };
    }
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
    if (error.status === 409) {
      return {
        title: "Veriler güncellendi",
        message: "Bu inceleme başka bir işlemle güncellendi. Güncel veriler yeniden yüklendi.",
      };
    }
    if (error.status === 422) {
      return {
        title: "İnceleme henüz tamamlanamadı",
        message: "Eksik veya çözümlenmemiş alanları kontrol edip yeniden deneyin.",
      };
    }
    if (error.status === 413) {
      return { title: "Dosya çok büyük", message: "Dosya yükleme sınırını aşıyor." };
    }
    if (error.status === 415) {
      return { title: "Dosya türü desteklenmiyor", message: "Desteklenen bir bordro belgesi seçin." };
    }
  }
  return {
    title: "Bilgiler alınamadı",
    message: "Sunucuya şu anda ulaşılamıyor. Lütfen biraz sonra yeniden deneyin.",
  };
}
