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
import contextlib
import logging
from sidebar import sidebar_controls, MASTER_FILE, BARCODE_PDF_PATH

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- CONFIG ---
LABEL_WIDTH = 48 * mm
LABEL_HEIGHT = 25 * mm

# Utility functions
def is_empty_value(value):
    """Standardized check for empty/invalid values"""
    if pd.isna(value):
        return True
    if value is None:
        return True
    str_value = str(value).strip().lower()
    return str_value in ["", "nan", "none", "null", "n/a"]

@contextlib.contextmanager
def safe_pdf_context(pdf_bytes):
    """Context manager for safe PDF handling"""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        yield doc
    finally:
        doc.close()

# --- Exportable Functions for Use in Other Tools ---
def generate_pdf(dataframe):
    """Generate MRP labels with improved error handling"""
    try:
        buffer = BytesIO()
        c = canvas.Canvas(buffer, pagesize=(LABEL_WIDTH, LABEL_HEIGHT))
        today = datetime.today()
        mfg_date = today.strftime('%d %b %Y').upper()
        use_by = (today + relativedelta(months=6)).strftime('%d %b %Y').upper()
        date_code = today.strftime('%d%m%y')

        for _, row in dataframe.iterrows():
            # Safe data extraction
            name = str(row.get('Name') or row.get('item', 'Unknown Product'))
            weight = str(row.get('Net Weight') or row.get('weight', 'N/A'))
            
            # Safer MRP conversion
            try:
                mrp_value = row.get('M.R.P') or row.get('MRP')
                if is_empty_value(mrp_value):
                    mrp = "INR N/A"
                else:
                    mrp = f"INR {int(float(mrp_value))}"
            except (ValueError, TypeError, AttributeError):
                mrp = "INR N/A"
            
            # Safer FSSAI conversion
            try:
                fssai_value = row.get('M.F.G. FSSAI') or row.get('FSSAI', '')
                if is_empty_value(fssai_value):
                    fssai = "N/A"
                else:
                    fssai = str(int(float(fssai_value)))
            except (ValueError, TypeError, AttributeError):
                fssai = "N/A"
            
            # Generate batch code
            try:
                product_prefix = ''.join(filter(str.isalnum, name.upper()))[:2]
                if not product_prefix:
                    product_prefix = "XX"
                batch_code = f"{product_prefix}{date_code}{str(random.randint(1, 999)).zfill(3)}"
            except Exception:
                batch_code = f"XX{date_code}001"

            # Draw label content
            try:
                c.setFont("Helvetica-Bold", 6)
                c.drawString(2 * mm, 22 * mm, f"Name: {name[:30]}")  # Truncate long names
                c.drawString(2 * mm, 18 * mm, f"Net Weight: {weight} Kg")
                c.drawString(2 * mm, 14 * mm, f"M.R.P: {mrp}")
                c.drawString(2 * mm, 10 * mm, f"M.F.G: {mfg_date} | USE BY: {use_by}")
                c.drawString(2 * mm, 6 * mm, f"Batch Code: {batch_code}")
                c.drawString(2 * mm, 2 * mm, f"FSSAI: {fssai}")
                c.showPage()
            except Exception as e:
                logger.error(f"Error drawing label content: {str(e)}")
                # Create a basic error label
                c.setFont("Helvetica-Bold", 8)
                c.drawString(2 * mm, 12 * mm, "ERROR GENERATING LABEL")
                c.drawString(2 * mm, 8 * mm, f"Product: {name[:20]}")
                c.showPage()

        c.save()
        buffer.seek(0)
        return buffer
    except Exception as e:
        logger.error(f"Error generating PDF: {str(e)}")
        return None

