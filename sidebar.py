# sidebar.py
import streamlit as st
import os
from datetime import datetime
import pandas as pd

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

BARCODE_PDF_PATH = os.path.join(DATA_DIR, "master_fnsku.pdf")
MASTER_FILE = os.path.join(DATA_DIR, "temp_master.xlsx")
META_FILE = os.path.join(DATA_DIR, "master_meta.txt")
ADMIN_PASSWORD = "admin123"

def sidebar_controls():
    st.sidebar.title("🧰 Sidebar Controls")
    admin_logged_in = False
    password = st.sidebar.text_input("Admin Password", type="password")
    if password == ADMIN_PASSWORD:
        st.sidebar.success("✅ Admin logged in")
        admin_logged_in = True
    else:
        st.sidebar.info("Only admin can upload barcode or Excel.")

    if admin_logged_in:
        # Excel Upload
        st.sidebar.markdown("### 📊 Upload Master Excel")
        excel_file = st.sidebar.file_uploader("Upload `temp_master.xlsx`", type=["xlsx"])
        if excel_file:
            with open(MASTER_FILE, "wb") as f:
                f.write(excel_file.read())
            with open(META_FILE, "w") as meta:
                meta.write(f"{excel_file.name}|{datetime.now().isoformat()}")
            st.sidebar.success("✅ Master Excel uploaded!")
        if os.path.exists(MASTER_FILE) and os.path.exists(META_FILE):
            name, ts = open(META_FILE).read().split("|")
            st.sidebar.caption(f"🗂 {name} — {pd.to_datetime(ts).strftime('%d %b %Y %I:%M %p')}")

        # Barcode Upload
        st.sidebar.markdown("### 📤 Upload Barcode PDF")
        barcode_file = st.sidebar.file_uploader("Upload `master_fnsku.pdf`", type=["pdf"])
        if barcode_file:
            with open(BARCODE_PDF_PATH, "wb") as f:
                f.write(barcode_file.read())
            st.sidebar.success("✅ Barcode PDF uploaded")
        if os.path.exists(BARCODE_PDF_PATH):
            ts = datetime.fromtimestamp(os.path.getmtime(BARCODE_PDF_PATH)).strftime('%d %b %Y %I:%M %p')
            st.sidebar.caption(f"📦 Barcode updated: {ts}")

    return admin_logged_in
