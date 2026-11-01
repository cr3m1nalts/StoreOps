import http.client
import io
import json
import os
import shutil
import sqlite3
import tempfile
import threading
import unittest
import zipfile
from http.server import ThreadingHTTPServer

import server
from server import ac, islem, kur_coz, rapor_araligi, surum_no


class Test(unittest.TestCase):
    def setUp(self):
        self.db = ac(":memory:")

    def gun(self):
        return islem(self.db, "gun", {})

    def test_urun_yalnizca_stoktan_secilir(self):
        ekle = {"kategori": "Kılıf", "ad": "iPhone 13", "fiyat": "150"}
        with self.assertRaises(ValueError):
            islem(self.db, "urun_ekle", ekle)
        islem(self.db, "stok_ekle", {"kategori": "Kılıf", "ad": "iPhone 13", "adet": "2", "birim_maliyet": "1"})
        islem(self.db, "stok_ekle", {"kategori": "Kılıf", "ad": "iPhone 13", "adet": "5", "birim_maliyet": "1"})
        islem(self.db, "stok_ekle", {"kategori": "Diğer", "ad": "3 x Paket", "adet": "1", "birim_maliyet": "1"})
        self.assertEqual(islem(self.db, "stok_urunleri", {}),
                         [{"kategori": "Diğer", "ad": "3 x Paket"}, {"kategori": "Kılıf", "ad": "iPhone 13"}])
        with self.assertRaises(ValueError):  # başka kategorideki aynı ad kabul edilmez
            islem(self.db, "urun_ekle", {**ekle, "kategori": "Diğer"})
        islem(self.db, "urun_ekle", ekle)
        self.assertEqual(len(islem(self.db, "urun_listele", {})), 1)

    def test_tedarikci_kendi_tablosu_haftalik(self):
        islem(self.db, "tedarikci_ekle", {"ad": "Ahmet Parça"})
        islem(self.db, "tedarikci_ekle", {"ad": "Veli GSM"})
        islem(self.db, "tedarikci_alim", {"id": 1, "ad": "iPhone 11 Ekran", "adet": "2", "birim_maliyet": "500"})
        islem(self.db, "tedarikci_alim", {"id": 2, "ad": "Batarya", "adet": "1", "birim_maliyet": "100"})
        self.assertEqual(self.gun()["gider"], 1100)
        r = islem(self.db, "tedarikci_kayit", {"id": 1})
        self.assertEqual((r["toplam"], len(r["kayitlar"]), r["kayitlar"][0]["aciklama"]),
                         (1000, 1, "Parça (Ahmet Parça): 2 x iPhone 11 Ekran"))
        self.assertEqual(islem(self.db, "tedarikci_kayit", {"id": 1, "tarih": "2000-01-05"})["kayitlar"], [])
        self.assertEqual(islem(self.db, "rapor", {"tur": "hafta"})["parca_toplam"], 1100)
        self.assertEqual(islem(self.db, "stok_urunleri", {}), [])  # parçacı alımı ürün listesine girmez
        with self.assertRaises(ValueError):  # kaydı olan parçacı silinemez
            islem(self.db, "tedarikci_sil", {"id": 1})
        islem(self.db, "hareket_sil", {"id": r["kayitlar"][0]["id"]})
        islem(self.db, "tedarikci_sil", {"id": 1})
        with self.assertRaises(ValueError):
            islem(self.db, "tedarikci_alim", {"id": 1, "ad": "x", "adet": "1", "birim_maliyet": "1"})

    CIHAZ = {"satici_ad": "Ali Veli", "satici_tc": "10000000146", "durum": "İkinci El", "marka": "Samsung", "model": "S21",
             "depolama": "128 GB", "kozmetik": "İyi", "mensei": "Yurtiçi", "alis_fiyat": "10000"}

    def test_cihaz_alis_gidere_satis_gelire(self):
        islem(self.db, "cihaz_al", self.CIHAZ)
        self.assertEqual(self.gun()["gider"], 10000)
        c = islem(self.db, "cihaz_listele", {})[0]
        self.assertIsNone(c["pil_sagligi"])
        self.assertNotIn("10000000146", self.gun()["kayitlar"][0]["aciklama"])  # T.C. no gelir/gider listesine düşmez
        with self.assertRaises(ValueError):  # kayıtlı olmayan cihaz satılamaz
            islem(self.db, "cihaz_sat", {"id": 99, "fiyat": "1"})
        islem(self.db, "cihaz_sat", {"id": 1, "fiyat": "12500"})
        self.assertEqual(self.gun()["gelir"], 12500)
        with self.assertRaises(ValueError):  # iki kez satılamaz
            islem(self.db, "cihaz_sat", {"id": 1, "fiyat": "12500"})
        self.assertEqual(self.gun()["gelir"], 12500)
        with self.assertRaises(ValueError):  # satılmış cihazın alışı silinemez
            islem(self.db, "cihaz_sil", {"id": 1})
        kayitlar = self.gun()["kayitlar"]
        with self.assertRaises(ValueError):
            islem(self.db, "hareket_sil", {"id": kayitlar[1]["id"]})
        # satış geri alınınca cihaz yeniden satılabilir; sonra alış da silinebilir
        islem(self.db, "hareket_sil", {"id": kayitlar[0]["id"]})
        self.assertIsNone(islem(self.db, "cihaz_listele", {})[0]["satis_tarih"])
        islem(self.db, "hareket_sil", {"id": kayitlar[1]["id"]})
        self.assertEqual((islem(self.db, "cihaz_listele", {}), self.gun()["gider"]), ([], 0))

    def test_cihaz_dogrulama(self):
        for yanlis in ("", "12345678901", "00000000146", "1000000014", "10000000147"):
            with self.assertRaises(ValueError):
                islem(self.db, "cihaz_al", {**self.CIHAZ, "satici_tc": yanlis})
        with self.assertRaises(ValueError):
            islem(self.db, "cihaz_al", {**self.CIHAZ, "mensei": "Mars"})
        iphone = {**self.CIHAZ, "marka": "Apple", "model": "iPhone 13"}
        for pil in ("", "0", "101"):  # iPhone'da pil sağlığı zorunlu
            with self.assertRaises(ValueError):
                islem(self.db, "cihaz_al", {**iphone, "pil_sagligi": pil})
        self.assertEqual((islem(self.db, "cihaz_listele", {}), self.gun()["gider"]), ([], 0))
        islem(self.db, "cihaz_al", {**self.CIHAZ, "marka": "APPLE", "model": "İPHONE 13", "pil_sagligi": "87"})
        self.assertEqual(islem(self.db, "cihaz_listele", {})[0]["pil_sagligi"], 87)

    def test_surum_karsilastirma_ve_notlar(self):
        self.assertGreater(surum_no("v1.3"), surum_no("1.2"))
        self.assertGreater(surum_no("v1.10"), surum_no("v1.9"))
        self.assertEqual(surum_no("v1.2.0"), surum_no("1.2"))
        self.assertEqual(surum_no("deneme"), ())
        server.GUNCELLEME.update(yeni=None, notlar="v1.2 notları")
        self.addCleanup(server.GUNCELLEME.update, yeni=None, notlar=None)
        self.assertEqual(islem(self.db, "guncelleme", {})["notlar"], "v1.2 notları")
        islem(self.db, "notlar_goruldu", {})
        self.assertIsNone(islem(self.db, "guncelleme", {})["notlar"])  # bir kez gösterilir

    def test_satis_gelire_yazilir(self):
        islem(self.db, "stok_ekle", {"kategori": "Şarj Kablosu", "ad": "2M TypeC-TypeC", "adet": "1", "birim_maliyet": "1"})
        islem(self.db, "urun_ekle", {"kategori": "Şarj Kablosu", "ad": "2M TypeC-TypeC", "fiyat": "150"})
        islem(self.db, "sat", {"urun_id": 1, "adet": 3})
        g = self.gun()
        self.assertEqual(g["gelir"], 450)
        self.assertEqual(g["kayitlar"][0]["aciklama"], "3 x 2M TypeC-TypeC")
        with self.assertRaises(ValueError):
            islem(self.db, "sat", {"urun_id": 1, "adet": 0})

    def servis(self):
        islem(self.db, "servis_ekle", {"cihaz_model": "iPhone 11", "musteri": "Ali Veli",
                                       "kilit_turu": "PIN", "kilit_degeri": "1234", "ucret": "500"})
        return 1

    def test_teslim_bir_kez_gelire_yazilir_ve_kilit_silinir(self):
        i = self.servis()
        islem(self.db, "servis_durum", {"id": i, "durum": "teslim", "ucret": "600"})
        self.assertEqual(self.gun()["gelir"], 600)
        s = islem(self.db, "servis_listele", {})[0]
        self.assertEqual((s["durum"], s["kilit_degeri"]), ("teslim", ""))
        with self.assertRaises(ValueError):
            islem(self.db, "servis_durum", {"id": i, "durum": "teslim"})
        self.assertEqual(self.gun()["gelir"], 600)

    def test_iade_gelir_yazmaz_neden_ister(self):
        i = self.servis()
        with self.assertRaises(ValueError):
            islem(self.db, "servis_durum", {"id": i, "durum": "iade", "neden": ""})
        islem(self.db, "servis_durum", {"id": i, "durum": "iade", "neden": "Müşteri vazgeçti"})
        self.assertEqual(self.gun()["gelir"], 0)

    def test_teslim_geliri_silinirse_servis_yeniden_acilir(self):
        i = self.servis()
        islem(self.db, "servis_durum", {"id": i, "durum": "teslim"})
        islem(self.db, "hareket_sil", {"id": self.gun()["kayitlar"][0]["id"]})
        self.assertEqual(islem(self.db, "servis_listele", {})[0]["durum"], "hazir")

    def test_gunluk_toplam(self):
        islem(self.db, "hareket_ekle", {"tur": "gelir", "tutar": "100.10", "aciklama": "x"})
        islem(self.db, "hareket_ekle", {"tur": "gider", "tutar": "30.05", "aciklama": "kira"})
        self.assertEqual(self.gun()["net"], 70.05)
        self.assertEqual(islem(self.db, "gun", {"tarih": "2000-01-01"})["kayitlar"], [])
        for kotu in ("-5", "inf", "nan"):
            with self.assertRaises(ValueError):
                islem(self.db, "hareket_ekle", {"tur": "gider", "tutar": kotu, "aciklama": "x"})


    def test_dukkan_adi_saklanir(self):
        islem(self.db, "ayar_yaz", {"anahtar": "dukkan_adi", "deger": "Ece İletişim"})
        self.assertEqual(islem(self.db, "ayar_oku", {}), {"dukkan_adi": "Ece İletişim"})
        with self.assertRaises(ValueError):
            islem(self.db, "ayar_yaz", {"anahtar": "baska", "deger": "x"})


    def kur_ayarla(self, kur="40"):
        islem(self.db, "kur_yaz", {"kur": kur})

    def test_veresiye_odeme_gelire_yazilir_bir_kez(self):
        islem(self.db, "veresiye_ekle", {"ad": "Ali Veli", "telefon": "0555 111 22 33", "tutar": "250"})
        self.assertEqual(islem(self.db, "veresiye_listele", {})["toplam"], 250)
        islem(self.db, "veresiye_ode", {"id": 1})
        self.assertEqual(self.gun()["gelir"], 250)
        self.assertEqual(islem(self.db, "veresiye_listele", {})["toplam"], 0)
        with self.assertRaises(ValueError):
            islem(self.db, "veresiye_ode", {"id": 1})
        self.assertEqual(self.gun()["gelir"], 250)
        with self.assertRaises(ValueError):
            islem(self.db, "veresiye_sil", {"id": 1})
        # ödeme kaydı silinirse borç geri gelir
        islem(self.db, "hareket_sil", {"id": self.gun()["kayitlar"][0]["id"]})
        self.assertEqual(islem(self.db, "veresiye_listele", {})["toplam"], 250)

    def test_borclu_musteri_uyarisi(self):
        islem(self.db, "veresiye_ekle", {"ad": "İBRAHİM  Işık", "telefon": "0555 111 22 33", "tutar": "100"})
        islem(self.db, "veresiye_ekle", {"ad": "Başkası", "telefon": "05000000000", "tutar": "9"})
        kontrol = lambda **k: islem(self.db, "veresiye_kontrol", k)["toplam"]
        self.assertEqual(kontrol(telefon="+90 (555) 111-2233"), 100)
        self.assertEqual(kontrol(ad="ibrahim ışık"), 100)
        self.assertEqual(kontrol(telefon="0555 999 99 99", ad="Yeni Müşteri"), 0)
        self.assertEqual(kontrol(telefon="", ad=""), 0)
        islem(self.db, "veresiye_ode", {"id": 1})
        self.assertEqual(kontrol(telefon="05551112233"), 0)

    def test_servis_maliyeti_kurla_carpilir_giderlere_yazilir(self):
        with self.assertRaises(ValueError):  # kur yoksa kayıt da açılmaz
            islem(self.db, "servis_ekle", {"cihaz_model": "A", "musteri": "B", "maliyet_usd": "10"})
        self.assertEqual(islem(self.db, "servis_listele", {}), [])
        self.kur_ayarla("40.5")
        islem(self.db, "servis_ekle", {"cihaz_model": "A", "musteri": "B", "maliyet_usd": "10"})
        islem(self.db, "servis_maliyet", {"id": 1, "usd": "2.5"})
        self.kur_ayarla("50")  # eski kayıtlar o günkü kurla kalır
        s = islem(self.db, "servis_listele", {})[0]
        self.assertEqual((s["maliyet_usd"], s["maliyet_tl"]), (12.5, 506.25))
        self.assertEqual(self.gun()["gider"], 506.25)
        # parça gideri silinince servis kaydı yeniden açılmaz, maliyet düşer
        islem(self.db, "servis_durum", {"id": 1, "durum": "teslim", "ucret": "0"})
        islem(self.db, "hareket_sil", {"id": self.gun()["kayitlar"][0]["id"]})
        s = islem(self.db, "servis_listele", {})[0]
        self.assertEqual((s["durum"], s["maliyet_usd"]), ("teslim", 10))

    def test_stok_girisi_gidere_yazilir(self):
        islem(self.db, "stok_ekle", {"kategori": "Kılıf", "ad": "iPhone 13", "adet": "10", "birim_maliyet": "20", "para_birimi": "TL"})
        with self.assertRaises(ValueError):
            islem(self.db, "stok_ekle", {"kategori": "Kılıf", "ad": "x", "adet": "1", "birim_maliyet": "1", "para_birimi": "USD"})
        self.kur_ayarla("40")
        islem(self.db, "stok_ekle", {"kategori": "Kulaklık", "ad": "Kablolu", "adet": "3", "birim_maliyet": "1.5", "para_birimi": "USD"})
        self.assertEqual(self.gun()["gider"], 200 + 180)
        stok = islem(self.db, "stok_listele", {})
        self.assertEqual([(x["kategori"], x["adet"], x["usd"]) for x in stok], [("Kulaklık", 3, 4.5), ("Kılıf", 10, None)])
        with self.assertRaises(ValueError):
            islem(self.db, "stok_ekle", {"kategori": "Yok", "ad": "x", "adet": "1", "birim_maliyet": "1"})

    def test_rapor_araliklari(self):
        self.assertEqual([x.isoformat() for x in rapor_araligi("hafta", "2026-11-01")], ["2026-10-26", "2026-11-01"])
        self.assertEqual([x.isoformat() for x in rapor_araligi("ay", "2026-12-31")], ["2026-12-01", "2026-12-31"])
        self.assertEqual([x.isoformat() for x in rapor_araligi("ay", "2028-02-10")], ["2028-02-01", "2028-02-29"])
        ekle = lambda t, tur, tutar, kategori=None: self.db.execute(
            "INSERT INTO hareket(tarih_saat,tur,tutar,aciklama,kategori) VALUES(?,?,?,?,?)",
            (t, tur, tutar, "x", kategori))
        ekle("2026-10-25 23:59:59", "gelir", 1000)  # önceki hafta
        ekle("2026-10-26 00:00:00", "gelir", 100)
        ekle("2026-11-01 23:59:59", "gider", 30, "Kılıf")
        ekle("2026-11-02 00:00:00", "gelir", 5000)  # sonraki hafta
        self.db.commit()
        r = islem(self.db, "rapor", {"tur": "hafta", "tarih": "2026-10-28"})
        self.assertEqual((r["gelir"], r["gider"], r["net"], r["parca_toplam"]), (100, 30, 70, 30))
        self.assertEqual([g["gun"] for g in r["gunler"]], ["2026-10-26", "2026-11-01"])
        self.assertEqual(islem(self.db, "rapor", {"tur": "ay", "tarih": "2026-10-05"})["gelir"], 1100)
        with self.assertRaises(ValueError):
            islem(self.db, "rapor", {"tur": "yil", "tarih": "2026-10-05"})

    def test_tcmb_verisi_cozulur(self):
        xml = '<Tarih_Date Tarih="30.10.2026"><Currency Kod="AUD"><ForexSelling>35.1</ForexSelling></Currency><Currency Kod="USD"><ForexSelling>49.8644</ForexSelling></Currency></Tarih_Date>'
        self.assertEqual(kur_coz(xml.encode()), (49.8644, "30.10.2026"))
        with self.assertRaises(ValueError):
            kur_coz(b'<Tarih_Date Tarih="1"></Tarih_Date>')

    def test_eski_veritabani_kayipsiz_yukseltilir(self):
        with tempfile.TemporaryDirectory() as k:
            yol = os.path.join(k, "eski.db")
            eski = sqlite3.connect(yol)
            eski.executescript("""CREATE TABLE hareket(id INTEGER PRIMARY KEY, tarih_saat TEXT NOT NULL, tur TEXT NOT NULL,
              tutar REAL NOT NULL, aciklama TEXT, urun_id INTEGER, adet INTEGER, servis_id INTEGER);
              INSERT INTO hareket(tarih_saat,tur,tutar,aciklama) VALUES('2026-10-28 10:00:00','gelir',75,'eski');""")
            eski.close()
            for _ in range(2):  # ikinci açılış da sorunsuz olmalı
                db = ac(yol)
                self.assertEqual(islem(db, "gun", {"tarih": "2026-10-28"})["gelir"], 75)
                db.close()