def extract_fnsku_page(fnsku_code, pdf_path):
    """Extract FNSKU page from barcode PDF with improved error handling"""
    try:
        if not os.path.exists(pdf_path):
            logger.error(f"Barcode PDF not found: {pdf_path}")
            return None
            
        with open(pdf_path, 'rb') as f:
            pdf_bytes = f.read()
            
        with safe_pdf_context(pdf_bytes) as doc:
            for i, page in enumerate(doc):
                try:
                    page_text = page.get_text()
                    if fnsku_code in page_text:
                        single_page_pdf = fitz.open()
                        single_page_pdf.insert_pdf(doc, from_page=i, to_page=i)
                        buffer = BytesIO()
                        single_page_pdf.save(buffer)
                        buffer.seek(0)
                        single_page_pdf.close()
                        return buffer
                except Exception as e:
                    logger.warning(f"Error processing page {i}: {str(e)}")
                    continue
        
        logger.warning(f"FNSKU {fnsku_code} not found in barcode PDF")
        return None
    except Exception as e:
        logger.error(f"Error extracting FNSKU page: {str(e)}")
        return None

def generate_combined_label_pdf(mrp_df, fnsku_code, barcode_pdf_path):
    """Generate combined MRP + barcode label with improved error handling"""
    try:
        buffer = BytesIO()
        
        # Generate MRP label
        mrp_label_buffer = generate_pdf(mrp_df)
        if not mrp_label_buffer:
            logger.error("Failed to generate MRP label")
            return None
        
        # Extract barcode from PDF
        if not os.path.exists(barcode_pdf_path):
            logger.error(f"Barcode PDF not found: {barcode_pdf_path}")
            return None
            
        try:
            with open(barcode_pdf_path, 'rb') as f:
                barcode_pdf_bytes = f.read()
                
            with safe_pdf_context(barcode_pdf_bytes) as doc:
                barcode_pix = None
                for page in doc:
                    try:
                        page_text = page.get_text()
                        if fnsku_code in page_text:
                            barcode_pix = page.get_pixmap(dpi=300)
                            break
                    except Exception as e:
                        logger.warning(f"Error processing barcode page: {str(e)}")
                        continue
                
                if not barcode_pix:
                    logger.warning(f"FNSKU {fnsku_code} not found in barcode PDF")
                    return None
        except Exception as e:
            logger.error(f"Error opening barcode PDF: {str(e)}")
            return None

        try:
            # Convert PDFs to images
            with safe_pdf_context(mrp_label_buffer.read()) as mrp_pdf:
                mrp_pix = mrp_pdf[0].get_pixmap(dpi=300)
            
            mrp_img = Image.open(BytesIO(mrp_pix.tobytes("png")))
            barcode_img = Image.open(BytesIO(barcode_pix.tobytes("png")))
        except Exception as e:
            logger.error(f"Error converting to images: {str(e)}")
            return None

        try:
            # Create combined label
            c = canvas.Canvas(buffer, pagesize=(96 * mm, 25 * mm))
            c.drawImage(ImageReader(mrp_img), 0, 0, width=48 * mm, height=25 * mm)
            c.drawImage(ImageReader(barcode_img), 48 * mm, 0, width=48 * mm, height=25 * mm)
            c.showPage()
            c.save()
            buffer.seek(0)
            return buffer
        except Exception as e:
            logger.error(f"Error creating combined label: {str(e)}")
            return None
            
    except Exception as e:
        logger.error(f"Unexpected error in generate_combined_label_pdf: {str(e)}")
        return None

