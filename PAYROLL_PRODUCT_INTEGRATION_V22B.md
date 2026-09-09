# Bordro Ürün Entegrasyonu V2.2B

## Akış

Belge içe aktarma çalışma alanı, onaylı skaler kanıtı güncel ve yetkili bir
`PayrollVersion` kaydına dönüştürür. Ayrı detay materyalizasyonu, onaylı detay
anlık görüntüsünden aynı bordro sürümüne `PayrollEarning`, `PayrollDeduction`
ve `PayrollAbsence` kayıtlarını ekler.

Çalışanın `/payrolls/:year/:month` rotası `/api/v1/me` sözleşmelerini kullanır.
Yetkili yönetici, İK yöneticisi ve denetçi için
`/employees/:employeeId/payrolls/:year/:month` rotası aynı görünümü mevcut
organizasyon-kapsamlı `/api/v1/employees/{employee_id}` sözleşmeleriyle açar.
Materyalizasyon sonucundaki yetkili çalışan kimliği yönetici rotasını oluşturur;
tarayıcı çalışan kimliği türetmez.

Her iki görünüm de güncel bordro sürümündeki skaler değerleri ve materyalize
detay satırlarını gösterir. Vergi durumu ilgili self-service veya
organizasyon-kapsamlı vergi-durumu sözleşmesinden alınır. Önceki dönem
karşılaştırması; net ücret, toplam kazanç, toplam kesinti ve gelir vergisi için
sunucunun sağladığı `previous`, `current`, `delta` ve `delta_percent` dizelerini
gösterir. Tarayıcı finansal fark hesaplamaz.

## Gerçek bordro E2E sonucu

BLOCKED: REAL_E2E_SAMPLE_PATH_REQUIRED

Çalışma alanında veya kullanılabilir yerel ekler içinde okunabilir gerçek bordro
belgesi bulunamadığından canlı yükleme akışı başlatılmadı. Örnek belge, kişisel
veri veya çıkarılmış bordro değeri bu belgeye ya da kaynak koduna eklenmedi.
