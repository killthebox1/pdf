import warnings
warnings.filterwarnings("ignore", category=UserWarning)

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from pypdf import PdfReader
from fpdf import FPDF
import os
import re
import unicodedata
import urllib.request
import asyncio
import concurrent.futures

# Bot Token
TOKEN = "8834883881:AAEYOoaFEqWw3HtwCVl87R9UI2exXED18-s"

user_files = {}   # {user_id: pdf_path}
user_busy = {}    # {user_id: True/False}

FONT_PATH = "DejaVuSans.ttf"

# Her bölüm için özel RGB renk paleti
PART_COLORS = [
    (192, 0, 0),     # 1. ÖSYM Kodu -> Kırmızı
    (0, 102, 204),   # 2. SB Kodu -> Mavi
    (0, 128, 0),     # 3. Kurum Adı -> Yeşil
    (112, 48, 160),  # 4. Pozisyon Unvanı -> Mor
    (226, 107, 10),  # 5. İl Adı -> Turuncu
    (0, 128, 128),   # 6. Teşkilat -> Camgöbeği
    (192, 0, 128),   # 7. Pozisyon Sayısı -> Bordo
    (31, 78, 121)    # 8. Nitelik Kodları -> Lacivert
]

def ensure_font_exists():
    if not os.path.exists(FONT_PATH):
        print("DejaVuSans.ttf indiriliyor...")
        url = "https://raw.githubusercontent.com/dejavu-fonts/dejavu-fonts/master/ttf/DejaVuSans.ttf"
        try:
            urllib.request.urlretrieve(url, FONT_PATH)
            print("Font indirildi ✅")
        except Exception as e:
            print(f"Font hatası: {e}")

def normalize_text(text: str) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("İ", "i").replace("I", "ı")
    return text.lower()

# Satırı sütun alanlarına göre mantıksal parçalara ayıran parser
def parse_record_to_parts(full_record: str):
    match_start = re.match(r'^(\d{9})\s+(\d+)\s+(.+)$', full_record)
    if not match_start:
        return [full_record]

    osym_kod = match_start.group(1)
    sb_kod = match_start.group(2)
    rest = match_start.group(3)

    match_end = re.search(r'^(.*?)\s+(TAŞRA|TASRA|MERKEZ)\s+(\d+)\s+([\d\s]+)$', rest)
    if not match_end:
        return [osym_kod, sb_kod, rest]

    middle_text = match_end.group(1).strip()
    teskilat = match_end.group(2)
    sayi = match_end.group(3)
    nitelik = match_end.group(4)

    title_match = re.search(r'\s+(SAĞLIK TEKNİKERİ\s*\(.*?\)|SAĞLIK TEKNİKERİ|TEKNİKER|MÜHENDİS|HEMŞİRE|EBE|MEMUR|ŞÖFÖR|AŞÇI|HİZMETLİ)\s+', middle_text)
    
    if title_match:
        kurum_adi = middle_text[:title_match.start()].strip()
        pozisyon_unvani = title_match.group(1).strip()
        il_adi = middle_text[title_match.end():].strip()
    else:
        parts = middle_text.rsplit(' ', 1)
        if len(parts) == 2:
            kurum_adi = parts[0]
            pozisyon_unvani = ""
            il_adi = parts[1]
        else:
            kurum_adi = middle_text
            pozisyon_unvani = ""
            il_adi = ""

    return [osym_kod, sb_kod, kurum_adi, pozisyon_unvani, il_adi, teskilat, sayi, nitelik]

def search_pdf_blocking(file_path: str, keyword_norm: str, progress_callback):
    satirlar = []
    reader = PdfReader(file_path)
    total_pages = len(reader.pages)

    for idx, page in enumerate(reader.pages, 1):
        try:
            text = page.extract_text()
            if text:
                lines = text.split('\n')
                current_record = []
                
                for line in lines:
                    clean_line = line.replace('|', ' ').strip()
                    clean_line = re.sub(r'\s+', ' ', clean_line)
                    
                    if not clean_line:
                        continue
                    
                    words = clean_line.split()
                    is_new_osym_code = False
                    if words and len(words[0]) == 9 and words[0].isdigit():
                        is_new_osym_code = True

                    if is_new_osym_code or clean_line.startswith("Bu pozisyon") or "KPSS" in clean_line or "*Aranan" in clean_line or "ÖSYM KODU" in clean_line:
                        if current_record:
                            full_record = " ".join(current_record)
                            full_record = re.sub(r'\s+', ' ', full_record).strip()
                            if keyword_norm in normalize_text(full_record):
                                satirlar.append(full_record)
                            current_record = []
                    
                    if is_new_osym_code:
                        current_record.append(clean_line)
                    elif current_record and not (clean_line.startswith("Bu pozisyon") or "KPSS" in clean_line or "*Aranan" in clean_line or "ÖSYM KODU" in clean_line):
                        current_record.append(clean_line)

                if current_record:
                    full_record = " ".join(current_record)
                    full_record = re.sub(r'\s+', ' ', full_record).strip()
                    if keyword_norm in normalize_text(full_record):
                        satirlar.append(full_record)

        except Exception:
            pass
        
        progress = int((idx / total_pages) * 100)
        progress_callback(progress)

    return satirlar

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Merhaba! PDF dosyanızı gönderin. PDF gönderildikten sonra /search kelime komutunu kullanabilirsiniz.\n"
        "Örnek: /search tıbbi sekreter"
    )