class ProfilTest(unittest.TestCase):
    def test_otomatik_doldurma_kapanir_diger_ayarlar_kalir(self):
        with tempfile.TemporaryDirectory() as k:
            yol = os.path.join(k, "Default", "Preferences")
            oku = lambda: json.load(open(yol, encoding="utf-8"))
            server.otomatik_doldurmayi_kapat(k)  # profil henüz yok
            self.assertFalse(oku()["autofill"]["profile_enabled"])
            with open(yol, "w", encoding="utf-8") as f:
                json.dump({"diger": 1, "autofill": {"profile_enabled": True, "x": 2}}, f)
            server.otomatik_doldurmayi_kapat(k)
            a = oku()
            self.assertEqual((a["diger"], a["autofill"]["x"], a["autofill"]["profile_enabled"]), (1, 2, False))
            with open(yol, "w", encoding="utf-8") as f:
                f.write("{bozuk")  # bozuk dosya uygulamayı durdurmamalı
            server.otomatik_doldurmayi_kapat(k)
            self.assertFalse(oku()["autofill"]["credit_card_enabled"])


class KimlikTest(unittest.TestCase):
    """Şifre, kurtarma kodu ve veritabanı şifrelemesi: gerçek HTTP istekleriyle."""

    def setUp(self):
        self.k = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.k, True)
        for ad, deger in (("DB_YOLU", os.path.join(self.k, "dukkan.db")), ("ANAHTAR_YOLU", os.path.join(self.k, "anahtar.dat"))):
            self.addCleanup(setattr, server, ad, getattr(server, ad))
            setattr(server, ad, deger)
        self.addCleanup(self.kapat)
        server.DB = server.ANAHTAR = server.OTURUM = None
        self.sunucu = ThreadingHTTPServer(("127.0.0.1", 0), server.Istek)
        server.PORT = self.sunucu.server_port
        threading.Thread(target=self.sunucu.serve_forever, daemon=True).start()
        self.cerez = None

    def kapat(self):
        self.sunucu.shutdown()
        if server.DB:
            server.DB.close()
        server.DB = server.ANAHTAR = server.OTURUM = None

    def istek(self, op, **d):
        c = http.client.HTTPConnection("127.0.0.1", server.PORT, timeout=20)
        b = {"Host": f"127.0.0.1:{server.PORT}", "Content-Type": "application/json"}
        if self.cerez:
            b["Cookie"] = self.cerez
        c.request("POST", "/api", body=json.dumps({"op": op, **d}), headers=b)
        r = c.getresponse()
        veri = json.loads(r.read() or b"{}")
        if r.getheader("Set-Cookie"):
            self.cerez = r.getheader("Set-Cookie").split(";")[0]
        c.close()
        return r.status, veri

    def yedek(self):
        c = http.client.HTTPConnection("127.0.0.1", server.PORT, timeout=20)
        b = {"Host": f"127.0.0.1:{server.PORT}"}
        if self.cerez:
            b["Cookie"] = self.cerez
        c.request("GET", "/yedek", headers=b)
        r = c.getresponse()
        veri = r.read()
        c.close()
        return r.status, veri

    def duz_db(self):
        d = sqlite3.connect(server.DB_YOLU)
        d.executescript("""CREATE TABLE veresiye(id INTEGER PRIMARY KEY, tarih TEXT NOT NULL, ad TEXT NOT NULL, telefon TEXT NOT NULL,
          tutar REAL NOT NULL, odendi TEXT);
          INSERT INTO veresiye(tarih,ad,telefon,tutar) VALUES('2026-10-28','GIZLI MUSTERI','05551112233',75);""")
        d.close()

    def test_eski_veritabani_sifrelenir_kayit_kaybolmaz(self):
        self.duz_db()
        self.assertEqual(self.istek("durum")[1]["durum"], "kurulum")
        self.assertEqual(self.istek("veresiye_listele")[0], 401)
        s, r = self.istek("kurulum", sifre="dogru-sifre")
        self.assertEqual(s, 200)
        self.assertEqual(self.istek("veresiye_listele")[1]["toplam"], 75)
        ham = open(server.DB_YOLU, "rb").read()
        self.assertNotIn(b"GIZLI MUSTERI", ham)
        self.assertNotIn(b"SQLite format 3", ham[:16])
        self.assertFalse(os.path.exists(server.DB_YOLU + ".sifreli"))
        self.assertEqual(server.DB.execute("PRAGMA secure_delete").fetchone()[0], 1)

    def test_sifre_kilit_ve_erisim(self):
        self.assertEqual(self.istek("kurulum", sifre="kisa")[0], 400)
        self.assertFalse(os.path.exists(server.ANAHTAR_YOLU))
        self.assertEqual(self.istek("kurulum", sifre="dogru-sifre")[0], 200)
        self.assertEqual(self.istek("veresiye_ekle", ad="A", telefon="05551112233", tutar="10")[0], 200)
        self.assertEqual(self.yedek()[0], 200)
        giris_cerezi = self.cerez
        self.assertEqual(self.istek("kurulum", sifre="baska-sifre")[0], 400)  # ikinci kurulum olmaz
        self.istek("kilitle")
        self.assertIsNone(server.DB)
        for c in (None, giris_cerezi, "oturum=sahte"):  # kilitlenince eski çerez de geçmez
            self.cerez = c
            self.assertEqual(self.istek("veresiye_listele")[0], 401)
            self.assertEqual(self.yedek()[0], 401)
            self.assertEqual(self.istek("kilitle")[0], 401)
        self.assertEqual(self.istek("durum")[1]["durum"], "kilitli")
        self.assertEqual(self.istek("giris", sifre="yanlis-sifre")[0], 400)
        self.assertIsNone(server.DB)
        self.assertEqual(self.istek("giris", sifre="dogru-sifre")[0], 200)
        self.assertEqual(self.istek("veresiye_listele")[1]["toplam"], 10)

    def test_yanlis_sifre_duz_veritabanini_bozmaz(self):
        # kurulum, anahtar yazıldıktan sonra yarıda kesildiyse giriş taşımayı tamamlar; yanlış şifre dokunamaz
        self.istek("kurulum", sifre="dogru-sifre")
        self.istek("kilitle")
        os.remove(server.DB_YOLU)
        self.duz_db()
        onceki = open(server.DB_YOLU, "rb").read()
        self.assertEqual(self.istek("giris", sifre="yanlis-sifre")[0], 400)
        self.assertEqual(open(server.DB_YOLU, "rb").read(), onceki)
        self.assertEqual(self.istek("giris", sifre="dogru-sifre")[0], 200)
        self.assertEqual(self.istek("veresiye_listele")[1]["toplam"], 75)
        self.assertNotIn(b"GIZLI MUSTERI", open(server.DB_YOLU, "rb").read())

    def test_kurtarma_kodu_ve_sifre_degistirme(self):
        kod = self.istek("kurulum", sifre="ilk-sifre")[1]["kurtarma"]
        self.istek("veresiye_ekle", ad="A", telefon="05551112233", tutar="10")
        self.assertEqual(self.istek("sifre_degistir", eski="yanlis-sifre", sifre="ikinci-sifre")[0], 400)
        self.assertEqual(self.istek("sifre_degistir", eski="ilk-sifre", sifre="ikinci-sifre")[0], 200)
        self.istek("kilitle")
        self.cerez = None
        self.assertEqual(self.istek("giris", sifre="ilk-sifre")[0], 400)
        self.assertEqual(self.istek("kurtar", kod="AAAA-BBBB-CCCC-DDDD-EEEE-FFFF", sifre="yeni-sifre")[0], 400)
        self.assertEqual(self.istek("kurtar", kod=kod.lower().replace("-", " "), sifre="yeni-sifre")[0], 200)
        self.assertEqual(self.istek("veresiye_listele")[1]["toplam"], 10)
        self.istek("kilitle")
        self.assertEqual(self.istek("giris", sifre="ikinci-sifre")[0], 400)
        self.assertEqual(self.istek("giris", sifre="yeni-sifre")[0], 200)

    def test_anahtar_kaybolursa_kayitlar_ezilmez(self):
        self.istek("kurulum", sifre="dogru-sifre")
        self.istek("kilitle")
        os.remove(server.ANAHTAR_YOLU)
        onceki = open(server.DB_YOLU, "rb").read()
        self.assertEqual(self.istek("durum")[1]["durum"], "anahtar_yok")
        self.assertEqual(self.istek("kurulum", sifre="yeni-sifre")[0], 400)
        self.assertEqual(open(server.DB_YOLU, "rb").read(), onceki)
        self.assertFalse(os.path.exists(server.ANAHTAR_YOLU))

    def test_yedekten_geri_donulur(self):
        self.istek("kurulum", sifre="dogru-sifre")
        self.istek("veresiye_ekle", ad="A", telefon="05551112233", tutar="10")
        s, z = self.yedek()
        self.istek("kilitle")
        os.remove(server.DB_YOLU)
        os.remove(server.ANAHTAR_YOLU)
        with zipfile.ZipFile(io.BytesIO(z)) as a:
            self.assertEqual(sorted(a.namelist()), ["anahtar.dat", "dukkan.db"])
            a.extractall(self.k)
        self.assertEqual(self.istek("giris", sifre="dogru-sifre")[0], 200)
        self.assertEqual(self.istek("veresiye_listele")[1]["toplam"], 10)


