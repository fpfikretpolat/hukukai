import streamlit as st
import time
import fitz  # PyMuPDF
import os
from google import genai
from dotenv import load_dotenv
from docx import Document
from io import BytesIO
import PIL.Image
from PIL import ImageSequence

# GÜNCELLEME: 503 hatalarına karşı dirençli analiz fonksiyonu
def davayi_analiz_et(gorsel_ve_metin_listesi, secilen_prompt):
    max_deneme = 3
    bekleme_suresi = 3 # İlk hata alınırsa 3 saniye bekle
    
    for deneme in range(max_deneme):
        try:
            gonderilecek_paket = [secilen_prompt] + gorsel_ve_metin_listesi
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=gonderilecek_paket
            )
            return response.text
            
        except Exception as e:
            hata_mesaji = str(e)
            # Eğer hata 503 (Sunucu Yoğunluğu) veya 429 (Kota Aşımı) ise
            if "503" in hata_mesaji or "UNAVAILABLE" in hata_mesaji or "429" in hata_mesaji:
                if deneme < max_deneme - 1:
                    # Kullanıcıya sağ alttan şık bir bildirim verip arka planda bekliyoruz
                    st.toast(f"⚠️ Google sunucuları yoğun. {bekleme_suresi} saniye içinde otomatik tekrar deneniyor... (Deneme {deneme + 1}/{max_deneme})")
                    time.sleep(bekleme_suresi)
                    bekleme_suresi *= 2 # Bir sonraki denemede daha çok bekle (3 sn, 6 sn...)
                    continue # Döngünün başına dön ve tekrar dene
            
            # Eğer başka bir hataysa veya deneme hakkı bittiyse hatayı ekrana bas
            return f"❌ AI Analiz hatası: {hata_mesaji}\n\nLütfen 1-2 dakika bekleyip tekrar deneyin."


# --- SAYFA AYARLARI ---
st.set_page_config(page_title="Hukuk AI Asistanı", page_icon="⚖️", layout="wide")

# --- API KURULUMU ---
load_dotenv()
api_key = os.getenv("GOOGLE_API_KEY")

if not api_key:
    st.error("HATA: .env dosyasında GOOGLE_API_KEY bulunamadı! Lütfen kontrol edin.")
    st.stop()

client = genai.Client(api_key=api_key)

