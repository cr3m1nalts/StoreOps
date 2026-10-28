# StoreOps — Telefon Dükkanı Takip

Küçük telefon dükkanları için **internetsiz, tek bilgisayarda çalışan** mağaza takip uygulaması.
Teknik servis kayıtları, aksesuar satışları ve günlük gelir/gider tek ekranda.

## Özellikler

- **Ana Ekran** — büyük saat, "Hayırlı İşler Bol Kazançlar" ve sakin bir animasyon. Dükkanda iş yokken açık kalsın diye.
- **Teknik Servis** — cihaz modeli, müşteri adı/telefonu, kilit bilgisi (PIN, şifre veya **çizilebilir 3x3 desen**) ve şikayet kaydı.
  Durumlar renkli: Alındı → Tamirde → Hazır → **Teslim** (ücret otomatik gelire yazılır) veya **İade** (gelir yazılmaz, neden sorulur).
  Kilit bilgisi teslimde/iadede silinir (KVKK).
- **Ürün Satış** — Şarj Kablosu, Şarj Aleti, Kılıf, Ekran Koruyucu, Diğer kategorilerine istediğiniz çeşidi ekleyin
  (ör. "2M TypeC-TypeC"). Adet seçip **Sat**'a basınca tutar otomatik gelire yazılır.
- **Gelir / Gider** — her gün kendi sayfası; gece 12'de kendiliğinden yeni güne geçer. Elle gelir/gider eklenir,
  önceki günlere ‹ › oklarıyla bakılır. Gelir, gider ve net toplam üstte.
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
| `server.py` | Yerel sunucu (yalnızca `127.0.0.1`), SQLite veritabanı ve API |
| `index.html` | Tüm arayüz (HTML + CSS + JavaScript, tek dosya) |
| `test_server.py` | Testler: `python -m unittest test_server` |
| `baslat.bat` | Python ile çalıştırır |
| `exe_yap.bat` | `dist\StoreOps.exe`'yi yeniden üretir (`pip install pyinstaller` gerekir) |

## Lisans

[MIT](LICENSE) — dilediğiniz gibi kullanabilir, değiştirebilir ve dağıtabilirsiniz.
