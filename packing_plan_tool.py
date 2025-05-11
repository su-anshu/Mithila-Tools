import streamlit as st
import pandas as pd
import fitz
import re
from fpdf import FPDF
from io import BytesIO
from collections import defaultdict
from datetime import datetime
import os
from sidebar import sidebar_controls, MASTER_FILE, BARCODE_PDF_PATH
from label_generator_tool import generate_combined_label_pdf

def highlight_large_qty(pdf_bytes):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    in_table = False

    for page in doc:
        text_blocks = page.get_text("blocks")

        for block in text_blocks:
            x0, y0, x1, y1, text, *_ = block

            if "Description" in text and "Qty" in text:
                in_table = True
                continue

            if in_table:
                if not any(char.isdigit() for char in text):
                    continue
                if "Qty" in text or "Unit Price" in text or "Total" in text:
                    continue

                values = text.split()
                for val in values:
                    if val.isdigit() and int(val) > 1:
                        highlight_box = fitz.Rect(x0, y0, x1, y1)
                        page.draw_rect(highlight_box, color=(1, 0, 0), fill_opacity=0.4)
                        break

            if "TOTAL" in text:
                in_table = False

    output_buffer = BytesIO()
    doc.save(output_buffer)
    output_buffer.seek(0)
    return output_buffer