async def handle_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id

    if user_busy.get(user_id, False):
        await update.message.reply_text("Önceki işlem tamamlanmadı, lütfen bekleyin.")
        return

    old_file = user_files.get(user_id)
    if old_file and os.path.exists(old_file):
        try:
            os.remove(old_file)
        except:
            pass

    try:
        file = await update.message.document.get_file()
        file_path = f"{user_id}_temp.pdf"
        await file.download_to_drive(file_path)
        user_files[user_id] = file_path
        await update.message.reply_text("PDF başarıyla alındı. Artık /search <kelime> komutunu kullanabilirsiniz.")
    except Exception as e:
        await update.message.reply_text(f"PDF alırken hata oluştu: {e}")

async def search_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id

    if user_busy.get(user_id, False):
        await update.message.reply_text("Önceki işlem tamamlanmadı, lütfen bekleyin.")
        return

    file_path = user_files.get(user_id)
    if not file_path or not os.path.exists(file_path):
        await update.message.reply_text("Lütfen önce PDF dosyanızı gönderin.")
        return

    if len(context.args) == 0:
        await update.message.reply_text("Lütfen aramak istediğiniz kelimeyi /search kelime şeklinde yazın.")
        return

    user_busy[user_id] = True
    output_path = ""
    progress_msg = None

    try:
        keyword = " ".join(context.args)
        keyword_norm = normalize_text(keyword)

        progress_msg = await update.message.reply_text("Arama başladı... %0")
        
        last_reported_progress = [0]
        loop = asyncio.get_running_loop()

        def progress_callback(progress):
            if progress >= last_reported_progress[0] + 25 or progress == 100:
                last_reported_progress[0] = progress
                asyncio.run_coroutine_threadsafe(
                    update_progress_ui(progress_msg, progress), loop
                )

        with concurrent.futures.ThreadPoolExecutor() as executor:
            satirlar = await loop.run_in_executor(
                executor, search_pdf_blocking, file_path, keyword_norm, progress_callback
            )

        if not satirlar:
            await progress_msg.edit_text(f"'{keyword}' kelimesi PDF içinde bulunamadı.")
            return

        # Sonuç PDF oluşturma
        output_path = f"{user_id}_sonuc.pdf"
        pdf_output = FPDF()
        pdf_output.add_page()

        ensure_font_exists()
        if os.path.exists(FONT_PATH):
            pdf_output.add_font('DejaVu', '', FONT_PATH)
            pdf_output.set_font('DejaVu', '', 9)
        else:
            pdf_output.set_font('Helvetica', '', 9)

        pdf_output.cell(0, 10, f"'{keyword}' kelimesi ile bulunan tüm sonuçlar", new_x="LMARGIN", new_y="NEXT", align="C")
        pdf_output.ln(5)

        # Parantezsiz, Sadece Renkli Çıktı Yazdırma
        for i, satir in enumerate(satirlar, 1):
            parts = parse_record_to_parts(satir)
            
            # SIRA NUMARASI (Siyah)
            pdf_output.set_text_color(0, 0, 0)
            pdf_output.write(5, f"{i}. ")

            # HER PARÇAYI KENDİ RENGİYLE YAZ (PARANTEZSİZ)
            for p_idx, part in enumerate(parts):
                if not part:
                    continue
                color = PART_COLORS[p_idx % len(PART_COLORS)]
                pdf_output.set_text_color(*color)
                pdf_output.write(5, f"{part} ")

            pdf_output.ln(7) # Satır arası boşluk

        pdf_output.output(output_path)

        await progress_msg.edit_text("Arama tamamlandı ✅")
        with open(output_path, "rb") as f:
            await update.message.reply_document(document=f, filename=f"{keyword}_sonuclar.pdf")

    except Exception as e:
        if progress_msg:
            await progress_msg.edit_text(f"Arama sırasında hata oluştu: {e}")
        else:
            await update.message.reply_text(f"Arama sırasında hata oluştu: {e}")

    finally:
        if output_path and os.path.exists(output_path):
            try:
                os.remove(output_path)
            except:
                pass
        user_busy[user_id] = False

async def update_progress_ui(msg, progress):
    try:
        await msg.edit_text(f"Arama devam ediyor... %{progress}")
    except Exception:
        pass

async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bilinmeyen komut. PDF gönderdikten sonra /search <kelime> kullanabilirsiniz.")

def main():
    ensure_font_exists()

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("search", search_pdf))
    app.add_handler(MessageHandler(filters.Document.PDF, handle_pdf))
    app.add_handler(MessageHandler(filters.COMMAND, unknown))

    print("Bot başarıyla başlatıldı ✅")
    app.run_polling()

if __name__ == "__main__":
    main()
