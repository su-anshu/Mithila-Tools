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
        missing_products = []  # Track products not found or with issues
        
        for _, row in df.iterrows():
            asin = row["ASIN"]
            qty = int(row["Qty"])
            match_row = master_df[master_df["ASIN"] == asin]
            
            if match_row.empty:
                # Product not found in master file
                missing_products.append({
                    "ASIN": asin,
                    "Issue": "Not found in master file",
                    "Qty": qty
                })
                # Still add to physical plan with available info
                physical_rows.append({
                    "item": f"UNKNOWN PRODUCT ({asin})",
                    "weight": "N/A",
                    "Qty": qty,
                    "Packet Size": "N/A",
                    "ASIN": asin,
                    "MRP": "N/A",
                    "FNSKU": "MISSING",
                    "FSSAI": "",
                    "Packed Today": "",
                    "Available": "",
                    "Status": "⚠️ MISSING FROM MASTER"
                })
                continue
            
            base = match_row.iloc[0]
            split = str(base.get("Split Into", "")).strip()
            
            # Check if FNSKU is missing
            fnsku = str(base.get("FNSKU", "")).strip()
            if not fnsku or fnsku.lower() in ["nan", "none", ""]:
                missing_products.append({
                    "ASIN": asin,
                    "Issue": "Missing FNSKU",
                    "Product": base.get("Name", "Unknown"),
                    "Qty": qty
                })
            
            # Handle products with split information
            if split and split.lower() not in ["nan", "none", ""]:
                name = base["Name"]
                sizes = [s.strip().replace("kg", "").strip() for s in split.split(",")]
                split_found = False
                
                for size in sizes:
                    sub_match = master_df[
                        (master_df["Name"] == name) &
                        (master_df["Net Weight"].astype(str).str.replace("kg", "").str.strip() == size)
                    ]
                    if not sub_match.empty:
                        sub = sub_match.iloc[0]
                        sub_fnsku = str(sub.get("FNSKU", "")).strip()
                        status = "✅ READY" if sub_fnsku and sub_fnsku.lower() not in ["nan", "none", ""] else "⚠️ MISSING FNSKU"
                        
                        physical_rows.append({
                            "item": name,
                            "weight": sub["Net Weight"],
                            "Qty": qty,
                            "Packet Size": sub["Packet Size"],
                            "ASIN": sub["ASIN"],
                            "MRP": sub["M.R.P"],
                            "FNSKU": sub_fnsku if sub_fnsku and sub_fnsku.lower() not in ["nan", "none", ""] else "MISSING",
                            "FSSAI": sub.get("FSSAI", ""),
                            "Packed Today": "",
                            "Available": "",
                            "Status": status
                        })
                        split_found = True
                
                if not split_found:
                    missing_products.append({
                        "ASIN": asin,
                        "Issue": "Split sizes not found in master file",
                        "Product": name,
                        "Split Info": split,
                        "Qty": qty
                    })
            else:
                # No split information - use base product
                status = "✅ READY" if fnsku and fnsku.lower() not in ["nan", "none", ""] else "⚠️ MISSING FNSKU"
                
                physical_rows.append({
                    "item": base["Name"],
                    "weight": base["Net Weight"],
                    "Qty": qty,
                    "Packet Size": base["Packet Size"],
                    "ASIN": asin,
                    "MRP": base["M.R.P"],
                    "FNSKU": fnsku if fnsku and fnsku.lower() not in ["nan", "none", ""] else "MISSING",
                    "FSSAI": base.get("FSSAI", ""),
                    "Packed Today": "",
                    "Available": "",
                    "Status": status
                })

        df_physical = pd.DataFrame(physical_rows)
        
        if not df_physical.empty:
            # Group by all columns except Qty to sum quantities for identical items
            df_physical = df_physical.groupby(
                ["item", "weight", "Packet Size", "ASIN", "MRP", "FNSKU", "FSSAI", "Packed Today", "Available", "Status"],
                as_index=False
            ).agg({"Qty": "sum"})
        
        return df_physical, missing_products

    def generate_summary_pdf(original_df, physical_df, missing_products=None):
        pdf = FPDF()
        timestamp = datetime.now().strftime("%d %b %Y, %I:%M %p")

        # Function to clean text for PDF (remove unicode characters)
        def clean_text(text):
            if pd.isna(text):
                return ""
            text = str(text)
            # Replace common unicode characters with ASCII equivalents
            replacements = {
                '✅': '',
                '⚠️': '',
                '📦': '',
                '🚨': '',
                '•': '-'
            }
            for unicode_char, replacement in replacements.items():
                text = text.replace(unicode_char, replacement)
            # Remove any remaining non-ASCII characters
            text = text.encode('ascii', 'ignore').decode('ascii')
            return text

        def add_table(df, title, include_tracking=False, hide_asin=False):
            pdf.set_font("Arial", "B", 12)
            pdf.cell(0, 10, clean_text(title), 0, 1, "C")
            pdf.set_font("Arial", "", 10)
            pdf.cell(0, 8, f"Generated on: {timestamp}", 0, 1, "C")
            pdf.ln(2)

            headers = ["Item", "Weight", "Qty", "Packet Size"]
            col_widths = [50, 25, 20, 35]

            if not hide_asin:
                headers.append("ASIN")
                col_widths.append(50)

            if include_tracking:
                headers += ["Packed Today", "Available"]
                col_widths += [30, 30]

            margin_x = (210 - sum(col_widths)) / 2
            pdf.set_x(margin_x)
            pdf.set_font("Arial", "B", 10)
            for header, width in zip(headers, col_widths):
                pdf.cell(width, 10, clean_text(header), 1, 0, "C")
            pdf.ln()

            pdf.set_font("Arial", "", 10)
            for _, row in df.iterrows():
                pdf.set_x(margin_x)
                values = [clean_text(row["item"])[:20], clean_text(row["weight"]), str(row["Qty"]), clean_text(row["Packet Size"])[:15]]
                if not hide_asin:
                    values.append(clean_text(row["ASIN"]))
                if include_tracking:
                    values += [clean_text(row["Packed Today"]), clean_text(row["Available"])]
                    
                for val, width in zip(values, col_widths):
                    pdf.cell(width, 10, str(val), 1)
                pdf.ln()

        pdf.add_page()
        add_table(original_df, "Original Ordered Items (from Invoice)", hide_asin=False)
        pdf.ln(5)
        add_table(physical_df, "Actual Physical Packing Plan", include_tracking=True, hide_asin=True)
        
        # Use bytes output instead of string to avoid encoding issues
        output_buffer = BytesIO()
        pdf_bytes = pdf.output(dest="S")
        output_buffer.write(pdf_bytes.encode("latin1"))
        output_buffer.seek(0)
        return output_buffer

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
            df_orders = df_orders[["item", "weight", "Qty", "Packet Size", "ASIN", "MRP", "FNSKU", "FSSAI"]]

            df_physical, missing_products = expand_to_physical(df_orders, master_df)

            st.success("✅ Packing plan generated!")

            # Show alerts for missing products
            if missing_products:
                st.error("⚠️ **ATTENTION: Some products have issues!**")
                with st.expander("🚨 View Missing/Problem Products", expanded=True):
                    for issue in missing_products:
                        st.warning(f"**ASIN:** {issue['ASIN']} - **Issue:** {issue['Issue']} - **Qty:** {issue['Qty']}")
                        if 'Product' in issue:
                            st.write(f"Product: {issue['Product']}")
                        if 'Split Info' in issue:
                            st.write(f"Split Info: {issue['Split Info']}")

            st.subheader("📦 Original Ordered Items (from Invoice)")
            st.dataframe(df_orders, use_container_width=True)

            st.subheader("📦 Actual Physical Packing Plan (after split)")
            if not df_physical.empty:
                # Color code the dataframe based on status
                def highlight_status(row):
                    if row['Status'] == '⚠️ MISSING FNSKU':
                        return ['background-color: #ffcccc'] * len(row)
                    elif row['Status'] == '⚠️ MISSING FROM MASTER':
                        return ['background-color: #ff9999'] * len(row)
                    else:
                        return ['background-color: #ccffcc'] * len(row)
                
                st.dataframe(df_physical.style.apply(highlight_status, axis=1), use_container_width=True)
            else:
                st.warning("No physical packing plan generated. Check the missing products above.")

            if not df_physical.empty:
                try:
                    summary_pdf = generate_summary_pdf(df_orders, df_physical, missing_products)
                    st.download_button("📥 Download Packing Plan PDF", data=summary_pdf, file_name="Packing_Plan.pdf", mime="application/pdf")
                except Exception as e:
                    st.error(f"Error generating PDF: {str(e)}")
                    st.info("PDF generation failed, but you can still download the Excel file below.")

                excel_buffer = BytesIO()
                with pd.ExcelWriter(excel_buffer) as writer:
                    df_physical.to_excel(writer, index=False, sheet_name="Physical Packing Plan")
                    df_orders.to_excel(writer, index=False, sheet_name="Original Orders")
                    if missing_products:
                        pd.DataFrame(missing_products).to_excel(writer, index=False, sheet_name="Missing Products")
                excel_buffer.seek(0)

                st.download_button("📊 Download Excel (All Data)", data=excel_buffer, file_name="Packing_Plan.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

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

            if not df_physical.empty:
                combined_pdf = fitz.open()
                labels_generated = 0
                
                for _, row in df_physical.iterrows():
                    fnsku = str(row['FNSKU']).strip()
                    qty = int(row['Qty'])
                    
                    if fnsku and fnsku != "MISSING" and fnsku.lower() not in ["nan", "none", ""]:
                        for _ in range(qty):
                            try:
                                label_pdf = generate_combined_label_pdf(pd.DataFrame([row]), fnsku, BARCODE_PDF_PATH)
                                if label_pdf:
                                    combined_pdf.insert_pdf(fitz.open(stream=label_pdf.read(), filetype="pdf"))
                                    labels_generated += 1
                            except Exception as e:
                                st.warning(f"Could not generate label for FNSKU {fnsku}: {e}")

                if len(combined_pdf) > 0:
                    label_buf = BytesIO()
                    combined_pdf.save(label_buf)
                    label_buf.seek(0)
                    st.download_button("📥 Download All Combined Labels", data=label_buf, file_name="All_Combined_Labels.pdf", mime="application/pdf")
                    
                    st.success(f"Generated {labels_generated} labels successfully!")
                else:
                    st.warning("⚠️ No labels could be generated. Check if products have valid FNSKUs.")
            else:
                st.info("ℹ️ No labels to generate - no valid physical packing plan.")

            # === New Section: Generate MRP-only labels for items with missing FNSKU ===
            st.markdown("### 🧾 MRP-Only Labels for Non-FNSKU Items")
            from label_generator_tool import generate_pdf  # already available in your folder

            mrp_only_rows = df_physical[df_physical["FNSKU"].isin(["", "MISSING", "nan", "None", None])]

            if not mrp_only_rows.empty:
                mrp_only_pdf = fitz.open()
                mrp_only_count = 0

                for _, row in mrp_only_rows.iterrows():
                    qty = int(row["Qty"])
                    for _ in range(qty):
                        try:
                            single_label_pdf = generate_pdf(pd.DataFrame([row]))
                            if single_label_pdf:
                                mrp_only_pdf.insert_pdf(fitz.open(stream=single_label_pdf.read(), filetype="pdf"))
                                mrp_only_count += 1
                        except Exception as e:
                            st.warning(f"Failed to generate MRP label for {row['item']} — {e}")

                if len(mrp_only_pdf):
                    buf = BytesIO()
                    mrp_only_pdf.save(buf)
                    buf.seek(0)
                    st.download_button("📥 Download MRP-Only Labels", data=buf, file_name="MRP_Only_Labels.pdf", mime="application/pdf")
                    st.success(f"✅ Generated {mrp_only_count} MRP-only labels for non-FNSKU items.")
                else:
                    st.warning("⚠️ No MRP-only labels could be generated.")
            else:
                st.info("ℹ️ All items have valid FNSKUs. No separate MRP-only labels needed.")