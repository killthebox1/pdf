import warnings
warnings.filterwarnings("ignore", category=UserWarning)

import os
import re
import json
import logging
import unicodedata

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
import pdfplumber
from fpdf import FPDF

# Log ayarları
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# TELEGRAM BOT TOKEN
TOKEN = "8446108598:AAHc3BHITPo-kuxjz5rzzgCjmnoTxEzL62s"

user_files = {}   # {user_id: pdf_path}
user_busy = {}    # {user_id: True/False}

# --- JSON Veri Yükleyici ---
def load_json_data():
    json_path = os.path.join(os.path.dirname(__file__), 'veriler.json')
    if os.path.exists(json_path):
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"JSON okuma hatası: {e}")
            return {}
    return {}

# GitHub'a yüklenen veriler.json dosyası otomatik okunur
app_data = load_json_data()

# --- Normalizasyon fonksiyonu ---
def normalize_text(text: str) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("İ", "i").replace("I", "ı")
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
        keyword = " ".join(context.args)
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

                progress = int((idx / total_pages) * 100)
                if progress % 10 == 0:
                    try:
                        await progress_msg.edit_text(f"Arama devam ediyor... %{progress}")
                    except Exception:
                        pass

        if not satirlar:
            await progress_msg.edit_text(f"'{keyword}' kelimesi PDF içinde bulunamadı.")
            return

        # PDF oluşturma
        output_path = f"{user_id}_{keyword}_sonuclar.pdf"
        pdf_output = FPDF()
        pdf_output.add_page()

        font_path = os.path.join(os.path.dirname(__file__), 'DejaVuSans.ttf')
        
        if os.path.exists(font_path):
            pdf_output.add_font('DejaVu', '', font_path)
            pdf_output.set_font('DejaVu', '', 12)
        else:
            pdf_output.set_font('Helvetica', '', 12)

        header_text = f"'{keyword}' kelimesi ile bulunan tüm satırlar"
        pdf_output.cell(0, 10, header_text, new_x="LMARGIN", new_y="NEXT", align="C")
        pdf_output.ln(5)

        for i, satir in enumerate(satirlar, 1):
            pdf_output.multi_cell(0, 8, f"{i}. {satir}")
            pdf_output.ln(1)

        pdf_output.output(output_path)

        await progress_msg.edit_text("Arama tamamlandı ✅")
        with open(output_path, "rb") as f:
            await update.message.reply_document(document=f, filename=f"{keyword}_sonuclar.pdf")

    except Exception as e:
        err_msg = f"Arama sırasında hata oluştu: {e}"
        if progress_msg:
            await progress_msg.edit_text(err_msg)
        else:
            await update.message.reply_text(err_msg)

    finally:
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
