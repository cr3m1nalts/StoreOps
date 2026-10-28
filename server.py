"""Telefon dükkanı takip - yerel sunucu. Çalıştırmak için: python server.py"""
import json
import math
import os
import sqlite3
import subprocess
import sys
import threading
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# .exe içinde index.html geçici bir klasöre açılır; veritabanı ise .exe'nin yanında durur
KAYNAK = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
KLASOR = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else KAYNAK
DB_YOLU = os.path.join(KLASOR, "dukkan.db")
PORT = 8765
DB = None
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
"""
DURUMLAR = ("alindi", "tamirde", "hazir", "teslim", "iade")
KATEGORILER = ("Şarj Kablosu", "Şarj Aleti", "Kılıf", "Ekran Koruyucu", "Diğer")
AYARLAR = ("dukkan_adi",)


def simdi():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def ac(yol=DB_YOLU):
    db = sqlite3.connect(yol, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.executescript(SEMA)
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


def gelir_yaz(db, tutar, aciklama, urun_id=None, adet=None, servis_id=None):
    db.execute("INSERT INTO hareket(tarih_saat,tur,tutar,aciklama,urun_id,adet,servis_id) VALUES(?,?,?,?,?,?,?)",
               (simdi(), "gelir", tutar, aciklama, urun_id, adet, servis_id))


def islem(db, op, d):
    with db:  # tek işlem: hata olursa yazılan her şey geri alınır
        if op == "servis_listele":
            q = f"%{metin(d, 'ara')}%"
            return satirlar(db.execute(
                "SELECT * FROM servis WHERE cihaz_model LIKE ? OR musteri LIKE ? OR telefon LIKE ? "
                "ORDER BY durum IN ('teslim','iade'), id DESC LIMIT 500", (q, q, q)))
        if op == "servis_ekle":
            db.execute("INSERT INTO servis(tarih,cihaz_model,musteri,telefon,kilit_turu,kilit_degeri,sikayet,ucret) "
                       "VALUES(?,?,?,?,?,?,?,?)",
                       (simdi(), metin(d, "cihaz_model", True), metin(d, "musteri", True), metin(d, "telefon"),
                        metin(d, "kilit_turu"), metin(d, "kilit_degeri"), metin(d, "sikayet"),
                        para(d.get("ucret"), sifir_olur=True)))
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
            h = db.execute("SELECT servis_id FROM hareket WHERE id=?", (int(d["id"]),)).fetchone()
            if h and h["servis_id"]:  # yanlışlıkla teslim edildiyse servis kaydı yeniden açılır
                db.execute("UPDATE servis SET durum='hazir' WHERE id=?", (h["servis_id"],))
            db.execute("DELETE FROM hareket WHERE id=?", (int(d["id"]),))
            return {"ok": True}

        if op == "ayar_oku":
            return {r["anahtar"]: r["deger"] for r in db.execute("SELECT * FROM ayar")}
        if op == "ayar_yaz":
            if d.get("anahtar") not in AYARLAR:
                raise ValueError("Geçersiz ayar")
            db.execute("INSERT OR REPLACE INTO ayar VALUES(?,?)", (d["anahtar"], metin(d, "deger", True)[:30]))
            return {"ok": True}
    raise ValueError("Bilinmeyen işlem")


class Istek(BaseHTTPRequestHandler):
    def gonder(self, kod, veri, tip, ek=None):
        self.send_response(kod)
        self.send_header("Content-Type", tip)
        for k, v in (ek or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(veri)

    def yerel_mi(self):
        # başka sitelerin (DNS rebinding) bu sunucuya erişmesini engeller
        return self.headers.get("Host") in (f"localhost:{PORT}", f"127.0.0.1:{PORT}")

    def do_GET(self):
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


def pencere_ac(url):
    """Edge'i adres çubuğu olmayan kendi penceresinde açar; pencere kapanana kadar bekletilebilir süreci döner."""
    for kok in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles")):
        edge = os.path.join(kok or "", "Microsoft", "Edge", "Application", "msedge.exe")
        if os.path.exists(edge):
            # ayrı profil: kullanıcının açık Edge'ine karışmaz ve pencere kapanınca süreç biter
            return subprocess.Popen([edge, f"--app={url}", f"--user-data-dir={os.path.join(KLASOR, 'tarayici')}",
                                     "--no-first-run", "--no-default-browser-check", "--window-size=1280,820"])
    webbrowser.open(url)  # shortcut: Edge yoksa normal tarayıcıda açılır ve sunucu kendiliğinden kapanmaz
    return None


if __name__ == "__main__":
    if sys.stderr is None:  # .exe konsolsuz çalışır: hatalar dosyaya yazılsın
        sys.stdout = sys.stderr = open(os.path.join(KLASOR, "storeops.log"), "a", encoding="utf-8")
    adres = f"http://localhost:{PORT}"
    try:
        sunucu = ThreadingHTTPServer(("127.0.0.1", PORT), Istek)
    except OSError:  # uygulama zaten açık: sadece pencereyi aç
        pencere_ac(adres)
        raise SystemExit
    DB = ac()
    threading.Thread(target=sunucu.serve_forever, daemon=True).start()
    print(f"Uygulama açık: {adres}")
    pencere = pencere_ac(adres)
    if pencere:
        pencere.wait()  # pencere kapanınca uygulama da kapanır
    else:
        threading.Event().wait()
