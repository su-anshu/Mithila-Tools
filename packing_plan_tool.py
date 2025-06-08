import streamlit as st
import pandas as pd
import fitz
import re
from fpdf import FPDF
from io import BytesIO
from collections import defaultdict
from datetime import datetime
import os
import contextlib
import logging
from sidebar import sidebar_controls, MASTER_FILE, BARCODE_PDF_PATH
from label_generator_tool import generate_combined_label_pdf, generate_pdf

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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

def validate_uploaded_file(uploaded_file, max_size_mb=50):
    """Validate uploaded files before processing"""
    if uploaded_file is None:
        return False, "No file uploaded"
    
    if uploaded_file.size > max_size_mb * 1024 * 1024:
        return False, f"File too large (max {max_size_mb}MB)"
    
    if uploaded_file.type not in ['application/pdf']:
        return False, "Invalid file type - only PDF files allowed"
    
    return True, "Valid file"

def highlight_large_qty(pdf_bytes):
    """Highlight large quantities in PDF invoices"""
    try:
        with safe_pdf_context(pdf_bytes) as doc:
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
    except Exception as e:
        logger.error(f"Error highlighting PDF: {str(e)}")
        return None

def packing_plan_tool():
    st.title("📦 Packing Plan Generator (Original Orders + Physical Packing)")
    sidebar_controls()

    if not os.path.exists(MASTER_FILE):
        st.warning("No master Excel file found. Upload it via sidebar.")
        return

    try:
        master_df = pd.read_excel(MASTER_FILE)
        master_df.columns = master_df.columns.str.strip()
    except Exception as e:
        st.error(f"Error reading master file: {str(e)}")
        return

    with st.expander("📋 Preview Master Excel"):
        st.dataframe(master_df.head())

    pdf_files = st.file_uploader("📥 Upload One or More Invoice PDFs", type=["pdf"], accept_multiple_files=True)

    def expand_to_physical(df, master_df):
        """Convert ordered items to physical packing plan"""
        physical_rows = []
        missing_products = []
        
        for _, row in df.iterrows():
            try:
                asin = row.get("ASIN", "UNKNOWN")
                qty = int(row.get("Qty", 1))
                match_row = master_df[master_df["ASIN"] == asin]
                
                if match_row.empty:
                    logger.warning(f"Product not found in master file: {asin}")
                    missing_products.append({
                        "ASIN": asin,
                        "Issue": "Not found in master file",
                        "Qty": qty
                    })
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
                name = base.get("Name", "Unknown Product")
                fnsku = str(base.get("FNSKU", "")).strip()
                
                # Check if FNSKU is missing
                if is_empty_value(fnsku):
                    missing_products.append({
                        "ASIN": asin,
                        "Issue": "Missing FNSKU",
                        "Product": name,
                        "Qty": qty
                    })
                
                # Handle products with split information
                if split and not is_empty_value(split):
                    sizes = [s.strip().replace("kg", "").strip() for s in split.split(",")]
                    split_found = False
                    
                    for size in sizes:
                        try:
                            sub_match = master_df[
                                (master_df["Name"] == name) &
                                (master_df["Net Weight"].astype(str).str.replace("kg", "").str.strip() == size)
                            ]
                            if not sub_match.empty:
                                sub = sub_match.iloc[0]
                                sub_fnsku = str(sub.get("FNSKU", "")).strip()
                                status = "✅ READY" if not is_empty_value(sub_fnsku) else "⚠️ MISSING FNSKU"
                                
                                physical_rows.append({
                                    "item": name,
                                    "weight": sub.get("Net Weight", "N/A"),
                                    "Qty": qty,
                                    "Packet Size": sub.get("Packet Size", "N/A"),
                                    "ASIN": sub.get("ASIN", asin),
                                    "MRP": sub.get("M.R.P", "N/A"),
                                    "FNSKU": sub_fnsku if not is_empty_value(sub_fnsku) else "MISSING",
                                    "FSSAI": sub.get("FSSAI", ""),
                                    "Packed Today": "",
                                    "Available": "",
                                    "Status": status
                                })
                                split_found = True
                        except Exception as e:
                            logger.error(f"Error processing split variant: {str(e)}")
                    
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
                    status = "✅ READY" if not is_empty_value(fnsku) else "⚠️ MISSING FNSKU"
                    
                    physical_rows.append({
                        "item": name,
                        "weight": base.get("Net Weight", "N/A"),
                        "Qty": qty,
                        "Packet Size": base.get("Packet Size", "N/A"),
                        "ASIN": asin,
                        "MRP": base.get("M.R.P", "N/A"),
                        "FNSKU": fnsku if not is_empty_value(fnsku) else "MISSING",
                        "FSSAI": base.get("FSSAI", ""),
                        "Packed Today": "",
                        "Available": "",
                        "Status": status
                    })
            except Exception as e:
                logger.error(f"Error processing row {asin}: {str(e)}")
                continue

        df_physical = pd.DataFrame(physical_rows)
        
        if not df_physical.empty:
            try:
                # Group by all columns except Qty to sum quantities for identical items
                df_physical = df_physical.groupby(
                    ["item", "weight", "Packet Size", "ASIN", "MRP", "FNSKU", "FSSAI", "Packed Today", "Available", "Status"],
                    as_index=False
                ).agg({"Qty": "sum"})
            except Exception as e:
                logger.error(f"Error grouping physical data: {str(e)}")
        
        return df_physical, missing_products

    def generate_summary_pdf(original_df, physical_df, missing_products=None):
        """Generate PDF summary with proper encoding handling"""
        try:
            pdf = FPDF()
            timestamp = datetime.now().strftime("%d %b %Y, %I:%M %p")

            def clean_text(text):
                """Clean text for PDF generation"""
                if pd.isna(text):
                    return ""
                text = str(text)
                replacements = {
                    '✅': 'OK',
                    '⚠️': 'WARNING',
                    '📦': '',
                    '🚨': 'ALERT',
                    '•': '-'
                }
                for unicode_char, replacement in replacements.items():
                    text = text.replace(unicode_char, replacement)
                # Remove any remaining non-ASCII characters
                text = text.encode('ascii', 'ignore').decode('ascii')
                return text

            def add_table(df, title, include_tracking=False, hide_asin=False):
                """Add table to PDF"""
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
                    values = [
                        clean_text(str(row.get("item", "")))[:20], 
                        clean_text(str(row.get("weight", ""))), 
                        str(row.get("Qty", 0)), 
                        clean_text(str(row.get("Packet Size", "")))[:15]
                    ]
                    if not hide_asin:
                        values.append(clean_text(str(row.get("ASIN", ""))))
                    if include_tracking:
                        values += [
                            clean_text(str(row.get("Packed Today", ""))), 
                            clean_text(str(row.get("Available", "")))
                        ]
                        
                    for val, width in zip(values, col_widths):
                        pdf.cell(width, 10, str(val)[:width//2], 1)  # Truncate to fit
                    pdf.ln()

            pdf.add_page()
            add_table(original_df, "Original Ordered Items (from Invoice)", hide_asin=False)
            pdf.ln(5)
            add_table(physical_df, "Actual Physical Packing Plan", include_tracking=True, hide_asin=True)
            
            # Fixed PDF output handling
            output_buffer = BytesIO()
            try:
                pdf_output = pdf.output(dest="S")
                # Handle both string and bytes output
                if isinstance(pdf_output, str):
                    output_buffer.write(pdf_output.encode("latin1"))
                else:
                    output_buffer.write(pdf_output)
            except Exception as e:
                logger.error(f"PDF encoding error: {str(e)}")
                # Fallback
                pdf_string = pdf.output(dest="S")
                output_buffer.write(pdf_string.encode("latin1", errors="ignore"))
            
            output_buffer.seek(0)
            return output_buffer
        except Exception as e:
            logger.error(f"Error generating PDF: {str(e)}")
            return None

    if pdf_files:
        logger.info(f"Processing {len(pdf_files)} PDF files")
        
        # Validate files first
        for pdf_file in pdf_files:
            is_valid, message = validate_uploaded_file(pdf_file)
            if not is_valid:
                st.error(f"File {pdf_file.name}: {message}")
                return

        with st.spinner("🔍 Processing invoices..."):
            asin_qty_data = defaultdict(int)
            highlighted_pdfs = {}
            
            # Improved ASIN pattern
            asin_pattern = re.compile(r"\b(B[0-9A-Z]{9})\b")
            qty_pattern = re.compile(r"\bQty\b.*?(\d+)")
            price_qty_pattern = re.compile(r"₹[\d,.]+\s+(\d+)\s+₹[\d,.]+")

            for uploaded_file in pdf_files:
                try:
                    pdf_name = uploaded_file.name
                    pdf_bytes = uploaded_file.read()
                    
                    with safe_pdf_context(pdf_bytes) as doc:
                        pages_text = [page.get_text().split("\n") for page in doc]

                        for lines in pages_text:
                            for i, line in enumerate(lines):
                                asin_match = asin_pattern.search(line)
                                if asin_match:
                                    asin = asin_match.group(1)
                                    qty = 1
                                    # Look for quantity in next few lines
                                    for j in range(i, min(i + 4, len(lines))):
                                        match = qty_pattern.search(lines[j])
                                        if match:
                                            qty = int(match.group(1))
                                            break
                                    # Fallback to price-quantity pattern
                                    if qty == 1:
                                        for j in range(i, min(i + 4, len(lines))):
                                            match = price_qty_pattern.search(lines[j])
                                            if match:
                                                qty = int(match.group(1))
                                                break
                                    asin_qty_data[asin] += qty

                    # Generate highlighted PDF
                    highlighted = highlight_large_qty(pdf_bytes)
                    if highlighted:
                        highlighted_pdfs[pdf_name] = highlighted
                        
                except Exception as e:
                    logger.error(f"Error processing {uploaded_file.name}: {str(e)}")
                    st.warning(f"Could not process {uploaded_file.name}: {str(e)}")

            if not asin_qty_data:
                st.warning("No ASIN codes found in the uploaded PDFs. Please check the file format.")
                return

            # Create orders dataframe
            df_orders = pd.DataFrame([{"ASIN": asin, "Qty": qty} for asin, qty in asin_qty_data.items()])
            df_orders = pd.merge(df_orders, master_df, on="ASIN", how="left")
            
            # Safe column renaming
            rename_dict = {}
            if "Name" in df_orders.columns:
                rename_dict["Name"] = "item"
            if "Net Weight" in df_orders.columns:
                rename_dict["Net Weight"] = "weight"
            if "M.R.P" in df_orders.columns:
                rename_dict["M.R.P"] = "MRP"
            
            df_orders.rename(columns=rename_dict, inplace=True)
            
            # Select available columns
            available_columns = ["Qty"]
            for col in ["item", "weight", "Packet Size", "ASIN", "MRP", "FNSKU", "FSSAI"]:
                if col in df_orders.columns:
                    available_columns.append(col)
            
            df_orders = df_orders[available_columns]

            df_physical, missing_products = expand_to_physical(df_orders, master_df)

            st.success("✅ Packing plan generated!")

            # Show alerts for missing products
            if missing_products:
                st.error("⚠️ **ATTENTION: Some products have issues!**")
                with st.expander("🚨 View Missing/Problem Products", expanded=True):
                    for issue in missing_products:
                        st.warning(f"**ASIN:** {issue.get('ASIN', 'Unknown')} - **Issue:** {issue.get('Issue', 'Unknown')} - **Qty:** {issue.get('Qty', 0)}")
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
                    status = row.get('Status', '')
                    if 'MISSING FNSKU' in status:
                        return ['background-color: #ffcccc'] * len(row)
                    elif 'MISSING FROM MASTER' in status:
                        return ['background-color: #ff9999'] * len(row)
                    else:
                        return ['background-color: #ccffcc'] * len(row)
                
                try:
                    st.dataframe(df_physical.style.apply(highlight_status, axis=1), use_container_width=True)
                except:
                    # Fallback without styling
                    st.dataframe(df_physical, use_container_width=True)
            else:
                st.warning("No physical packing plan generated. Check the missing products above.")

            # PDF and Excel downloads
            if not df_physical.empty:
                try:
                    summary_pdf = generate_summary_pdf(df_orders, df_physical, missing_products)
                    if summary_pdf:
                        st.download_button("📥 Download Packing Plan PDF", data=summary_pdf, file_name="Packing_Plan.pdf", mime="application/pdf")
                    else:
                        st.warning("Could not generate PDF. Try downloading Excel instead.")
                except Exception as e:
                    st.error(f"Error generating PDF: {str(e)}")
                    st.info("PDF generation failed, but you can still download the Excel file below.")

                # Excel export
                try:
                    excel_buffer = BytesIO()
                    with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
                        df_physical.to_excel(writer, index=False, sheet_name="Physical Packing Plan")
                        df_orders.to_excel(writer, index=False, sheet_name="Original Orders")
                        if missing_products:
                            pd.DataFrame(missing_products).to_excel(writer, index=False, sheet_name="Missing Products")
                    excel_buffer.seek(0)
                    st.download_button("📊 Download Excel (All Data)", data=excel_buffer, file_name="Packing_Plan.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                except Exception as e:
                    st.error(f"Error generating Excel file: {str(e)}")

            # Highlighted PDFs
            if highlighted_pdfs:
                st.markdown("### 🔍 Highlighted Invoices")
                for name, buf in highlighted_pdfs.items():
                    if buf:
                        st.download_button(f"📄 {name}", data=buf, file_name=f"highlighted_{name}", mime="application/pdf")

            # Label generation section
            st.markdown("### 🧾 Combined MRP + Barcode Labels")
            if not os.path.exists(BARCODE_PDF_PATH):
                st.warning("Barcode PDF not found. Upload it via sidebar.")
            else:
                try:
                    # Test if barcode PDF can be opened
                    with safe_pdf_context(open(BARCODE_PDF_PATH, 'rb').read()) as test_doc:
                        pass
                except Exception as e:
                    st.error(f"Error opening barcode PDF: {e}")
                    return

                if not df_physical.empty:
                    try:
                        combined_pdf = fitz.open()
                        labels_generated = 0
                        
                        for _, row in df_physical.iterrows():
                            fnsku = str(row.get('FNSKU', '')).strip()
                            qty = int(row.get('Qty', 0))
                            
                            if fnsku and fnsku != "MISSING" and not is_empty_value(fnsku):
                                for _ in range(qty):
                                    try:
                                        label_pdf = generate_combined_label_pdf(pd.DataFrame([row]), fnsku, BARCODE_PDF_PATH)
                                        if label_pdf:
                                            with safe_pdf_context(label_pdf.read()) as label_doc:
                                                combined_pdf.insert_pdf(label_doc)
                                            labels_generated += 1
                                    except Exception as e:
                                        logger.warning(f"Could not generate label for FNSKU {fnsku}: {e}")

                        if len(combined_pdf) > 0:
                            label_buf = BytesIO()
                            combined_pdf.save(label_buf)
                            label_buf.seek(0)
                            st.download_button("📥 Download All Combined Labels", data=label_buf, file_name="All_Combined_Labels.pdf", mime="application/pdf")
                            st.success(f"Generated {labels_generated} labels successfully!")
                        else:
                            st.warning("⚠️ No labels could be generated. Check if products have valid FNSKUs.")
                        
                        combined_pdf.close()
                    except Exception as e:
                        st.error(f"Error generating combined labels: {str(e)}")
                else:
                    st.info("ℹ️ No labels to generate - no valid physical packing plan.")

            # MRP-only labels section
            st.markdown("### 🧾 MRP-Only Labels for Non-FNSKU Items")
            if not df_physical.empty:
                try:
                    mrp_only_rows = df_physical[df_physical["FNSKU"].isin(["", "MISSING", "nan", "None"]) | df_physical["FNSKU"].isna()]

                    if not mrp_only_rows.empty:
                        mrp_only_pdf = fitz.open()
                        mrp_only_count = 0

                        for _, row in mrp_only_rows.iterrows():
                            qty = int(row.get("Qty", 0))
                            for _ in range(qty):
                                try:
                                    single_label_pdf = generate_pdf(pd.DataFrame([row]))
                                    if single_label_pdf:
                                        with safe_pdf_context(single_label_pdf.read()) as label_doc:
                                            mrp_only_pdf.insert_pdf(label_doc)
                                        mrp_only_count += 1
                                except Exception as e:
                                    logger.warning(f"Failed to generate MRP label for {row.get('item', 'unknown')}: {e}")

                        if len(mrp_only_pdf) > 0:
                            buf = BytesIO()
                            mrp_only_pdf.save(buf)
                            buf.seek(0)
                            st.download_button("📥 Download MRP-Only Labels", data=buf, file_name="MRP_Only_Labels.pdf", mime="application/pdf")
                            st.success(f"✅ Generated {mrp_only_count} MRP-only labels for non-FNSKU items.")
                        else:
                            st.warning("⚠️ No MRP-only labels could be generated.")
                        
                        mrp_only_pdf.close()
                    else:
                        st.info("ℹ️ All items have valid FNSKUs. No separate MRP-only labels needed.")
                except Exception as e:
                    st.error(f"Error generating MRP-only labels: {str(e)}")
