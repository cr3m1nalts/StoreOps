import http.client
import threading
import unittest
from http.server import ThreadingHTTPServer

import server
from server import ac, islem


class Test(unittest.TestCase):
    def setUp(self):
        self.db = ac(":memory:")

    def gun(self):
        return islem(self.db, "gun", {})

    def test_satis_gelire_yazilir(self):
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


class GuvenlikTest(unittest.TestCase):
    def test_baska_siteler_engellenir(self):
        server.DB = ac(":memory:")
        sunucu = ThreadingHTTPServer(("127.0.0.1", 0), server.Istek)
        server.PORT = sunucu.server_port
        threading.Thread(target=sunucu.serve_forever, daemon=True).start()
        self.addCleanup(sunucu.shutdown)

        def istek(host, tip):
            c = http.client.HTTPConnection("127.0.0.1", server.PORT)
            c.request("POST", "/api", body=b'{"op":"gun"}', headers={"Host": host, "Content-Type": tip})
            return c.getresponse().status

        yerel = f"localhost:{server.PORT}"
        self.assertEqual(istek(yerel, "application/json"), 200)
        self.assertEqual(istek(f"kotu-site.com:{server.PORT}", "application/json"), 403)  # DNS rebinding
        self.assertEqual(istek(yerel, "text/plain"), 403)  # başka sitenin formu / fetch'i


if __name__ == "__main__":
    unittest.main()
