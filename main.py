import warnings
warnings.filterwarnings("ignore", category=UserWarning)

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
import pdfplumber
from fpdf import FPDF
import os
import re
import unicodedata

# BOT TOKENINIZI BURAYA YAZIN
TOKEN = "8446108598:AAHc3BHITPo-kuxjz5rzzgCjmnoTxEzL62s"

user_files = {}   # {user_id: pdf_path}
user_busy = {}    # {user_id: True/False}

# --- Normalizasyon fonksiyonu ---
def normalize_text(text: str) -> str:
    if not text:
        return ""
    # Unicode normalizasyonu
    text = unicodedata.normalize("NFKC", text)
    # Türkçe karakter düzeltmeleri
    text = text.replace("İ", "i").replace("I", "ı")
    # Küçük harfe çevir
    return text.lower()

# --- Bot komutları ---
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
        keyword = " ".join(context.args)  # çok kelimelik arama için
        keyword_norm = normalize_text(keyword)
        satirlar = []

        with pdfplumber.open(file_path) as pdf:
            total_pages = len(pdf.pages)
            progress_msg = await update.message.reply_text("Arama başladı... %0")

            for idx, sayfa in enumerate(pdf.pages, 1):
                metin = sayfa.extract_text()
                if metin:
                    for satir in metin.split("\n"):
                        temiz_satir = re.sub(r'\s+', ' ', satir).strip()
                        satir_norm = normalize_text(temiz_satir)
                        if keyword_norm in satir_norm:
                            satirlar.append(temiz_satir)

                # Yüzde ilerleme
                progress = int((idx / total_pages) * 100)
                if progress % 10 == 0:
                    try:
                        await progress_msg.edit_text(f"Arama devam ediyor... %{progress}")
                    except:
                        pass

        if not satirlar:
            await progress_msg.edit_text(f"'{keyword}' kelimesi PDF içinde bulunamadı.")
            return

        # PDF sonuç oluştur
        output_path = f"{user_id}_{keyword}_sonuclar.pdf"
        pdf_output = FPDF()
        pdf_output.add_page()
        # Font dosya adı düzeltilmiş
        pdf_output.add_font('DejaVu', '', 'DejaVuSans.ttf', uni=True)
        pdf_output.set_font('DejaVu', '', 12)
        pdf_output.cell(0, 10, f"'{keyword}' kelimesi ile bulunan tüm satırlar", ln=True, align="C")
        pdf_output.ln(5)

        for i, satir in enumerate(satirlar, 1):
            pdf_output.multi_cell(0, 8, f"{i}. {satir}")
            pdf_output.ln(1)

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
        # Geçici dosyaları mutlaka sil
        temp_file = user_files.pop(user_id, None)
        if temp_file and os.path.exists(temp_file):
            os.remove(temp_file)
        if output_path and os.path.exists(output_path):
            os.remove(output_path)
        user_busy[user_id] = False

async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bilinmeyen komut. PDF gönderdikten sonra /search <kelime> kullanabilirsiniz.")

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("search", search_pdf))
    app.add_handler(MessageHandler(filters.Document.PDF, handle_pdf))
    app.add_handler(MessageHandler(filters.COMMAND, unknown))

    print("Bot başlatıldı ✅")
    app.run_polling()

if __name__ == "__main__":
    main()