def packing_plan_tool():
    st.title("📦 Packing Plan Generator (Original Orders + Physical Packing)")
    sidebar_controls()

    if not os.path.exists(MASTER_FILE):
        st.warning("No master Excel file found. Upload it via sidebar.")
        return

    master_df = pd.read_excel(MASTER_FILE)
    master_df.columns = master_df.columns.str.strip()

    with st.expander("📋 Preview Master Excel"):
        st.dataframe(master_df.head())

    pdf_files = st.file_uploader("📥 Upload One or More Invoice PDFs", type=["pdf"], accept_multiple_files=True)

    def expand_to_physical(df, master_df):
        physical_rows = []
        for _, row in df.iterrows():
            asin = row["ASIN"]
            qty = int(row["Qty"])
            match_row = master_df[master_df["ASIN"] == asin]
            if match_row.empty:
                continue
            base = match_row.iloc[0]
            split = str(base.get("Split Into", "")).strip()
            if split and split.lower() != "nan":
                name = base["Name"]
                sizes = [s.strip().replace("kg", "").strip() for s in split.split(",")]
                for size in sizes:
                    sub_match = master_df[
                        (master_df["Name"] == name) & 
                        (master_df["Net Weight"].astype(str).str.replace("kg", "").str.strip() == size)
                    ]
                    if not sub_match.empty:
                        sub = sub_match.iloc[0]
                        physical_rows.append({
                            "item": name,
                            "weight": sub["Net Weight"],
                            "Qty": qty,
                            "Packet Size": sub["Packet Size"],
                            "ASIN": sub["ASIN"],
                            "MRP": sub["M.R.P"],
                            "FNSKU": sub["FNSKU"],
                            "Packed": "",
                            "Unpacked": ""
                        })
            else:
                physical_rows.append({
                    "item": base["Name"],
                    "weight": base["Net Weight"],
                    "Qty": qty,
                    "Packet Size": base["Packet Size"],
                    "ASIN": asin,
                    "MRP": base["M.R.P"],
                    "FNSKU": base["FNSKU"],
                    "Packed": "",
                    "Unpacked": ""
                })
        df_physical = pd.DataFrame(physical_rows)
        return df_physical.groupby(
            ["item", "weight", "Packet Size", "ASIN", "MRP", "FNSKU", "Packed", "Unpacked"],
            as_index=False
        ).agg({"Qty": "sum"})

    def generate_summary_pdf(original_df, physical_df):
        pdf = FPDF()
        timestamp = datetime.now().strftime("%d %b %Y, %I:%M %p")

        def add_table(df, title, include_tracking=False, hide_asin=False):
            pdf.set_font("Arial", "B", 12)
            pdf.cell(0, 10, title, 0, 1, "C")
            pdf.set_font("Arial", "", 10)
            pdf.cell(0, 8, f"Generated on: {timestamp}", 0, 1, "C")
            pdf.ln(2)

            headers = ["Item", "Weight", "Qty", "Packet Size"]
            col_widths = [50, 20, 15, 35]

            if not hide_asin:
                headers.append("ASIN")
                col_widths.append(50)

            if include_tracking:
                headers += ["Packed", "Unpacked"]
                col_widths += [20, 20]

            margin_x = (210 - sum(col_widths)) / 2
            pdf.set_x(margin_x)
            pdf.set_font("Arial", "B", 10)
            for header, width in zip(headers, col_widths):
                pdf.cell(width, 10, header, 1, 0, "C")
            pdf.ln()

            pdf.set_font("Arial", "", 10)
            for _, row in df.iterrows():
                pdf.set_x(margin_x)
                values = [row["item"], row["weight"], row["Qty"], row["Packet Size"]]
                if not hide_asin:
                    values.append(row["ASIN"])
                if include_tracking:
                    values += [row["Packed"], row["Unpacked"]]
                for val, width in zip(values, col_widths):
                    pdf.cell(width, 10, str(val), 1)
                pdf.ln()

        pdf.add_page()
        add_table(original_df, "Original Ordered Items (from Invoice)", hide_asin=False)
        pdf.ln(5)
        add_table(physical_df, "Actual Physical Packing Plan", include_tracking=True, hide_asin=True)
        return BytesIO(pdf.output(dest="S").encode("latin1"))

    if pdf_files:
        with st.spinner("🔍 Processing invoices..."):
            asin_qty_data = defaultdict(int)
            highlighted_pdfs = {}
            asin_pattern = re.compile(r"(B0[A-Z0-9]{8})")
            qty_pattern = re.compile(r"\bQty\b.*?(\d+)")
            price_qty_pattern = re.compile(r"₹[\d,.]+\s+(\d+)\s+₹[\d,.]+")

            for uploaded_file in pdf_files:
                pdf_name = uploaded_file.name
                pdf_bytes = uploaded_file.read()
                doc = fitz.open(stream=pdf_bytes, filetype="pdf")
                pages_text = [page.get_text().split("\n") for page in doc]

                for lines in pages_text:
                    for i, line in enumerate(lines):
                        asin_match = asin_pattern.search(line)
                        if asin_match:
                            asin = asin_match.group(1)
                            qty = 1
                            for j in range(i, min(i + 4, len(lines))):
                                match = qty_pattern.search(lines[j])
                                if match:
                                    qty = int(match.group(1))
                                    break
                            if qty == 1:
                                for j in range(i, min(i + 4, len(lines))):
                                    match = price_qty_pattern.search(lines[j])
                                    if match:
                                        qty = int(match.group(1))
                                        break
                            asin_qty_data[asin] += qty

                highlighted = highlight_large_qty(pdf_bytes)
                if highlighted:
                    highlighted_pdfs[pdf_name] = highlighted

            df_orders = pd.DataFrame([{"ASIN": asin, "Qty": qty} for asin, qty in asin_qty_data.items()])
            df_orders = pd.merge(df_orders, master_df, on="ASIN", how="left")
            df_orders.rename(columns={"Name": "item", "Net Weight": "weight", "M.R.P": "MRP"}, inplace=True)
            df_orders = df_orders[["item", "weight", "Qty", "Packet Size", "ASIN", "MRP", "FNSKU"]]

            df_physical = expand_to_physical(df_orders, master_df)

            st.success("✅ Packing plan generated!")

            st.subheader("📦 Original Ordered Items (from Invoice)")
            st.dataframe(df_orders, use_container_width=True)

            st.subheader("📦 Actual Physical Packing Plan (after split)")
            st.dataframe(df_physical, use_container_width=True)

            summary_pdf = generate_summary_pdf(df_orders, df_physical)
            st.download_button("📥 Download Packing Plan PDF", data=summary_pdf, file_name="Packing_Plan.pdf", mime="application/pdf")

            excel_buffer = BytesIO()
            with pd.ExcelWriter(excel_buffer) as writer:
                df_physical.to_excel(writer, index=False, sheet_name="Physical Packing Plan")
                df_orders.to_excel(writer, index=False, sheet_name="Original Orders")
            excel_buffer.seek(0)

            st.download_button("📊 Download Excel (Both Tables)", data=excel_buffer, file_name="Packing_Plan.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

            if highlighted_pdfs:
                st.markdown("### 🔍 Highlighted Invoices")
                for name, buf in highlighted_pdfs.items():
                    st.download_button(f"📄 {name}", data=buf, file_name=f"highlighted_{name}", mime="application/pdf")

            st.markdown("### 🧾 Combined MRP + Barcode Labels")
            if not os.path.exists(BARCODE_PDF_PATH):
                st.warning("Barcode PDF not found.")
                return

            try:
                fitz.open(BARCODE_PDF_PATH)
            except Exception as e:
                st.error(f"Error opening barcode PDF: {e}")
                return

            combined_pdf = fitz.open()
            for _, row in df_physical.iterrows():
                fnsku = str(row['FNSKU']).strip()
                qty = int(row['Qty'])
                if fnsku:
                    for _ in range(qty):
                        label_pdf = generate_combined_label_pdf(pd.DataFrame([row]), fnsku, BARCODE_PDF_PATH)
                        if label_pdf:
                            combined_pdf.insert_pdf(fitz.open(stream=label_pdf.read(), filetype="pdf"))

            if len(combined_pdf):
                label_buf = BytesIO()
                combined_pdf.save(label_buf)
                label_buf.seek(0)
                st.download_button("📥 Download All Combined Labels", data=label_buf, file_name="All_Combined_Labels.pdf", mime="application/pdf")
            else:
                st.info("ℹ️ No labels generated.")