# --- UZMAN PROMPT KÜTÜPHANESİ ---
# Dava türlerine göre yapay zekanın beynini değiştiren sözlük
DAVA_PROMPTLARI = {
    "Ceza Hukuku (Ağır Ceza / Asliye)": """
        Sen uzman bir Türk Ceza Avukatısın. Dosyadaki ifadeler, HTS kayıtları, kamera görüntüleme tutanakları ve bilirkişi raporları arasındaki MADDİ ÇELİŞKİLERİ bul.
        Zaman, mekan, silah türü ve kişi teşhislerindeki uyumsuzluklara odaklan. 
        Analizini 3 başlıkta yap: 1. Olay Özeti, 2. Tespit Edilen Çelişkiler, 3. Hukuki Risk ve Savunma Stratejisi (Beraat/İndirim sebepleri).
    """,
    "Aile Hukuku (Boşanma / Velayet)": """
        Sen uzman bir Türk Aile Hukuku Avukatısın. Boşanma dosyalarındaki dilekçeler, tanık beyanları, mesaj kayıtları ve banka dökümlerini incele.
        Özellikle KUSUR tespiti (sadakatsizlik, şiddet, ekonomik baskı) için tanık beyanlarındaki tutarsızlıkları ve yalanları bul. 
        Analizini 3 başlıkta yap: 1. Uyuşmazlık Özeti, 2. İddia ve Tanık Beyanlarındaki Çelişkiler, 3. Nafaka, Tazminat ve Velayet İçin Risk/Strateji Analizi.
    """,
    "Miras Hukuku (Muris Muvazaası / Tenkis)": """
        Sen uzman bir Türk Miras Hukuku Avukatısın. Dosyadaki tapu senetleri, resmi vasiyetnameler, banka dekontları ve nüfus kayıtlarını çapraz incele.
        Gerçek bedel ile tapuda gösterilen bedel arasındaki uçurumları, mal kaçırma (muris muvazaası) kastını ve saklı pay (tenkis) ihlallerini bul.
        Analizini 3 başlıkta yap: 1. Dava Özeti, 2. Belge ve Bedel Çelişkileri (Muvazaa Tespiti), 3. Hukuki Risk ve İspat Stratejisi.
    """,
    "Borçlar ve Ticaret Hukuku (Alacak / Sözleşme)": """
        Sen uzman bir Türk Ticaret ve Borçlar Hukuku Avukatısın. Ticari defterler, faturalar, sözleşme maddeleri, sevk irsaliyeleri ve ihtarnameleri incele.
        Temerrüt tarihlerindeki hataları, sözleşmeye aykırılıkları, imza inkarını ve faiz başlangıç tarihlerindeki tutarsızlıkları tespit et.
        Analizini 3 başlıkta yap: 1. Sözleşme/İhtilaf Özeti, 2. Belge ve Beyan Çelişkileri, 3. Zamanaşımı/Hak Düşürücü Süre Riskleri ve Dava Stratejisi.
    """,
    "İcra ve İflas Hukuku (İlamsız/İlamlı Takip)": """
        Sen uzman bir Türk İcra ve İflas Hukuku Avukatısın. Dosyadaki takip taleplerini, ödeme/icra emirlerini, tebligat mazbatalarını, itiraz dilekçelerini ve hesap özetlerini çok dikkatli incele.
        Özellikle şu usul hatalarını ve çelişkileri ara: Tebligat Kanunu'na aykırı (usulsüz) tebligat yapılıp yapılmadığı, 7 günlük hak düşürücü itiraz sürelerinin kaçırılıp kaçırılmadığı, takip talebi ile ödeme emri arasındaki bedel/faiz uyuşmazlıkları ve yetkisiz icra dairesi seçimi.
        Analizini 3 başlıkta yap: 1. İcra Dosyası Özeti, 2. Tespit Edilen Usul Hataları ve Çelişkiler (Tebligat, Süre, Faiz Oranları), 3. Hukuki Risk ve Şikayet/İtiraz Stratejisi (İmzaya veya Borca İtiraz).
    """
}

# --- FONKSİYONLAR ---
def dosya_isleyici(yuklenen_dosyalar):
    islenmis_icerik = []
    for dosya in yuklenen_dosyalar:
        dosya_adi = dosya.name.lower()
        islenmis_icerik.append(f"\n\n{'='*50}\n📁 DOSYA KAYNAĞI: {dosya.name}\n{'='*50}\n")
        try:
            if dosya_adi.endswith(".pdf"):
                doc = fitz.open(stream=dosya.read(), filetype="pdf")
                for sayfa in doc:
                    metin = sayfa.get_text().strip()
                    if len(metin) > 20:
                        islenmis_icerik.append(f"\n--- {dosya.name} / SAYFA {sayfa.number + 1} ---\n")
                        islenmis_icerik.append(metin)
                    else:
                        st.toast(f"📸 {dosya.name} - Sayfa {sayfa.number + 1} resim olarak taranıyor...")
                        pix = sayfa.get_pixmap(dpi=150) 
                        img = PIL.Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                        islenmis_icerik.append(f"\n--- {dosya.name} / SAYFA {sayfa.number + 1} (GÖRSEL TARAMA) ---\n")
                        islenmis_icerik.append(img)
            
            elif dosya_adi.endswith((".tif", ".tiff", ".jpg", ".jpeg", ".png")):
                st.toast(f"🖼️ {dosya.name} görüntü dosyası işleniyor...")
                img = PIL.Image.open(dosya)
                if hasattr(img, "n_frames") and img.n_frames > 1:
                    for i, frame in enumerate(ImageSequence.Iterator(img)):
                        islenmis_icerik.append(f"\n--- {dosya.name} / SAYFA {i + 1} ---\n")
                        islenmis_icerik.append(frame.convert("RGB"))
                else:
                    islenmis_icerik.append(f"\n--- {dosya.name} ---\n")
                    islenmis_icerik.append(img.convert("RGB"))
                    
        except Exception as e:
            st.error(f"❌ '{dosya.name}' okuma hatası: {e}")
    return islenmis_icerik

