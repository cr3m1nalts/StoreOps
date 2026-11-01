"""Telefon dükkanı takip - yerel sunucu. Çalıştırmak için: python server.py"""
import json
import math
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# .exe içinde index.html geçici bir klasöre açılır; veritabanı ise .exe'nin yanında durur
KAYNAK = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
KLASOR = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else KAYNAK
DB_YOLU = os.path.join(KLASOR, "dukkan.db")
PORT = 8765
DB = None
SON_ISTEK = time.monotonic()  # sayfadan gelen son istek; pencere kapanınca kesilir
KILIT = threading.Lock()  # sqlite bağlantısını iş parçacıkları arasında sırayla kullanmak için

SEMA = """
CREATE TABLE IF NOT EXISTS servis(
  id INTEGER PRIMARY KEY, tarih TEXT NOT NULL, cihaz_model TEXT NOT NULL, musteri TEXT NOT NULL,
  telefon TEXT, kilit_turu TEXT, kilit_degeri TEXT, sikayet TEXT,
  durum TEXT NOT NULL DEFAULT 'alindi', ucret REAL NOT NULL DEFAULT 0, iade_nedeni TEXT);
CREATE TABLE IF NOT EXISTS urun(
  id INTEGER PRIMARY KEY, kategori TEXT NOT NULL, ad TEXT NOT NULL, fiyat REAL NOT NULL);
CREATE TABLE IF NOT EXISTS hareket(
  id INTEGER PRIMARY KEY, tarih_saat TEXT NOT NULL, tur TEXT NOT NULL CHECK(tur IN ('gelir','gider')),
  tutar REAL NOT NULL, aciklama TEXT, urun_id INTEGER, adet INTEGER, servis_id INTEGER);
CREATE TABLE IF NOT EXISTS ayar(anahtar TEXT PRIMARY KEY, deger TEXT);
CREATE TABLE IF NOT EXISTS tedarikci(id INTEGER PRIMARY KEY, ad TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS cihaz(
  id INTEGER PRIMARY KEY, alis_tarih TEXT NOT NULL, satici_ad TEXT NOT NULL, satici_tc TEXT NOT NULL,
  durum TEXT NOT NULL, marka TEXT NOT NULL, model TEXT NOT NULL, depolama TEXT NOT NULL, pil_sagligi INTEGER,
  kozmetik TEXT NOT NULL, mensei TEXT NOT NULL, alis_fiyat REAL NOT NULL, satis_tarih TEXT, satis_fiyat REAL);
CREATE TABLE IF NOT EXISTS veresiye(
  id INTEGER PRIMARY KEY, tarih TEXT NOT NULL, ad TEXT NOT NULL, telefon TEXT NOT NULL,
  tutar REAL NOT NULL, odendi TEXT);
"""
# Eski sürümlerin veritabanlarına eklenen sütunlar; dükkanlardaki kayıtlar korunur
YENI_HAREKET_SUTUNLARI = (("usd", "REAL"), ("kur", "REAL"), ("veresiye_id", "INTEGER"), ("kategori", "TEXT"),
                          ("tedarikci_id", "INTEGER"), ("cihaz_id", "INTEGER"))
TCMB_ADRES = "https://www.tcmb.gov.tr/kurlar/today.xml"
SURUM = "1.2"  # GitHub'da yayımlanan etiketle aynı olmalı (v1.2)
GITHUB_API = "https://api.github.com/repos/cr3m1nalts/StoreOps/releases/"
GUNCELLEME = {"yeni": None, "notlar": None}  # GitHub'dan okunur, veritabanına yazılmaz
CIHAZ_DURUMLARI = ("Sıfır", "İkinci El", "Yenilenmiş", "Arızalı")
KOZMETIK_DURUMLARI = ("Çok İyi", "İyi", "Orta", "Kötü")
MENSEILER = ("Yurtiçi", "Yurtdışı")
DURUMLAR = ("alindi", "tamirde", "hazir", "teslim", "iade")
KATEGORILER = ("Şarj Kablosu", "Şarj Aleti", "Kulaklık", "Kılıf", "Ekran Koruyucu", "Diğer")
AYARLAR = ("dukkan_adi",)


