# Bordro AI
### Belge İşleme, İnsan İncelemesi ve Bordro Görüntüleme

Bordro AI; bordro belgelerinin içe aktarılması, çıkarılan alanların eşleştirilmesi, kullanıcı tarafından incelenmesi ve onaylı verilerin bordro kayıtlarına aktarılması için geliştirilen bir web uygulamasıdır.

Çalışanlar kendi bordrolarını, vergi durumlarını ve önceki dönemle karşılaştırmalarını görüntüleyebilir. Yetkili kullanıcılar ise organizasyonları kapsamında belge işleme ve inceleme akışlarını yönetebilir.

## Öne Çıkan Özellikler

- **Belge içe aktarma:** Dosya doğrulama, kalıcı saklama ve aynı organizasyon içindeki birebir tekrarların tespiti.
- **OCR entegrasyonu:** Ayrı çalışan General Reader servisi üzerinden belge alanlarının çıkarılması.
- **Alan eşleştirme:** Kaynak alanların kontrollü bordro alanlarıyla eşleştirilmesi ve tür dönüşümleri.
- **İnsan incelemesi:** Gerekçeli düzeltmeler, geri alma işlemleri ve düzeltme geçmişi.
- **Sürümlü anlık görüntüler:** İncelenen verilerin değiştirilemez snapshot kayıtlarıyla korunması.
- **Bordroya aktarım:** Onaylı skaler ve detay verilerinin bordro sürümüne aktarılması.
- **Bordro görüntüleme:** Kazanç, kesinti, devamsızlık ve dönem karşılaştırma ekranları.
- **Yetkilendirme:** Organizasyon ve rol bazlı erişim; çalışanların kendi kayıtlarına erişmesi.

## Temel İşleyiş

1. Yetkili kullanıcı bordro belgesini yükler.
2. Backend dosyayı doğrular ve saklar.
3. General Reader, belge alanlarını çıkarır.
4. Alanlar bordro kavramlarıyla eşleştirilir.
5. Kullanıcı eksik veya sorunlu alanları inceler ve düzeltir.
6. İncelenen veriler sürümlü bir anlık görüntüye dönüştürülür.
7. Doğrulama ve onay aşamalarından geçen veriler bordro kayıtlarına aktarılır.
8. Çalışan ve yetkili kullanıcılar bordroyu ilgili ekranlardan görüntüler.

Belgeden çıkarılan değerler doğrudan onaylı bordro verisi sayılmaz. Çıkarım, inceleme, onay ve bordroya aktarım ayrı aşamalardır.

## Teknolojiler

| Katman | Teknolojiler |
| --- | --- |
| Backend | Python, FastAPI, Pydantic |
| Veri erişimi | SQLAlchemy, psycopg |
| Veritabanı | PostgreSQL |
| Şema yönetimi | Alembic |
| Frontend | React, TypeScript, Vite |
| Kimlik doğrulama | JWT, Argon2id |
| Servis entegrasyonu | HTTP, HMAC-SHA256 |
| Backend testleri | pytest |

## Mimari

Backend, route → service → repository → database katmanlarını izler.

General Reader ayrı bir belge çıkarım servisidir. Bordro AI bu servise imzalı HTTP istekleri gönderir ve dönen yanıtı kendi veri sözleşmesine göre doğrular. Kaynak dosyalar Bordro AI tarafından yönetilir.

Frontend finansal hesaplamaları yeniden üretmek yerine backend tarafından sağlanan değerleri ve dönem farklarını gösterir.

## Finansal Veri Yaklaşımı

- Parasal işlemlerde Decimal ve PostgreSQL NUMERIC türleri kullanılır.
- Ondalıklı değerler API yanıtlarında metin olarak taşınır.
- Vergi hesaplama kuralları veritabanındaki kural setleriyle yönetilir.
- Dönem karşılaştırmaları sayısal farkları gösterir; değişimin nedenine ilişkin otomatik bir açıklama üretmez.

## Geliştirme Ortamı

Yerel geliştirme için aşağıdaki bileşenler gerekir:

- Python ve backend bağımlılıkları
- PostgreSQL; ilk MVP test ortamında PostgreSQL 16 kullanılmıştır
- Node.js ve npm
- Belge çıkarım akışı için General Reader entegrasyon servisi

Backend ve frontend ayar örnekleri ilgili klasörlerdeki `.env.example` dosyalarında bulunur. Gerçek şifreler ve servis anahtarları kaynak koduna eklenmemelidir.

Frontend kurulum bilgileri için [frontend README](frontend/README.md) dosyasına bakın.

## Proje Yapısı

| Konum | İçerik |
| --- | --- |
| `backend/app/api/` | API uçları |
| `backend/app/services/` | İş akışları ve servisler |
| `backend/app/repositories/` | Veri erişimi |
| `backend/app/models/` | Veritabanı modelleri |
| `backend/app/integrations/` | Harici servis bağlantıları |
| `backend/app/storage/` | Belge saklama |
| `backend/alembic/` | Veritabanı geçişleri |
| `backend/tests/` | Birim ve entegrasyon testleri |
| `frontend/src/` | Kullanıcı arayüzü |
| `docs/` | Teknik dokümanlar |

## Teknik Dokümanlar

- [Kimlik doğrulama ve erişim](docs/AUTH_SECURITY.md)
- [Belge içe aktarma](docs/PAYROLL_IMPORT_V21A.md)
- [Alan eşleştirme](docs/PAYROLL_ADAPTER_V21B.md)
- [İnsan incelemesi ve snapshot](docs/PAYROLL_REVIEW_V21C.md)
- [Doğrulama](docs/PAYROLL_VALIDATION_V21D.md)
- [Onay akışı](docs/PAYROLL_APPROVAL_V21E.md)
- [Bordroya aktarım](docs/PAYROLL_MATERIALIZATION_V21F.md)
- [Detay verilerinin hazırlanması](docs/PAYROLL_DETAIL_STAGING_V21I.md)
- [Detay alanlarının eşleştirilmesi](docs/PAYROLL_DETAIL_MAPPING_V21J.md)
- [Vergi kayıtlarının senkronizasyonu](docs/PAYROLL_TAX_SYNC_V21G.md)
- [Kümülatif verginin yeniden oluşturulması](docs/PAYROLL_TAX_REBUILD_V21H.md)
- [Ürün entegrasyonu](docs/PAYROLL_PRODUCT_INTEGRATION_V22B.md)

Dokümanlardaki sürüm numaraları geliştirme aşamalarını belirtir. Eski aşamalarda belirtilen kapsam sınırları sonraki aşamalarda değişmiş olabilir.

## Mevcut Durum ve Sınırlar

Proje geliştirme aşamasındadır. Ürün entegrasyonu notlarında gerçek bir bordro belgesiyle uçtan uca yükleme ve işleme testi, örnek belge bulunamadığı için tamamlanmamış olarak kayıtlıdır.

Eski MVP raporundaki test sayıları güncel sürümün test sonucu olarak değerlendirilmemelidir. Güncel başarı durumu, mevcut kod üzerinde testler yeniden çalıştırılarak doğrulanmalıdır.

İnternete açık üretim kullanımı öncesinde kimlik doğrulama dokümanında belirtilen hız sınırlama, oturum/token yönetimi ve güvenlik olaylarının kaydı gibi takip işleri tamamlanmalıdır.