# GÜNCELLEME: Artık seçilen prompt dışarıdan parametre olarak geliyor
def davayi_analiz_et(gorsel_ve_metin_listesi, secilen_prompt):
    try:
        gonderilecek_paket = [secilen_prompt] + gorsel_ve_metin_listesi
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=gonderilecek_paket
        )
        return response.text
    except Exception as e:
        return f"❌ AI Analiz hatası: {e}"

def word_olustur(rapor_metni):
    doc = Document()
    doc.add_heading('Hukuki Analiz Raporu', 0)
    doc.add_paragraph(rapor_metni)
    buffer = BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer

# --- HAFIZA (SESSION STATE) AYARI ---
if "analiz_sonucu" not in st.session_state:
    st.session_state.analiz_sonucu = None

# --- ARAYÜZ (UI) BAŞLANGICI ---
st.title("⚖️ Hukuk AI Asistanı (Çoklu Branş)")
st.markdown("Farklı hukuk dallarına özel uzmanlaşmış yapay zeka ile çapraz dosya analizi.")

# YENİ: SOL MENÜDE DAVA TÜRÜ SEÇİMİ
st.sidebar.header("⚙️ Analiz Ayarları")
secilen_kategori = st.sidebar.selectbox(
    "Dava Türünü Seçin",
    options=list(DAVA_PROMPTLARI.keys()),
    index=0
)

st.sidebar.markdown("---")
st.sidebar.success("✅ Sistem Aktif: gemini-2.5-flash")
st.sidebar.info(f"🧠 Aktif Uzmanlık: **{secilen_kategori}**")

yuklenen_dosyalar = st.file_uploader(
    "Dosyaları (PDF, TIF, JPG, PNG) buraya sürükleyin", 
    type=["pdf", "tif", "tiff", "jpg", "jpeg", "png"], 
    accept_multiple_files=True
)

if yuklenen_dosyalar:
    st.info(f"📂 {len(yuklenen_dosyalar)} dosya eklendi. Analiz Modu: **{secilen_kategori}**")
    
    if st.button("Seçili Branşta Analiz Et", type="primary", use_container_width=True):
        with st.spinner(f"⏳ Yapay zeka {secilen_kategori} uzmanı olarak dosyaları okuyor..."):
            
            islenmis_icerik = dosya_isleyici(yuklenen_dosyalar)
            
            if islenmis_icerik:
                # GÜNCELLEME: Seçilen kategoriye ait promptu fonksiyona gönderiyoruz
                aktif_prompt = DAVA_PROMPTLARI[secilen_kategori]
                st.session_state.analiz_sonucu = davayi_analiz_et(islenmis_icerik, aktif_prompt)

# --- SONUÇ GÖSTERİMİ VE İNDİRME EKRANI ---
if st.session_state.analiz_sonucu:
    
    # EĞER SONUÇ BİR HATA MESAJIYSA (Başında ❌ varsa)
    if st.session_state.analiz_sonucu.startswith("❌"):
        st.error("Sistem şu anda yanıt veremedi. Lütfen birazdan tekrar deneyin.")
        st.warning(st.session_state.analiz_sonucu) # Hatayı sarı kutuda göster
        
    # EĞER SONUÇ GERÇEK BİR ANALİZSE (Başarı durumu)
    else:
        st.success("✅ Analiz Tamamlandı!")
        st.markdown("---")
        
        st.markdown(st.session_state.analiz_sonucu)
        st.markdown("---")
        
        word_dosyasi = word_olustur(st.session_state.analiz_sonucu)
        
        st.download_button(
            label="📄 Raporu Word Dosyası Olarak İndir",
            data=word_dosyasi,
            file_name="hukuki_analiz_raporu.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            use_container_width=True
        )