# --- Main App Logic ---
def label_generator_tool():
    st.title("🔖 MRP Label Generator")
    st.caption("Generate 48mm x 25mm labels with MRP, batch code, FSSAI & barcode.")
    sidebar_controls()

    def sanitize_filename(name):
        """Sanitize filename for safe file operations"""
        return re.sub(r'[^\w\-_\.]', '_', str(name))

    def load_data():
        """Load master data with error handling"""
        try:
            if not os.path.exists(MASTER_FILE):
                return None
            df = pd.read_excel(MASTER_FILE)
            df.columns = df.columns.str.strip()
            return df
        except Exception as e:
            logger.error(f"Error loading master data: {str(e)}")
            st.error(f"Error loading master data: {str(e)}")
            return None

    # Load and validate data
    df = load_data()
    if df is None:
        st.warning("⚠️ No master Excel file found. Upload it via sidebar.")
        return
    
    if df.empty:
        st.warning("⚠️ Master Excel file is empty.")
        return
    
    # Check required columns
    required_columns = ['Name']
    missing_columns = [col for col in required_columns if col not in df.columns]
    if missing_columns:
        st.error(f"Missing required columns in master file: {missing_columns}")
        return

    try:
        st.subheader("🎯 Select Product & Weight")
        
        # Product selection with error handling
        product_options = []
        if 'Name' in df.columns:
            product_options = sorted(df['Name'].dropna().unique())
        
        if not product_options:
            st.warning("No products found in master file.")
            return
            
        selected_product = st.selectbox("Product", product_options)
        
        # Weight selection
        weight_options = []
        if 'Net Weight' in df.columns:
            product_df = df[df['Name'] == selected_product]
            weight_options = sorted(product_df['Net Weight'].dropna().unique())
        
        if not weight_options:
            st.warning(f"No weight options found for {selected_product}")
            return
            
        selected_weight = st.selectbox("Net Weight", weight_options)

        # Filter data
        filtered_df = df[
            (df['Name'] == selected_product) & 
            (df['Net Weight'] == selected_weight)
        ]

        with st.expander("🔍 Preview Label Data"):
            st.dataframe(filtered_df)

        if not filtered_df.empty:
            safe_name = sanitize_filename(selected_product)
            
            # Generate MRP label
            try:
                label_pdf = generate_pdf(filtered_df)
                if label_pdf:
                    st.download_button(
                        "📥 Download MRP Label Only", 
                        data=label_pdf, 
                        file_name=f"{safe_name}_Label.pdf", 
                        mime="application/pdf"
                    )
                else:
                    st.error("Failed to generate MRP label")
            except Exception as e:
                st.error(f"Error generating MRP label: {str(e)}")

            # Barcode and combined label section
            if 'FNSKU' in filtered_df.columns and os.path.exists(BARCODE_PDF_PATH):
                try:
                    fnsku_code = str(filtered_df.iloc[0]['FNSKU']).strip()
                    
                    if not is_empty_value(fnsku_code):
                        # Extract barcode
                        barcode = extract_fnsku_page(fnsku_code, BARCODE_PDF_PATH)
                        if barcode:
                            st.download_button(
                                "📦 Download Barcode Only", 
                                data=barcode, 
                                file_name=f"{fnsku_code}_barcode.pdf", 
                                mime="application/pdf"
                            )
                            
                            # Generate combined label
                            combined = generate_combined_label_pdf(filtered_df, fnsku_code, BARCODE_PDF_PATH)
                            if combined:
                                st.download_button(
                                    "🧾 Download Combined Label", 
                                    data=combined, 
                                    file_name=f"{safe_name}_Combined.pdf", 
                                    mime="application/pdf"
                                )
                            else:
                                st.warning("⚠️ Could not generate combined label.")
                        else:
                            st.warning(f"⚠️ FNSKU {fnsku_code} not found in barcode PDF.")
                    else:
                        st.warning("⚠️ FNSKU is missing for this product.")
                except Exception as e:
                    st.error(f"Error processing barcode: {str(e)}")
            else:
                if 'FNSKU' not in filtered_df.columns:
                    st.info("ℹ️ FNSKU column not found in master data.")
                elif not os.path.exists(BARCODE_PDF_PATH):
                    st.info("ℹ️ Barcode PDF not uploaded via sidebar.")
                else:
                    st.info("ℹ️ FNSKU missing or barcode PDF not available.")
        else:
            st.warning("⚠️ No matching data found for selected product and weight.")
            
    except Exception as e:
        logger.error(f"Unexpected error in label generator: {str(e)}")
        st.error(f"❌ An unexpected error occurred: {str(e)}")
