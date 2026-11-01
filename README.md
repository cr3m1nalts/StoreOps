# StoreOps — Telefon Dükkanı Takip

Küçük telefon dükkanları için **tek bilgisayarda çalışan** mağaza takip uygulaması. İnternet yalnızca dolar kuru ve yeni sürüm denetimi için gerekir.
Teknik servis, aksesuar ve cihaz alım-satımı, stok, parçacılar, veresiye ve gelir/gider raporları tek ekranda.

## Özellikler

- **Ana Ekran** — büyük saat, "Hayırlı İşler Bol Kazançlar" ve sakin bir animasyon. Dükkanda iş yokken açık kalsın diye.
- **Teknik Servis** — cihaz modeli, müşteri adı/telefonu, kilit bilgisi (PIN, şifre veya **çizilebilir 3x3 desen**) ve şikayet kaydı.
  Durumlar renkli: Alındı → Tamirde → Hazır → **Teslim** (ücret otomatik gelire yazılır) veya **İade** (gelir yazılmaz, neden sorulur).
  Kilit bilgisi teslimde/iadede silinir (KVKK).
- **Ürün Satış** — Stoğa girilmiş ürünler kategoriye göre seçilip satış fiyatıyla eklenir. Adet seçip **Sat**'a basınca tutar otomatik gelire yazılır.
- **Gelir / Gider** — her gün kendi sayfası; gece 12'de kendiliğinden yeni güne geçer. Elle gelir/gider eklenir,
  önceki günlere ‹ › oklarıyla bakılır. Gelir, gider ve net toplam üstte.
- **Veresiye** — kişi, telefon ve tutar kaydı. **Borç ödendi** düğmesi tutarı gelire yazar. Borçlu müşteri yeniden cihaz getirirse Teknik Servis ekranı telefon veya ada göre uyarır.
- **Stok girişi** — alınan malzemenin kaydı (₺ veya $); her kayıt otomatik gidere yazılır. Elde kalan adet tutulmaz, satış stoktan düşmez.
- **Cihaz** — alışta satıcı adı ve T.C. no, marka, model, depolama, cihaz ve kozmetik durumu, yurtiçi/yurtdışı, iPhone'da pil sağlığı kaydedilir; tutar gidere yazılır. Yalnızca kayıtlı cihazlar satılabilir; satış tutarı gelire yazılır.
- **Parça tedarikçileri** — istediğiniz kadar parçacı ekleyin; her birinin kendi haftalık alım tablosu olur, alımlar gidere yazılır.
- **Yeni sürüm uyarısı** — GitHub'da yeni sürüm çıkınca uygulama uyarır; yeni sürüm ilk açıldığında değişiklikleri gösterir.
- **Dolar kuru** — TCMB'nin günlük döviz satış kuru otomatik alınır (saatte bir kontrol). İnternet yoksa son kur kullanılır veya elle girilir.
- **Parça maliyeti** — servis kaydına $ olarak girilen maliyet o günün kuruyla ₺'ye çevrilip gidere yazılır.
- **Raporlar** — Gelir / Gider ekranında haftalık ve aylık toplamlar, günlük döküm ve alınan parçalar.
- **3 tema** — Normal, Koyu, Retro (yeşil terminal). Sağ üstten seçilir.
- **Değiştirilebilir ad** — sol üstteki ada tıklayıp dükkanınızın adını yazın.
- **Yedek** — sağ üstteki "Yedek indir" veritabanının kopyasını indirir.

## Kullanım

[Releases](../../releases) sayfasından `StoreOps.exe`'yi indirin, Masaüstünde bir klasöre koyup çift tıklayın.
Python veya kurulum gerekmez; uygulama kendi penceresinde açılır, pencere kapanınca tamamen kapanır.

- Veriler `.exe`'nin yanındaki `dukkan.db` dosyasında durur. Yedek için bu dosyayı kopyalamanız yeterli.
- `.exe` imzasız olduğu için ilk açılışta Windows SmartScreen uyarı verebilir: **Ek bilgi → Yine de çalıştır**.
- `.exe`'yi "Program Files" gibi yazma izni olmayan bir klasöre koymayın.
- Windows 10/11 ve Microsoft Edge gerekir (Windows'ta hazır gelir).

## Geliştirme

Sadece Python 3 standart kütüphanesi kullanılır, ek paket yoktur.

| Dosya | Ne işe yarar |
|---|---|
| `server.py` | Yerel sunucu (yalnızca `127.0.0.1`), SQLite veritabanı, API ve TCMB kuru |
| `index.html` | Tüm arayüz (HTML + CSS + JavaScript, tek dosya) |
| `test_server.py` | Testler: `python -m unittest test_server` |
| `baslat.bat` | Python ile çalıştırır |
| `exe_yap.bat` | `dist\StoreOps.exe`'yi yeniden üretir (`pip install pyinstaller` gerekir) |

## Lisans

[MIT](LICENSE) — dilediğiniz gibi kullanabilir, değiştirebilir ve dağıtabilirsiniz.