def simdi():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def ac(yol=DB_YOLU):
    db = sqlite3.connect(yol, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.executescript(SEMA)
    mevcut = {r["name"] for r in db.execute("PRAGMA table_info(hareket)")}
    with db:
        for ad, tip in YENI_HAREKET_SUTUNLARI:
            if ad not in mevcut:
                db.execute(f"ALTER TABLE hareket ADD COLUMN {ad} {tip}")
    return db


def satirlar(cur):
    return [dict(r) for r in cur]


def metin(d, k, zorunlu=False):
    v = str(d.get(k) or "").strip()
    if zorunlu and not v:
        raise ValueError(f"'{k}' boş olamaz")
    return v


def para(v, sifir_olur=False):
    t = round(float(v or 0), 2)
    if not math.isfinite(t) or t < 0 or (t == 0 and not sifir_olur):
        raise ValueError("Tutar sıfırdan büyük olmalı")
    return t


def gelir_yaz(db, tutar, aciklama, urun_id=None, adet=None, servis_id=None, veresiye_id=None, cihaz_id=None):
    db.execute("INSERT INTO hareket(tarih_saat,tur,tutar,aciklama,urun_id,adet,servis_id,veresiye_id,cihaz_id) "
               "VALUES(?,?,?,?,?,?,?,?,?)", (simdi(), "gelir", tutar, aciklama, urun_id, adet, servis_id, veresiye_id, cihaz_id))


def alim_yaz(db, d, on_ek, kategori=None, tedarikci_id=None):
    """Adet x birim maliyet (₺ veya $) alımını gider olarak yazar."""
    adet = int(d.get("adet") or 0)
    if adet < 1:
        raise ValueError("Adet en az 1 olmalı")
    toplam, kur, usd = para(d.get("birim_maliyet")) * adet, None, None
    if d.get("para_birimi") == "USD":
        kur, usd = kur_gerekli(db), round(toplam, 2)
        toplam *= kur
    db.execute("INSERT INTO hareket(tarih_saat,tur,tutar,aciklama,adet,usd,kur,kategori,tedarikci_id) VALUES(?,?,?,?,?,?,?,?,?)",
               (simdi(), "gider", round(toplam, 2), f"{on_ek}: {adet} x {metin(d, 'ad', True)}", adet, usd, kur, kategori, tedarikci_id))


def stok_urunleri(db):
    return satirlar(db.execute("SELECT DISTINCT kategori, substr(aciklama, instr(aciklama, ' x ') + 3) ad "
                               "FROM hareket WHERE kategori IS NOT NULL ORDER BY 1, 2"))


def tc_gecerli(t):
    if not re.fullmatch(r"[1-9]\d{10}", t):
        return False
    r = [int(c) for c in t]
    return (sum(r[0:9:2]) * 7 - sum(r[1:8:2])) % 10 == r[9] and sum(r[:10]) % 10 == r[10]


def surum_no(t):
    m = re.fullmatch(r"v?(\d+(?:\.\d+)*)", (t or "").strip())
    return tuple(([int(x) for x in m.group(1).split(".")] + [0, 0, 0])[:3]) if m else ()


def github_oku(yol):
    istek = urllib.request.Request(GITHUB_API + yol, headers={"User-Agent": "StoreOps", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(istek, timeout=15) as r:
        return json.loads(r.read(2_000_000))


def guncelleme_dongusu():
    while True:
        try:
            son = github_oku("latest")
            GUNCELLEME["yeni"] = ({"surum": son["tag_name"], "notlar": son.get("body") or ""}
                                  if surum_no(son["tag_name"]) > surum_no(SURUM) else None)
            if GUNCELLEME["notlar"] is None:
                GUNCELLEME["notlar"] = github_oku(f"tags/v{SURUM}").get("body") or ""
            bekle = 6 * 3600
        except OSError:  # internet yok ya da bu sürüm henüz yayımlanmamış
            bekle = 3600
        except Exception as e:
            print(f"Güncelleme denetlenemedi: {e}", flush=True)
            bekle = 3600
        time.sleep(bekle)


def cihaz_sil(db, cihaz_id):
    c = db.execute("SELECT satis_tarih FROM cihaz WHERE id=?", (cihaz_id,)).fetchone()
    if c and c["satis_tarih"]:
        raise ValueError("Satılmış cihazın alışı silinemez: önce satış kaydını silin")
    db.execute("DELETE FROM hareket WHERE cihaz_id=? AND tur='gider'", (cihaz_id,))
    db.execute("DELETE FROM cihaz WHERE id=?", (cihaz_id,))


def ayar_oku(db):
    return {r["anahtar"]: r["deger"] for r in db.execute("SELECT * FROM ayar")}


def kur_gerekli(db):
    kur = ayar_oku(db).get("usd_kur")
    if not kur:
        raise ValueError("Dolar kuru yok: üstteki kur düğmesinden elle girin")
    return float(kur)


def kur_kaydet(db, kur, tarih, kaynak):
    for k, v in (("usd_kur", kur), ("usd_tarih", tarih), ("usd_kaynak", kaynak)):
        db.execute("INSERT OR REPLACE INTO ayar VALUES(?,?)", (k, str(v)))


def kur_coz(xml):
    """TCMB today.xml içinden USD döviz satış kurunu ve bülten tarihini döner."""
    kok = ET.fromstring(xml)
    for c in kok.findall("Currency"):
        if c.get("Kod") == "USD":
            kur = float(c.findtext("ForexSelling"))
            if not math.isfinite(kur) or kur <= 0:
                raise ValueError("TCMB kuru geçersiz")
            return kur, kok.get("Tarih")
    raise ValueError("TCMB verisinde USD yok")


def kur_dongusu():
    while True:
        try:
            istek = urllib.request.Request(TCMB_ADRES, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(istek, timeout=15) as r:
                kur, tarih = kur_coz(r.read(2_000_000))
            with KILIT, DB:
                kur_kaydet(DB, kur, tarih, "TCMB")
            bekle = 3600
        except OSError:  # internet yok: son kur geçerli kalır, sessizce yeniden denenir
            bekle = 300
        except Exception as e:
            print(f"Kur alınamadı: {e}", flush=True)
            bekle = 300
        time.sleep(bekle)


def parca_gider_yaz(db, usd, aciklama, servis_id):
    kur = kur_gerekli(db)
    db.execute("INSERT INTO hareket(tarih_saat,tur,tutar,aciklama,servis_id,usd,kur) VALUES(?,?,?,?,?,?,?)",
               (simdi(), "gider", round(usd * kur, 2), f"{aciklama} ({usd:g} $)", servis_id, usd, kur))


def tel_norm(t):
    r = re.sub(r"\D", "", t or "")[-10:]  # 0555... ile +90555... aynı numara sayılır
    return r if len(r) >= 7 else ""


def ad_norm(a):
    return " ".join((a or "").replace("İ", "i").replace("I", "ı").lower().split())


def rapor_araligi(tur, tarih):
    g = date.fromisoformat(tarih)
    if tur == "hafta":
        bas = g - timedelta(days=g.weekday())
        return bas, bas + timedelta(days=6)
    if tur == "ay":
        bas = g.replace(day=1)
        return bas, (bas + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    raise ValueError("Geçersiz rapor türü")


def islem(db, op, d):
    with db:  # tek işlem: hata olursa yazılan her şey geri alınır
        if op == "servis_listele":
            q = f"%{metin(d, 'ara')}%"
            return satirlar(db.execute(
                "SELECT s.*, (SELECT COALESCE(SUM(h.tutar),0) FROM hareket h WHERE h.servis_id=s.id AND h.tur='gider') maliyet_tl, "
                "(SELECT COALESCE(SUM(h.usd),0) FROM hareket h WHERE h.servis_id=s.id AND h.tur='gider') maliyet_usd "
                "FROM servis s WHERE cihaz_model LIKE ? OR musteri LIKE ? OR telefon LIKE ? "
                "ORDER BY durum IN ('teslim','iade'), id DESC LIMIT 500", (q, q, q)))
        if op == "servis_ekle":
            yeni = db.execute(
                "INSERT INTO servis(tarih,cihaz_model,musteri,telefon,kilit_turu,kilit_degeri,sikayet,ucret) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (simdi(), metin(d, "cihaz_model", True), metin(d, "musteri", True), metin(d, "telefon"),
                 metin(d, "kilit_turu"), metin(d, "kilit_degeri"), metin(d, "sikayet"),
                 para(d.get("ucret"), sifir_olur=True)))
            usd = para(d.get("maliyet_usd"), sifir_olur=True)
            if usd > 0:
                parca_gider_yaz(db, usd, f"Parça: {metin(d, 'cihaz_model')} - {metin(d, 'musteri')}", yeni.lastrowid)
            return {"ok": True}
        if op == "servis_maliyet":
            s = db.execute("SELECT * FROM servis WHERE id=?", (int(d["id"]),)).fetchone()
            if not s:
                raise ValueError("Kayıt bulunamadı")
            parca_gider_yaz(db, para(d.get("usd")), f"Parça: {s['cihaz_model']} - {s['musteri']}", s["id"])
            return {"ok": True}
        if op == "servis_durum":
            s = db.execute("SELECT * FROM servis WHERE id=?", (int(d["id"]),)).fetchone()
            if not s:
                raise ValueError("Kayıt bulunamadı")
            if s["durum"] in ("teslim", "iade"):
                raise ValueError("Bu kayıt zaten kapanmış")
            durum = d.get("durum")
            if durum not in DURUMLAR:
                raise ValueError("Geçersiz durum")
            if durum == "teslim":
                u = para(d.get("ucret", s["ucret"]), sifir_olur=True)
                # kilit bilgisi teslimde silinir (KVKK)
                db.execute("UPDATE servis SET durum='teslim', ucret=?, kilit_degeri='' WHERE id=?", (u, s["id"]))
                if u > 0:
                    gelir_yaz(db, u, f"Servis: {s['cihaz_model']} - {s['musteri']}", servis_id=s["id"])
            elif durum == "iade":
                db.execute("UPDATE servis SET durum='iade', iade_nedeni=?, kilit_degeri='' WHERE id=?",
                           (metin(d, "neden", True), s["id"]))
            else:
                db.execute("UPDATE servis SET durum=? WHERE id=?", (durum, s["id"]))
            return {"ok": True}

        if op == "urun_listele":
            return satirlar(db.execute("SELECT * FROM urun ORDER BY kategori, ad"))
        if op == "urun_ekle":
            if d.get("kategori") not in KATEGORILER:
                raise ValueError("Geçersiz kategori")
            if {"kategori": d["kategori"], "ad": metin(d, "ad")} not in stok_urunleri(db):
                raise ValueError("Ürün stokta kayıtlı değil: önce Stok sekmesinden giriş yapın")
            db.execute("INSERT INTO urun(kategori,ad,fiyat) VALUES(?,?,?)",
                       (d["kategori"], metin(d, "ad", True), para(d.get("fiyat"))))
            return {"ok": True}
        if op == "urun_fiyat":
            db.execute("UPDATE urun SET fiyat=? WHERE id=?", (para(d.get("fiyat")), int(d["id"])))
            return {"ok": True}
        if op == "urun_sil":
            db.execute("DELETE FROM urun WHERE id=?", (int(d["id"]),))
            return {"ok": True}
        if op == "sat":
            u = db.execute("SELECT * FROM urun WHERE id=?", (int(d["urun_id"]),)).fetchone()
            if not u:
                raise ValueError("Ürün bulunamadı")
            adet = int(d.get("adet") or 0)
            if adet < 1:
                raise ValueError("Adet en az 1 olmalı")
            gelir_yaz(db, round(u["fiyat"] * adet, 2), f"{adet} x {u['ad']}", urun_id=u["id"], adet=adet)
            return {"ok": True}

        if op == "gun":
            g = metin(d, "tarih") or simdi()[:10]
            k = satirlar(db.execute("SELECT * FROM hareket WHERE tarih_saat LIKE ? ORDER BY id DESC", (g + "%",)))
            gelir = round(sum(x["tutar"] for x in k if x["tur"] == "gelir"), 2)
            gider = round(sum(x["tutar"] for x in k if x["tur"] == "gider"), 2)
            return {"tarih": g, "kayitlar": k, "gelir": gelir, "gider": gider, "net": round(gelir - gider, 2)}
        if op == "hareket_ekle":
            if d.get("tur") not in ("gelir", "gider"):
                raise ValueError("Geçersiz tür")
            db.execute("INSERT INTO hareket(tarih_saat,tur,tutar,aciklama) VALUES(?,?,?,?)",
                       (simdi(), d["tur"], para(d.get("tutar")), metin(d, "aciklama", True)))
            return {"ok": True}
        if op == "hareket_sil":
            h = db.execute("SELECT tur, servis_id, veresiye_id, cihaz_id FROM hareket WHERE id=?", (int(d["id"]),)).fetchone()
            if h and h["cihaz_id"]:
                if h["tur"] == "gelir":  # satış geri alınırsa cihaz yeniden stokta görünür
                    db.execute("UPDATE cihaz SET satis_tarih=NULL, satis_fiyat=NULL WHERE id=?", (h["cihaz_id"],))
                else:
                    cihaz_sil(db, h["cihaz_id"])
            if h and h["tur"] == "gelir" and h["servis_id"]:  # yanlışlıkla teslim edildiyse servis kaydı yeniden açılır
                db.execute("UPDATE servis SET durum='hazir' WHERE id=?", (h["servis_id"],))
            if h and h["veresiye_id"]:  # yanlışlıkla "ödendi" denildiyse borç geri gelir
                db.execute("UPDATE veresiye SET odendi=NULL WHERE id=?", (h["veresiye_id"],))
            db.execute("DELETE FROM hareket WHERE id=?", (int(d["id"]),))
            return {"ok": True}

        if op == "ping":  # açık sayfa 20 sn'de bir gönderir
            return {}
        if op == "veresiye_listele":
            toplam = db.execute("SELECT COALESCE(SUM(tutar),0) t FROM veresiye WHERE odendi IS NULL").fetchone()["t"]
            return {"toplam": round(toplam, 2), "kayitlar": satirlar(db.execute(
                "SELECT * FROM veresiye ORDER BY odendi IS NOT NULL, id DESC LIMIT 500"))}
        if op == "veresiye_ekle":
            db.execute("INSERT INTO veresiye(tarih,ad,telefon,tutar) VALUES(?,?,?,?)",
                       (simdi(), metin(d, "ad", True), metin(d, "telefon", True), para(d.get("tutar"))))
            return {"ok": True}
        if op == "veresiye_ode":
            v = db.execute("SELECT * FROM veresiye WHERE id=?", (int(d["id"]),)).fetchone()
            if not v:
                raise ValueError("Kayıt bulunamadı")
            if v["odendi"]:
                raise ValueError("Bu borç zaten ödenmiş")
            db.execute("UPDATE veresiye SET odendi=? WHERE id=?", (simdi(), v["id"]))
            gelir_yaz(db, v["tutar"], f"Veresiye ödemesi: {v['ad']}", veresiye_id=v["id"])
            return {"ok": True}
        if op == "veresiye_sil":
            if db.execute("DELETE FROM veresiye WHERE id=? AND odendi IS NULL", (int(d["id"]),)).rowcount == 0:
                raise ValueError("Ödenmiş borç silinemez")
            return {"ok": True}
        if op == "veresiye_kontrol":
            tel, ad = tel_norm(d.get("telefon")), ad_norm(d.get("ad"))
            k = [dict(v) for v in db.execute("SELECT * FROM veresiye WHERE odendi IS NULL")
                 if (tel and tel_norm(v["telefon"]) == tel) or (ad and ad_norm(v["ad"]) == ad)]
            return {"toplam": round(sum(v["tutar"] for v in k), 2), "kayitlar": k}

        if op == "stok_listele":
            return satirlar(db.execute("SELECT * FROM hareket WHERE kategori IS NOT NULL ORDER BY id DESC LIMIT 300"))
        if op == "stok_ekle":
            if d.get("kategori") not in KATEGORILER:
                raise ValueError("Geçersiz kategori")
            alim_yaz(db, d, "Stok", kategori=d["kategori"])
            return {"ok": True}
        if op == "stok_urunleri":
            return stok_urunleri(db)

        if op == "tedarikci_listele":
            return satirlar(db.execute("SELECT * FROM tedarikci ORDER BY ad"))
        if op == "tedarikci_ekle":
            db.execute("INSERT INTO tedarikci(ad) VALUES(?)", (metin(d, "ad", True),))
            return {"ok": True}
        if op == "tedarikci_sil":
            if db.execute("SELECT 1 FROM hareket WHERE tedarikci_id=?", (int(d["id"]),)).fetchone():
                raise ValueError("Bu parçacının alım kayıtları var: önce onları silin")
            db.execute("DELETE FROM tedarikci WHERE id=?", (int(d["id"]),))
            return {"ok": True}
        if op == "tedarikci_alim":
            t = db.execute("SELECT * FROM tedarikci WHERE id=?", (int(d["id"]),)).fetchone()
            if not t:
                raise ValueError("Parçacı bulunamadı")
            alim_yaz(db, d, f"Parça ({t['ad']})", tedarikci_id=t["id"])
            return {"ok": True}
        if op == "tedarikci_kayit":
            bas, bit = rapor_araligi("hafta", metin(d, "tarih") or simdi()[:10])
            k = satirlar(db.execute("SELECT * FROM hareket WHERE tedarikci_id=? AND substr(tarih_saat,1,10) BETWEEN ? AND ? "
                                    "ORDER BY id DESC", (int(d["id"]), bas.isoformat(), bit.isoformat())))
            return {"bas": bas.isoformat(), "bit": bit.isoformat(), "kayitlar": k,
                    "toplam": round(sum(x["tutar"] for x in k), 2)}

        if op == "cihaz_listele":
            return satirlar(db.execute("SELECT * FROM cihaz ORDER BY satis_tarih IS NOT NULL, id DESC LIMIT 500"))
        if op == "cihaz_al":
            tc = metin(d, "satici_tc")
            if not tc_gecerli(tc):
                raise ValueError("T.C. kimlik numarası geçersiz")
            if d.get("durum") not in CIHAZ_DURUMLARI or d.get("kozmetik") not in KOZMETIK_DURUMLARI or d.get("mensei") not in MENSEILER:
                raise ValueError("Cihaz durumu, kozmetik veya yurtiçi/yurtdışı seçimi geçersiz")
            marka, model = metin(d, "marka", True), metin(d, "model", True)
            pil = None
            if "iphone" in ad_norm(f"{marka} {model}") or "apple" in ad_norm(marka):
                pil = int(d.get("pil_sagligi") or 0)
                if not 1 <= pil <= 100:
                    raise ValueError("iPhone için pil sağlığı 1-100 arasında olmalı")
            fiyat = para(d.get("alis_fiyat"))
            c = db.execute("INSERT INTO cihaz(alis_tarih,satici_ad,satici_tc,durum,marka,model,depolama,pil_sagligi,kozmetik,mensei,alis_fiyat) "
                           "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                           (simdi(), metin(d, "satici_ad", True), tc, d["durum"], marka, model, metin(d, "depolama", True),
                            pil, d["kozmetik"], d["mensei"], fiyat))
            db.execute("INSERT INTO hareket(tarih_saat,tur,tutar,aciklama,cihaz_id) VALUES(?,?,?,?,?)",
                       (simdi(), "gider", fiyat, f"Cihaz alışı: {marka} {model}", c.lastrowid))
            return {"ok": True}
        if op == "cihaz_sat":
            c = db.execute("SELECT * FROM cihaz WHERE id=?", (int(d["id"]),)).fetchone()
            if not c:
                raise ValueError("Yalnızca kayıtlı cihazlar satılabilir")
            if c["satis_tarih"]:
                raise ValueError("Bu cihaz zaten satılmış")
            fiyat = para(d.get("fiyat"))
            db.execute("UPDATE cihaz SET satis_tarih=?, satis_fiyat=? WHERE id=?", (simdi(), fiyat, c["id"]))
            gelir_yaz(db, fiyat, f"Cihaz satışı: {c['marka']} {c['model']}", cihaz_id=c["id"])
            return {"ok": True}
        if op == "cihaz_sil":
            cihaz_sil(db, int(d["id"]))
            return {"ok": True}

        if op == "guncelleme":
            gorulmedi = ayar_oku(db).get("son_surum") != SURUM
            return {"surum": SURUM, "yeni": GUNCELLEME["yeni"], "notlar": GUNCELLEME["notlar"] if gorulmedi else None}
        if op == "notlar_goruldu":
            db.execute("INSERT OR REPLACE INTO ayar VALUES('son_surum', ?)", (SURUM,))
            return {"ok": True}

        if op == "rapor":
            bas, bit = rapor_araligi(d.get("tur"), metin(d, "tarih") or simdi()[:10])
            aralik = (bas.isoformat(), bit.isoformat())
            gunler = satirlar(db.execute(
                "SELECT substr(tarih_saat,1,10) gun, ROUND(SUM(CASE WHEN tur='gelir' THEN tutar ELSE 0 END),2) gelir, "
                "ROUND(SUM(CASE WHEN tur='gider' THEN tutar ELSE 0 END),2) gider FROM hareket "
                "WHERE substr(tarih_saat,1,10) BETWEEN ? AND ? GROUP BY gun ORDER BY gun", aralik))
            parcalar = satirlar(db.execute(
                "SELECT * FROM hareket WHERE tur='gider' AND (kategori IS NOT NULL OR servis_id IS NOT NULL OR tedarikci_id IS NOT NULL) "
                "AND substr(tarih_saat,1,10) BETWEEN ? AND ? ORDER BY id DESC", aralik))
            gelir = round(sum(g["gelir"] for g in gunler), 2)
            gider = round(sum(g["gider"] for g in gunler), 2)
            return {"bas": aralik[0], "bit": aralik[1], "gunler": gunler, "parcalar": parcalar, "gelir": gelir,
                    "gider": gider, "net": round(gelir - gider, 2),
                    "parca_toplam": round(sum(p["tutar"] for p in parcalar), 2)}

        if op == "kur":
            a = ayar_oku(db)
            return {"kur": float(a["usd_kur"]) if a.get("usd_kur") else None,
                    "tarih": a.get("usd_tarih"), "kaynak": a.get("usd_kaynak")}
        if op == "kur_yaz":
            kur_kaydet(db, para(d.get("kur")), datetime.now().strftime("%d.%m.%Y"), "Elle girildi")
            return {"ok": True}

        if op == "ayar_oku":
            return ayar_oku(db)
        if op == "ayar_yaz":
            if d.get("anahtar") not in AYARLAR:
                raise ValueError("Geçersiz ayar")
            db.execute("INSERT OR REPLACE INTO ayar VALUES(?,?)", (d["anahtar"], metin(d, "deger", True)[:30]))
            return {"ok": True}
    raise ValueError("Bilinmeyen işlem")


def canli():
    global SON_ISTEK
    SON_ISTEK = time.monotonic()


class Istek(BaseHTTPRequestHandler):
    def gonder(self, kod, veri, tip, ek=None):
        self.send_response(kod)
        self.send_header("Content-Type", tip)
        self.send_header("Content-Length", str(len(veri)))  # eksik gelen yanıt (ör. yedek) fark edilsin
        for k, v in (ek or {}).items():
            self.send_header(k, v)
        self.end_headers()
        for i in range(0, len(veri), 32768):  # Windows'ta tek seferde 64 KB üstü gönderim ara sıra takılıyor
            self.wfile.write(veri[i:i + 32768])

    def yerel_mi(self):
        # başka sitelerin (DNS rebinding) bu sunucuya erişmesini engeller
        return self.headers.get("Host") in (f"localhost:{PORT}", f"127.0.0.1:{PORT}")

    def do_GET(self):
        canli()
        if not self.yerel_mi():
            return self.gonder(403, b"", "text/plain")
        if self.path == "/yedek":
            with KILIT, open(DB_YOLU, "rb") as f:
                ad = f"dukkan-yedek-{simdi()[:10]}.db"
                return self.gonder(200, f.read(), "application/octet-stream",
                                   {"Content-Disposition": f'attachment; filename="{ad}"'})
        with open(os.path.join(KAYNAK, "index.html"), "rb") as f:
            self.gonder(200, f.read(), "text/html; charset=utf-8")

    def do_POST(self):
        canli()
        govde = self.rfile.read(int(self.headers.get("Content-Length", 0)))  # reddedilse de okunmalı (Windows bağlantıyı koparır)
        # JSON başlığı zorunlu: tarayıcı başka sitelerden gelen bu isteği engeller
        if not self.yerel_mi() or self.path != "/api" or self.headers.get("Content-Type") != "application/json":
            return self.gonder(403, b"", "text/plain")
        try:
            d = json.loads(govde or b"{}")
            with KILIT:
                sonuc, kod = islem(DB, d.get("op"), d), 200
        except Exception as e:  # her hata kullanıcıya mesaj olarak döner; yazılanlar zaten geri alınmıştır
            sonuc, kod = {"hata": str(e) or "Geçersiz veri"}, 400
        self.gonder(kod, json.dumps(sonuc, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def log_message(self, *a):
        pass


def otomatik_doldurmayi_kapat(profil):
    """Edge'in müşteri adı/telefon önerilerini yalnızca bu uygulamanın profilinde kapatır."""
    yol = os.path.join(profil, "Default", "Preferences")
    try:
        with open(yol, encoding="utf-8") as f:
            ayarlar = json.load(f)
    except (OSError, ValueError):
        ayarlar = {}
    ayarlar.setdefault("autofill", {}).update(profile_enabled=False, credit_card_enabled=False)
    os.makedirs(os.path.dirname(yol), exist_ok=True)
    with open(yol + ".tmp", "w", encoding="utf-8") as f:
        json.dump(ayarlar, f)
    os.replace(yol + ".tmp", yol)


def pencere_ac(url):
    """Edge'i adres çubuğu olmayan kendi penceresinde açar (yoksa varsayılan tarayıcıda)."""
    for kok in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles")):
        edge = os.path.join(kok or "", "Microsoft", "Edge", "Application", "msedge.exe")
        if os.path.exists(edge):
            # ayrı profil: kullanıcının açık Edge'ine karışmaz
            subprocess.Popen([edge, f"--app={url}", f"--user-data-dir={os.path.join(KLASOR, 'tarayici')}",
                              "--no-first-run", "--no-default-browser-check", "--window-size=1280,820"])
            return
    webbrowser.open(url)


def edge_acik_mi():
    """Bu uygulamanın Edge profiliyle açık pencere var mı (küçültülmüş ya da uyutulmuş olsa bile)."""
    profil = os.path.join(KLASOR, "tarayici").replace("'", "''")
    komut = ("@(Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" | Where-Object "
             f"{{ $_.CommandLine -and $_.CommandLine.Contains('{profil}') }}).Count")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", komut], capture_output=True, text=True,
                           timeout=60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return r.stdout.strip() not in ("", "0")
    except Exception:
        return True  # emin değilsek açık kal: pencere sunucusuz kalmasın


if __name__ == "__main__":
    if sys.stderr is None:  # .exe konsolsuz çalışır: hatalar dosyaya yazılsın
        sys.stdout = sys.stderr = open(os.path.join(KLASOR, "storeops.log"), "a", encoding="utf-8")
    adres = f"http://127.0.0.1:{PORT}"  # localhost bazı bilgisayarlarda önce IPv6'yı dener
    try:
        sunucu = ThreadingHTTPServer(("127.0.0.1", PORT), Istek)
    except OSError:  # uygulama zaten açık: sadece pencereyi aç
        pencere_ac(adres)
        raise SystemExit
    DB = ac()
    threading.Thread(target=sunucu.serve_forever, daemon=True).start()
    threading.Thread(target=kur_dongusu, daemon=True).start()
    threading.Thread(target=guncelleme_dongusu, daemon=True).start()
    print(f"Uygulama açık: {adres}")
    canli()
    otomatik_doldurmayi_kapat(os.path.join(KLASOR, "tarayici"))
    pencere_ac(adres)
    # Pencere kapanınca kapan: 3 dk sayfadan ses gelmezse ve uygulamanın Edge penceresi de kalmadıysa.
    # (Edge'in açtığı süreci beklemek güvenilir değil: ilk açılışta kendini yeniden başlatabiliyor.)
    while time.monotonic() - SON_ISTEK < 180 or edge_acik_mi():
        time.sleep(30)