class GuvenlikTest(unittest.TestCase):
    def test_buyuk_yanit_tam_gelir(self):
        server.DB = ac(":memory:")
        sunucu = ThreadingHTTPServer(("127.0.0.1", 0), server.Istek)
        server.PORT = sunucu.server_port
        threading.Thread(target=sunucu.serve_forever, daemon=True).start()
        self.addCleanup(sunucu.shutdown)
        with open(os.path.join(server.KAYNAK, "index.html"), "rb") as f:
            beklenen = f.read()
        self.assertGreater(len(beklenen), 65536)  # takılma bu boyutun üstünde görülüyordu
        for _ in range(60):
            c = http.client.HTTPConnection("127.0.0.1", server.PORT, timeout=3)
            c.request("GET", "/", headers={"Host": f"127.0.0.1:{server.PORT}"})
            self.assertEqual(c.getresponse().read(), beklenen)
            c.close()

    def test_baska_siteler_engellenir(self):
        server.DB = ac(":memory:")
        sunucu = ThreadingHTTPServer(("127.0.0.1", 0), server.Istek)
        server.PORT = sunucu.server_port
        threading.Thread(target=sunucu.serve_forever, daemon=True).start()
        self.addCleanup(sunucu.shutdown)

        def istek(host, tip):
            c = http.client.HTTPConnection("127.0.0.1", server.PORT)
            c.request("POST", "/api", body=b'{"op":"ping"}', headers={"Host": host, "Content-Type": tip})
            return c.getresponse().status

        yerel = f"localhost:{server.PORT}"
        self.assertEqual(istek(yerel, "application/json"), 200)
        self.assertEqual(istek(f"kotu-site.com:{server.PORT}", "application/json"), 403)  # DNS rebinding
        self.assertEqual(istek(yerel, "text/plain"), 403)  # başka sitenin formu / fetch'i


if __name__ == "__main__":
    unittest.main()
