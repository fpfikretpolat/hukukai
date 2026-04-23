import os
import pyodbc
import tempfile
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
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

# --- VERİ KALIPLARI ---
class LoginIstegi(BaseModel):
    username: str
    password: str

class KayitIstegi(BaseModel):
    username: str
    password: str

# Masaüstü ajanından gelecek verinin GÜNCELLENMİŞ kalıbı
class SorguIstegi(BaseModel):
    username: str
    password: str
    prompt: str
    brans: str = "Genel Analiz" # Hangi uzmanlık kullanılacak
    doc_context: str = ""       # Sadece ilk yüklemede dolu gelecek
    file_uri: str = None        # Gemini'nin dosyaya verdiği kimlik (Varsa)


@app.get("/")
def home():
    return {"mesaj": "Hukuk AI Sunucusu Aktif!"}

# --- GÜVENLİ KAYIT KAPISI ---
@app.post("/register")
async def kayit_ol(istek: KayitIstegi):
    try:
        conn = pyodbc.connect(connection_string)
        cursor = conn.cursor()
        
        cursor.execute("SELECT id FROM kullanicilar WHERE kullanici_adi = ?", (istek.username,))
        if cursor.fetchone():
            raise HTTPException(status_code=400, detail="Bu kullanıcı adı zaten alınmış!")
        
        cursor.execute("""
            INSERT INTO kullanicilar (kullanici_adi, sifre_hash) 
            VALUES (?, ?)
        """, (istek.username, istek.password))
        
        conn.commit()
        return {"durum": "basarili", "mesaj": "Hesap oluşturuldu."}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"SQL Hatası: {str(e)}")
    finally:
        if 'conn' in locals():
            conn.close()

# --- GİRİŞ KONTROL KAPISI ---
@app.post("/login")
async def giris_kontrol(istek: LoginIstegi):
    try:
        conn = pyodbc.connect(connection_string)
        cursor = conn.cursor()
        
        cursor.execute("SELECT id FROM kullanicilar WHERE kullanici_adi = ? AND sifre_hash = ?", 
                       (istek.username, istek.password))
        user = cursor.fetchone()
        
        if not user:
            raise HTTPException(status_code=401, detail="Hatalı kullanıcı adı veya şifre!")
            
        return {"durum": "basarili"}
    finally:
        if 'conn' in locals():
            conn.close()

# --- YENİ: FILE API İLE AKILLI ANALİZ KAPISI ---
@app.post("/analiz")
async def analiz_et(istek: SorguIstegi):
    try:
        conn = pyodbc.connect(connection_string)
        cursor = conn.cursor()

        # 1. Kullanıcı Doğrulama ve Kota Bilgilerini Çekme
        cursor.execute("SELECT id, aylik_kota, kullanilan_token FROM kullanicilar WHERE kullanici_adi = ? AND sifre_hash = ?", 
                       (istek.username, istek.password))
        user = cursor.fetchone()

        if not user:
            raise HTTPException(status_code=401, detail="Hatalı kullanıcı adı veya şifre!")

        user_id, kota, kullanilan = user
        
        # Sadece soruyu maliyet olarak hesaplıyoruz (Koca dökümanı artık saymıyoruz!)
        girdi_token = len(istek.prompt.split())

        if kullanilan + girdi_token > kota:
            raise HTTPException(status_code=402, detail="Aylık kullanım kotanızı aştınız!")

        # 2. File API: Dosyayı Bul veya Yükle
        uploaded_file = None
        current_file_uri = istek.file_uri

        # Eğer ajandan bir URI gelmediyse (Yeni dosya) ve metin gönderildiyse:
        if not current_file_uri and istek.doc_context:
            # Metni geçici bir dosyaya yaz
            with tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode="w", encoding="utf-8") as tmp:
                tmp.write(istek.doc_context)
                tmp_path = tmp.name
            
            # Gemini'ye dosya olarak yükle
            uploaded_file = genai.upload_file(path=tmp_path, display_name=f"Dava_{istek.username}")
            current_file_uri = uploaded_file.uri
            os.remove(tmp_path) # İşimiz bitince geçici dosyayı sil
            
        # Eğer ajan daha önce yüklenmiş bir dosyanın URI'sini gönderdiyse:
        elif current_file_uri:
            try:
                # Gemini hafızasından dosyayı çağır
                uploaded_file = genai.get_file(current_file_uri.split("/")[-1])
            except:
                # Dosyanın süresi dolmuşsa (Genelde 48 saat) ajana hata yolla, ajan metni tekrar göndersin
                return {"durum": "hata", "hata_kodu": "file_expired", "cevap": "Oturum zaman aşımına uğradı, dosya arka planda yeniden yükleniyor..."}

        # 3. Gemini API'ye İstek Atma
        mesaj_icerigi = []
        if uploaded_file:
            mesaj_icerigi.append(uploaded_file) # Dosya referansını ekle
        
        # Soruyu ve seçilen uzmanlık branşını ekle
        mesaj_icerigi.append(f"Uzmanlık Alanı/Branş: {istek.brans}\nSoru: {istek.prompt}")
        
        response = model.generate_content(mesaj_icerigi)
        ai_cevap = response.text
        
        # 4. Harcanan Kelimeleri (Sadece Soru + Cevap) Veritabanına Yazma
        toplam_harcanan = girdi_token + len(ai_cevap.split())
        cursor.execute("UPDATE kullanicilar SET kullanilan_token = kullanilan_token + ? WHERE id = ?", 
                       (toplam_harcanan, user_id))
        conn.commit()

        return {
            "durum": "basarili",
            "cevap": ai_cevap, 
            "harcanan_kelime": toplam_harcanan, 
            "kalan_kota": kota - (kullanilan + toplam_harcanan),
            "file_uri": current_file_uri # Ajan bunu kaydedecek ve bir sonraki soruda bize geri yollayacak
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if 'conn' in locals():
            conn.close()
