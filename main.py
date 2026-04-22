import os
import pyodbc
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import google.generativeai as genai

app = FastAPI(title="Hukuk AI API")

# Azure Configuration'dan gelecek şifreler
DB_SERVER = os.getenv("DB_SERVER")
DB_DATABASE = os.getenv("DB_DATABASE")
DB_USERNAME = os.getenv("DB_USERNAME")
DB_PASSWORD = os.getenv("DB_PASSWORD")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")

# Veritabanı Bağlantı Cümlesi (ZIRHLI VERSİYON)
connection_string = (
    f"DRIVER={{ODBC Driver 17 for SQL Server}};"
    f"SERVER=tcp:{DB_SERVER},1433;"
    f"DATABASE={DB_DATABASE};"
    f"UID={DB_USERNAME};"
    f"PWD={{{DB_PASSWORD}}};" 
    f"Encrypt=yes;"
    f"TrustServerCertificate=no;"
    f"Connection Timeout=30;"
)
# Gemini Kurulumu
if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)
    model = genai.GenerativeModel('gemini-2.5-flash') # Hız için flash idealdir

# Masaüstü ajanından gelecek verinin kalıbı
class SorguIstegi(BaseModel):
    username: str
    password: str
    prompt: str
    doc_context: str = ""

@app.get("/")
def home():
    return {"mesaj": "Hukuk AI Sunucusu Aktif!"}

# --- YENİ EKLENEN GİRİŞ KONTROL KAPISI ---
class LoginIstegi(BaseModel):
    username: str
    password: str

# --- YENİ: KAYIT OLMA KAPISI ---
class KayitIstegi(BaseModel):
    username: str
    password: str

@app.post("/register")
async def kayit_ol(istek: KayitIstegi):
    try:
        conn = pyodbc.connect(connection_string)
        cursor = conn.cursor()
        
        # Kullanıcı adı zaten var mı kontrol et
        cursor.execute("SELECT id FROM kullanicilar WHERE kullanici_adi = ?", (istek.username,))
        if cursor.fetchone():
            raise HTTPException(status_code=400, detail="Bu kullanıcı adı zaten alınmış!")
        
        # Yeni kullanıcıyı ekle (Başlangıç kotası: 5000 kelime)
        cursor.execute("""
            INSERT INTO kullanicilar (kullanici_adi, sifre_hash, toplam_kota, kullanilan_kota) 
            VALUES (?, ?, ?, ?)
        """, (istek.username, istek.password, 5000, 0))
        
        conn.commit()
        return {"durum": "basarili", "mesaj": "Hesap oluşturuldu. Giriş yapabilirsiniz."}
    finally:
        if 'conn' in locals():
            conn.close()

@app.post("/login")
async def giris_kontrol(istek: LoginIstegi):
    try:
        conn = pyodbc.connect(connection_string)
        cursor = conn.cursor()
        
        # Sadece veritabanında bu kullanıcı var mı diye bakıyoruz
        cursor.execute("SELECT id FROM kullanicilar WHERE kullanici_adi = ? AND sifre_hash = ?", 
                       (istek.username, istek.password))
        user = cursor.fetchone()
        
        if not user:
            raise HTTPException(status_code=401, detail="Hatalı kullanıcı adı veya şifre!")
            
        return {"durum": "basarili"}
    finally:
        if 'conn' in locals():
            conn.close()
# ------------------------------------------

@app.post("/analiz")
async def analiz_et(istek: SorguIstegi):
    try:
        conn = pyodbc.connect(connection_string)
        cursor = conn.cursor()

        # 1. Kullanıcı Doğrulama ve Kota Kontrolü
        cursor.execute("SELECT id, aylik_kota, kullanilan_token FROM kullanicilar WHERE kullanici_adi = ? AND sifre_hash = ?", 
                       (istek.username, istek.password))
        user = cursor.fetchone()

        if not user:
            raise HTTPException(status_code=401, detail="Hatalı kullanıcı adı veya şifre!")

        user_id, kota, kullanilan = user
        girdi_token = len(istek.prompt.split()) + len(istek.doc_context.split())

        if kullanilan + girdi_token > kota:
            raise HTTPException(status_code=402, detail="Aylık kullanım kotanızı aştınız!")

        # 2. Gemini API'ye İstek Atma
        tam_metin = f"Bağlam: {istek.doc_context}\nSoru: {istek.prompt}"
        response = model.generate_content(tam_metin)
        ai_cevap = response.text
        
        # 3. Harcanan Kelimeleri (Token) Veritabanına Yazma
        toplam_harcanan = girdi_token + len(ai_cevap.split())
        cursor.execute("UPDATE kullanicilar SET kullanilan_token = kullanilan_token + ? WHERE id = ?", 
                       (toplam_harcanan, user_id))
        conn.commit()

        return {
            "durum": "basarili",
            "cevap": ai_cevap, 
            "harcanan_kelime": toplam_harcanan, 
            "kalan_kota": kota - (kullanilan + toplam_harcanan)
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if 'conn' in locals():
            conn.close()
