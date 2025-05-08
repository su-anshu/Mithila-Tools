def packing_plan_tool():
    import streamlit as st
    import pandas as pd
    import fitz
    import re
    from fpdf import FPDF
    from io import BytesIO
    from collections import defaultdict
    import os
    from sidebar import sidebar_controls, MASTER_FILE, BARCODE_PDF_PATH
    from label_generator_tool import generate_pdf, extract_fnsku_page, generate_combined_label_pdf

    # --- Title & Sidebar ---
    st.title("📦 Packing Plan Generator and Multiple Quantity Highlighter")
    sidebar_controls()

    # --- Load Master Excel ---
    if not os.path.exists(MASTER_FILE):
        st.warning("No master Excel file found. Upload it via sidebar.")
        return

    master_df = pd.read_excel(MASTER_FILE)
    with st.expander("📋 Preview Master Excel"):
        st.dataframe(master_df.head())

    # --- Multi-PDF Upload ---
    pdf_files = st.file_uploader("📥 Upload One or More Invoice PDFs", type=["pdf"], accept_multiple_files=True)

    # --- Highlight Function ---
    def highlight_large_qty(pdf_bytes):
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        found = False
        for page in doc:
            text_blocks = page.get_text("blocks")
            in_table = False
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
                            found = True
                            break
                if "TOTAL" in text:
                    in_table = False
        if not found:
            return None
        output_buffer = BytesIO()
        doc.save(output_buffer)
        output_buffer.seek(0)
        return output_buffer

    # --- Process PDFs ---
    if pdf_files:
        with st.spinner("Processing all invoices..."):
            asin_qty_data = defaultdict(int)
            highlighted_pdfs = {}

            asin_pattern = re.compile(r"(B0[A-Z0-9]{8})")
            qty_hint_pattern = re.compile(r"\bQty\b.*?(\d+)")
            implicit_qty_pattern = re.compile(r"₹[\d,.]+\s+(\d+)\s+₹[\d,.]+")

            for uploaded_file in pdf_files:
                pdf_name = uploaded_file.name
                pdf_bytes = uploaded_file.read()
                doc = fitz.open(stream=pdf_bytes, filetype="pdf")
                lines_by_page = [page.get_text().split("\n") for page in doc]

                for lines in lines_by_page:
                    for i, line in enumerate(lines):
                        asin_match = asin_pattern.search(line)
                        if asin_match:
                            asin = asin_match.group(1)
                            qty = 1
                            for j in range(i, min(i + 4, len(lines))):
                                match = qty_hint_pattern.search(lines[j])
                                if match:
                                    qty = int(match.group(1))
                                    break
                            if qty == 1:
                                for j in range(i, min(i + 4, len(lines))):
                                    match = implicit_qty_pattern.search(lines[j])
                                    if match:
                                        qty = int(match.group(1))
                                        break
                            asin_qty_data[asin] += qty

                # Generate and store highlighted PDF if qty > 1 found
                highlighted = highlight_large_qty(pdf_bytes)
                if highlighted:
                    highlighted_pdfs[pdf_name] = highlighted

            # Build packing plan
            extracted_df = pd.DataFrame([{"ASIN": asin, "Qty": qty} for asin, qty in asin_qty_data.items()])
            packing_plan_df = pd.merge(extracted_df, master_df, on="ASIN", how="left")

            packing_plan_df.rename(columns={
                "Name": "item",
                "Net Weight": "weight",
                "M.R.P": "MRP"
            }, inplace=True)

            packing_plan_df = packing_plan_df[["item", "weight", "Qty", "Packet Size", "ASIN", "MRP", "FNSKU"]]
            st.success("✅ Packing plan generated!")
            st.dataframe(packing_plan_df, use_container_width=True)

            # --- Packing Summary PDF (Centered Table) ---
            def generate_summary_pdf(dataframe):
                pdf = FPDF()
                pdf.add_page()
                pdf.set_font("Arial", "B", 12)
                pdf.cell(0, 10, "Packing Plan Summary", 0, 1, "C")

                headers = ["Item", "Weight", "Qty", "Packet Size", "ASIN"]
                col_widths = [50, 20, 10, 25, 85]  # Adjusted widths to fit page
                total_width = sum(col_widths)
                margin_x = (210 - total_width) / 2  # Center align on A4 (210mm)

                pdf.set_x(margin_x)
                pdf.set_font("Arial", "B", 10)
                for i, header in enumerate(headers):
                    pdf.cell(col_widths[i], 10, header, 1, 0, "C")
                pdf.ln()

                pdf.set_font("Arial", "", 10)
                for _, row in dataframe.iterrows():
                    pdf.set_x(margin_x)
                    pdf.cell(col_widths[0], 10, str(row["item"]), 1)
                    pdf.cell(col_widths[1], 10, str(row["weight"]), 1)
                    pdf.cell(col_widths[2], 10, str(row["Qty"]), 1)
                    pdf.cell(col_widths[3], 10, str(row["Packet Size"]), 1)
                    pdf.cell(col_widths[4], 10, str(row["ASIN"]), 1)
                    pdf.ln()

                pdf_bytes = pdf.output(dest="S").encode("latin1")
                return BytesIO(pdf_bytes)

            pdf_buffer = generate_summary_pdf(packing_plan_df)
            st.download_button("📥 Download Consolidated Packing Plan PDF", data=pdf_buffer, file_name="Packing_Plan.pdf", mime="application/pdf")

            # --- Highlighted PDFs Download ---
            if highlighted_pdfs:
                st.markdown("### 🔍 Highlighted Invoices (Qty > 1)")
                for name, pdf_io in highlighted_pdfs.items():
                    st.download_button(f"📄 {name}", data=pdf_io, file_name=f"highlighted_{name}", mime="application/pdf")

            # --- Combine All Labels (Qty-wise) into One PDF ---
            st.markdown("### 🧾 All-in-One Combined MRP + Barcode Labels (Qty-wise)")
            combined_pages = []

            for index, row in packing_plan_df.iterrows():
                row_df = pd.DataFrame([row])
                fnsku_code = str(row['FNSKU']).strip()
                qty = int(row['Qty'])

                if fnsku_code and os.path.exists(BARCODE_PDF_PATH):
                    for _ in range(qty):
                        combined_pdf = generate_combined_label_pdf(row_df, fnsku_code, BARCODE_PDF_PATH)
                        if combined_pdf:
                            combined_pages.append(fitz.open(stream=combined_pdf.read(), filetype="pdf"))

            if combined_pages:
                final_pdf = fitz.open()
                for pdf in combined_pages:
                    final_pdf.insert_pdf(pdf)

                final_buffer = BytesIO()
                final_pdf.save(final_buffer)
                final_buffer.seek(0)

                st.download_button(
                    label="📥 Download All Combined MRP + Barcode Labels (Qty-wise)",
                    data=final_buffer,
                    file_name="All_Combined_Labels.pdf",
                    mime="application/pdf"
                )
            else:
                st.info("ℹ️ No combined labels generated.")
