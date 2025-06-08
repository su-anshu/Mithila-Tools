# sidebar.py
import streamlit as st
import os
from datetime import datetime
import pandas as pd
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

BARCODE_PDF_PATH = os.path.join(DATA_DIR, "master_fnsku.pdf")
MASTER_FILE = os.path.join(DATA_DIR, "temp_master.xlsx")
MANUAL_PLAN_FILE = os.path.join(DATA_DIR, "latest_packing_plan.xlsx")
META_FILE = os.path.join(DATA_DIR, "master_meta.txt")
ADMIN_PASSWORD = "admin@2025#"

def validate_file_upload(uploaded_file, expected_type, max_size_mb=50):
    """Validate uploaded files"""
    if uploaded_file is None:
        return False, "No file provided"
    
    if uploaded_file.size > max_size_mb * 1024 * 1024:
        return False, f"File too large (max {max_size_mb}MB)"
    
    if expected_type == "xlsx" and not uploaded_file.name.endswith(('.xlsx', '.xls')):
        return False, "Invalid Excel file format"
    elif expected_type == "pdf" and not uploaded_file.name.endswith('.pdf'):
        return False, "Invalid PDF file format"
    
    return True, "Valid file"

def sidebar_controls():
    """Enhanced sidebar with better error handling"""
    st.sidebar.title("🧰 Sidebar Controls")
    admin_logged_in = False
    password = st.sidebar.text_input("Admin Password", type="password")
    
    if password == ADMIN_PASSWORD:
        st.sidebar.success("✅ Admin logged in")
        admin_logged_in = True
    else:
        st.sidebar.info("Only admin can upload barcode or Excel.")

    if admin_logged_in:
        # Master Excel Upload
        st.sidebar.markdown("### 📊 Upload Master Excel")
        excel_file = st.sidebar.file_uploader("Upload `temp_master.xlsx`", type=["xlsx"], key="master_upload")
        if excel_file:
            is_valid, message = validate_file_upload(excel_file, "xlsx")
            if is_valid:
                try:
                    with open(MASTER_FILE, "wb") as f:
                        f.write(excel_file.read())
                    with open(META_FILE, "w") as meta:
                        meta.write(f"{excel_file.name}|{datetime.now().isoformat()}")
                    st.sidebar.success("✅ Master Excel uploaded!")
                    logger.info(f"Master Excel uploaded: {excel_file.name}")
                except Exception as e:
                    st.sidebar.error(f"Failed to save file: {str(e)}")
                    logger.error(f"Error saving master Excel: {str(e)}")
            else:
                st.sidebar.error(f"❌ {message}")
        
        # Display current master file info
        if os.path.exists(MASTER_FILE) and os.path.exists(META_FILE):
            try:
                meta_content = open(META_FILE).read().strip()
                if "|" in meta_content:
                    name, ts = meta_content.split("|", 1)
                    formatted_ts = pd.to_datetime(ts).strftime('%d %b %Y %I:%M %p')
                    st.sidebar.caption(f"🗂 {name} — {formatted_ts}")
                else:
                    st.sidebar.caption("🗂 Master file available")
            except Exception as e:
                st.sidebar.caption("🗂 Master file available (info unavailable)")
                logger.warning(f"Error reading meta file: {str(e)}")

        # Barcode Upload
        st.sidebar.markdown("### 📤 Upload Barcode PDF")
        barcode_file = st.sidebar.file_uploader("Upload `master_fnsku.pdf`", type=["pdf"])
        if barcode_file:
            is_valid, message = validate_file_upload(barcode_file, "pdf")
            if is_valid:
                try:
                    with open(BARCODE_PDF_PATH, "wb") as f:
                        f.write(barcode_file.read())
                    st.sidebar.success("✅ Barcode PDF uploaded")
                    logger.info(f"Barcode PDF uploaded: {barcode_file.name}")
                except Exception as e:
                    st.sidebar.error(f"Failed to save barcode: {str(e)}")
                    logger.error(f"Error saving barcode PDF: {str(e)}")
            else:
                st.sidebar.error(f"❌ {message}")
        
        # Display current barcode file info
        if os.path.exists(BARCODE_PDF_PATH):
            try:
                ts = datetime.fromtimestamp(os.path.getmtime(BARCODE_PDF_PATH)).strftime('%d %b %Y %I:%M %p')
                st.sidebar.caption(f"📦 Barcode updated: {ts}")
            except Exception as e:
                st.sidebar.caption("📦 Barcode file available")
                logger.warning(f"Error reading barcode file timestamp: {str(e)}")

        # Manual Packing Plan Upload
        st.sidebar.markdown("### 📝 Upload Manual Packing Plan Excel")
        manual_file = st.sidebar.file_uploader("Upload `latest_packing_plan.xlsx`", type=["xlsx"], key="manual_upload")
        if manual_file:
            is_valid, message = validate_file_upload(manual_file, "xlsx")
            if is_valid:
                try:
                    with open(MANUAL_PLAN_FILE, "wb") as f:
                        f.write(manual_file.read())
                    st.sidebar.success("✅ Manual Packing Plan uploaded")
                    logger.info(f"Manual packing plan uploaded: {manual_file.name}")
                except Exception as e:
                    st.sidebar.error(f"Failed to save manual plan: {str(e)}")
                    logger.error(f"Error saving manual packing plan: {str(e)}")
            else:
                st.sidebar.error(f"❌ {message}")
        
        # Display current manual plan file info
        if os.path.exists(MANUAL_PLAN_FILE):
            try:
                ts = datetime.fromtimestamp(os.path.getmtime(MANUAL_PLAN_FILE)).strftime('%d %b %Y %I:%M %p')
                st.sidebar.caption(f"📒 Manual Packing Plan updated: {ts}")
            except Exception as e:
                st.sidebar.caption("📒 Manual packing plan available")
                logger.warning(f"Error reading manual plan file timestamp: {str(e)}")

    return admin_logged_in, MASTER_FILE, BARCODE_PDF_PATH, MANUAL_PLAN_FILE
