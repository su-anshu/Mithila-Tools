import streamlit as st
import pandas as pd
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import mm
from reportlab.lib.utils import ImageReader
from io import BytesIO
from datetime import datetime
from dateutil.relativedelta import relativedelta
import random
import os
import fitz
from PIL import Image
import re
from sidebar import sidebar_controls, MASTER_FILE, BARCODE_PDF_PATH

# --- CONFIG ---
LABEL_WIDTH = 48 * mm
LABEL_HEIGHT = 25 * mm

# --- Exportable Functions for Use in Other Tools ---
def generate_pdf(dataframe):
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=(LABEL_WIDTH, LABEL_HEIGHT))
    today = datetime.today()
    mfg_date = today.strftime('%d %b %Y').upper()
    use_by = (today + relativedelta(months=6)).strftime('%d %b %Y').upper()
    date_code = today.strftime('%d%m%y')

    for _, row in dataframe.iterrows():
        name = str(row.get('Name') or row.get('item'))
        weight = str(row.get('Net Weight') or row.get('weight'))
        try:
            mrp = f"INR {int(float(row.get('M.R.P') or row.get('MRP')))}"
        except:
            mrp = "INR N/A"
        try:
            fssai = str(int(float(row.get('M.F.G. FSSAI') or row.get('FSSAI', ''))))
        except:
            fssai = "N/A"
        product_prefix = ''.join(filter(str.isalnum, name.upper()))[:2]
        batch_code = f"{product_prefix}{date_code}{str(random.randint(1, 999)).zfill(3)}"

        c.setFont("Helvetica-Bold", 6)
        c.drawString(2 * mm, 22 * mm, f"Name: {name}")
        c.drawString(2 * mm, 18 * mm, f"Net Weight: {weight} Kg")
        c.drawString(2 * mm, 14 * mm, f"M.R.P: {mrp}")
        c.drawString(2 * mm, 10 * mm, f"M.F.G: {mfg_date} | USE BY: {use_by}")
        c.drawString(2 * mm, 6 * mm, f"Batch Code: {batch_code}")
        c.drawString(2 * mm, 2 * mm, f"M.F.G. FSSAI: {fssai}")
        c.showPage()

    c.save()
    buffer.seek(0)
    return buffer

def extract_fnsku_page(fnsku_code, pdf_path):
    try:
        doc = fitz.open(pdf_path)
        for i, page in enumerate(doc):
            if fnsku_code in page.get_text():
                single_page_pdf = fitz.open()
                single_page_pdf.insert_pdf(doc, from_page=i, to_page=i)
                buffer = BytesIO()
                single_page_pdf.save(buffer)
                buffer.seek(0)
                return buffer
    except:
        return None

def generate_combined_label_pdf(mrp_df, fnsku_code, barcode_pdf_path):
    buffer = BytesIO()
    mrp_label_buffer = generate_pdf(mrp_df)
    try:
        doc = fitz.open(barcode_pdf_path)
        for page in doc:
            if fnsku_code in page.get_text():
                barcode_pix = page.get_pixmap(dpi=300)
                break
        else:
            return None
    except:
        return None

    try:
        mrp_pdf = fitz.open(stream=mrp_label_buffer.read(), filetype="pdf")
        mrp_pix = mrp_pdf[0].get_pixmap(dpi=300)
        mrp_img = Image.open(BytesIO(mrp_pix.tobytes("png")))
        barcode_img = Image.open(BytesIO(barcode_pix.tobytes("png")))
    except:
        return None

    c = canvas.Canvas(buffer, pagesize=(96 * mm, 25 * mm))
    c.drawImage(ImageReader(mrp_img), 0, 0, width=48 * mm, height=25 * mm)
    c.drawImage(ImageReader(barcode_img), 48 * mm, 0, width=48 * mm, height=25 * mm)
    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer

# --- Main App Logic ---
def label_generator_tool():
    st.title("🔖 MRP Label Generator")
    st.caption("Generate 48mm x 25mm labels with MRP, batch code, FSSAI & barcode.")
    sidebar_controls()

    def sanitize_filename(name):
        return re.sub(r'\W+', '_', name)

    def load_data():
        return pd.read_excel(MASTER_FILE)

    if os.path.exists(MASTER_FILE):
        try:
            df = load_data()
            st.subheader("🎯 Select Product & Weight")
            product_options = sorted(df['Name'].dropna().unique())
            selected_product = st.selectbox("Product", product_options)
            product_weights = sorted(df[df['Name'] == selected_product]['Net Weight'].dropna().unique())
            selected_weight = st.selectbox("Net Weight", product_weights)

            safe_name = sanitize_filename(selected_product)
            filtered_df = df[(df['Name'] == selected_product) & (df['Net Weight'] == selected_weight)]

            with st.expander("🔍 Preview Label Data"):
                st.dataframe(filtered_df)

            if not filtered_df.empty:
                label_pdf = generate_pdf(filtered_df)
                st.download_button("📥 Download MRP Label Only", data=label_pdf, file_name=f"{safe_name}_Label.pdf", mime="application/pdf")

                if 'FNSKU' in filtered_df.columns and os.path.exists(BARCODE_PDF_PATH):
                    fnsku_code = str(filtered_df.iloc[0]['FNSKU']).strip()
                    barcode = extract_fnsku_page(fnsku_code, BARCODE_PDF_PATH)
                    if barcode:
                        st.download_button("📦 Download Barcode Only", data=barcode, file_name=f"{fnsku_code}_barcode.pdf", mime="application/pdf")
                        combined = generate_combined_label_pdf(filtered_df, fnsku_code, BARCODE_PDF_PATH)
                        if combined:
                            st.download_button("🧾 Download Combined Label", data=combined, file_name=f"{safe_name}_Combined.pdf", mime="application/pdf")
                        else:
                            st.info("ℹ️ Could not generate combined label.")
                    else:
                        st.warning("⚠️ FNSKU not found in barcode PDF.")
                else:
                    st.info("ℹ️ FNSKU missing or barcode PDF not uploaded.")
            else:
                st.warning("⚠️ No matching data found.")
        except Exception as e:
            st.error(f"❌ Error: {e}")
    else:
        st.warning("⚠️ No master Excel file found. Upload it via sidebar.")
