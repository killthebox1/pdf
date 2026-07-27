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

# Senkron PDF Arama Fonksiyonu
def search_pdf_blocking(file_path: str, keyword_norm: str, progress_callback):
    satirlar = []
    reader = PdfReader(file_path)
    total_pages = len(reader.pages)

    for idx, page in enumerate(reader.pages, 1):
        try:
            # Metni fiziksel sayfa düzenini koruyarak (layout mode) çıkarıyoruz
            metin = page.extract_text(extraction_mode="layout")
            if not metin:
                metin = page.extract_text() # Yedek çıkarma yöntemi

            if metin:
                # Boş satırları temizleyip listeye al
                raw_lines = [l.strip() for l in metin.split("\n") if l.strip()]
                
                for i, satir in enumerate(raw_lines):
                    # Boşlukları düzenle
                    temiz_satir = re.sub(r'\s+', ' ', satir).strip()
                    satir_norm = normalize_text(temiz_satir)
                    
                    if keyword_norm in satir_norm:
                        # Eğer bulunan satır çok kısaysa veya bilgi üst/alt satıra taşmışsa bağlamı koru
                        tam_satir = temiz_satir
                        
                        # Üst satırda kod veya başlık varsa ekle (Satır başı kontrolü)
                        if i > 0 and len(raw_lines[i-1]) < 80:
                            ust_satir = re.sub(r'\s+', ' ', raw_lines[i-1]).strip()
                            # Eğer üst satır zaten eklenmediyse başa birleştir
                            if ust_satir not in tam_satir:
                                tam_satir = f"{ust_satir} | {tam_satir}"

                        satirlar.append(tam_satir)
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
            pdf_output.set_font('DejaVu', '', 11)
        else:
            pdf_output.set_font('Helvetica', '', 11)

        pdf_output.cell(0, 10, f"'{keyword}' kelimesi ile bulunan tüm satırlar", new_x="LMARGIN", new_y="NEXT", align="C")
        pdf_output.ln(5)

        for i, satir in enumerate(satirlar, 1):
            pdf_output.multi_cell(0, 7, f"{i}. {satir}")
            pdf_output.ln(2)

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
