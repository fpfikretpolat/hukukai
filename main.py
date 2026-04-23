import os
import pyodbc
import tempfile
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional
from google import genai

app = FastAPI(title="Hukuk AI API")

# Azure Configuration'dan gelecek şifreler
DB_SERVER = os.getenv("DB_SERVER")
DB_DATABASE = os.getenv("DB_DATABASE")
DB_USERNAME = os.getenv("DB_USERNAME")
DB_PASSWORD = os.getenv("DB_PASSWORD")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")

# Veritabanı Bağlantı Cümlesi
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

# --- YENİ NESİL GEMINI KURULUMU ---
if GEMINI_KEY:
    client = genai.Client(api_key=GEMINI_KEY)

class LoginIstegi(BaseModel):
    username: str
    password: str

class KayitIstegi(BaseModel):
    username: str
    password: str

class SorguIstegi(BaseModel):
    username: str
    password: str
    prompt: str
    brans: str = "Genel Analiz"
    doc_context: str = ""
    file_uri: Optional[str] = None


@app.get("/")
def home():
    return {"mesaj": "Hukuk AI Sunucusu Aktif!"}

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

@app.post("/analiz")
async def analiz_et(istek: SorguIstegi):
    try:
        conn = pyodbc.connect(connection_string)
        cursor = conn.cursor()

        cursor.execute("SELECT id, aylik_kota, kullanilan_token FROM kullanicilar WHERE kullanici_adi = ? AND sifre_hash = ?", 
                       (istek.username, istek.password))
        user = cursor.fetchone()

        if not user:
            raise HTTPException(status_code=401, detail="Hatalı kullanıcı adı veya şifre!")

        user_id, kota, kullanilan = user
        girdi_token = len(istek.prompt.split())

        if kullanilan + girdi_token > kota:
            raise HTTPException(status_code=402, detail="Aylık kullanım kotanızı aştınız!")

        uploaded_file = None
        current_file_uri = istek.file_uri

        # 1. YENİ NESİL DOSYA YÜKLEME VEYA ÇAĞIRMA
        if not current_file_uri and istek.doc_context:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode="w", encoding="utf-8") as tmp:
                tmp.write(istek.doc_context)
                tmp_path = tmp.name
            
            # Yeni SDK Dosya Yükleme Kodu
            uploaded_file = client.files.upload(file=tmp_path)
            current_file_uri = uploaded_file.name # Yeni SDK .uri yerine .name kullanır
            os.remove(tmp_path)
            
        elif current_file_uri:
            try:
                # Yeni SDK Dosya Çağırma Kodu
                uploaded_file = client.files.get(name=current_file_uri)
            except:
                return {"durum": "hata", "hata_kodu": "file_expired", "cevap": "Oturum zaman aşımına uğradı, dosya arka planda yeniden yükleniyor..."}

        # 2. YENİ NESİL ANALİZ
        mesaj_icerigi = []
        if uploaded_file:
            mesaj_icerigi.append(uploaded_file)
            
        mesaj_icerigi.append(f"Uzmanlık Alanı/Branş: {istek.brans}\nSoru: {istek.prompt}")
        
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=mesaj_icerigi
        )
        ai_cevap = response.text
        
        toplam_harcanan = girdi_token + len(ai_cevap.split())
        cursor.execute("UPDATE kullanicilar SET kullanilan_token = kullanilan_token + ? WHERE id = ?", 
                       (toplam_harcanan, user_id))
        conn.commit()

        return {
            "durum": "basarili",
            "cevap": ai_cevap, 
            "harcanan_kelime": toplam_harcanan, 
            "kalan_kota": kota - (kullanilan + toplam_harcanan),
            "file_uri": current_file_uri 
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if 'conn' in locals():
            conn.close()
