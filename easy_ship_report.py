import streamlit as st
import pandas as pd
import re
from io import BytesIO
from datetime import date
from sidebar import sidebar_controls
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, KeepTogether
)
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
import os

def easy_ship_report():
    st.title("📥 Easy Ship Order Report Generator")
    admin_logged_in, MASTER_FILE, _, _ = sidebar_controls()

    # Load MRP Excel to map ASIN → Clean Name
    if os.path.exists(MASTER_FILE):
        mrp_df = pd.read_excel(MASTER_FILE)
        mrp_df['clean_product_name'] = (
            mrp_df['Name'].astype(str) + " " + mrp_df['Net Weight'].astype(str) + "kg"
        )
        asin_map = mrp_df[['ASIN', 'clean_product_name']].dropna()
    else:
        st.error("❌ Master Excel not found. Please upload it via sidebar.")
        st.stop()

    # Easy Ship file uploader
    uploaded_file = st.file_uploader("Upload your Amazon Easy Ship Excel file", type="xlsx")

    if uploaded_file:
        try:
            df = pd.read_excel(uploaded_file, sheet_name="Sheet1")
            df = df[['tracking-id', 'asin', 'product-name', 'quantity-purchased', 'pickup-slot']]
            df = df.sort_values(by="asin")

            # Truncate messy names
            def truncate_product_name(text):
                words = str(text).split()
                return ' '.join(words[:10])[:70]
            df['product-name'] = df['product-name'].apply(truncate_product_name)

            # Clean pickup date
            def extract_month_day(slot):
                match = re.search(r'[A-Za-z]{3,9} \d{1,2}', str(slot))
                return match.group(0) if match else ""
            df['pickup-slot'] = df['pickup-slot'].apply(extract_month_day)

            # Rename quantity + highlight
            df = df.rename(columns={'quantity-purchased': 'qty'})
            df['highlight'] = df['qty'] > 1

            # Merge clean names using ASIN
            df = df.merge(asin_map, left_on='asin', right_on='ASIN', how='left')
            df['product-name'] = df['clean_product_name'].fillna(df['product-name'])
            df.drop(columns=['clean_product_name', 'ASIN'], inplace=True)

            st.success(f"✅ {len(df)} orders processed.")
            st.dataframe(df.drop(columns=['highlight']))

            # Orientation selector
            orientation = st.radio("Select Page Orientation", ["Portrait", "Landscape"], horizontal=True)

            # PDF generation
            def generate_grouped_pdf(dataframe, orientation):
                buffer = BytesIO()
                styles = getSampleStyleSheet()
                left_align_style = ParagraphStyle(
                    name='LeftAlign',
                    parent=styles['Heading4'],
                    alignment=0,
                    fontSize=12,
                    leading=14
                )
                today_str = date.today().strftime("%Y-%m-%d")
                page_size = A4 if orientation == "Portrait" else landscape(A4)

                doc = SimpleDocTemplate(buffer, pagesize=page_size, title=f"Easy Ship Report - {len(df)} Orders - {today_str}")
                elements = [Paragraph(f"Easy Ship Report - {len(df)} Orders - {today_str}", styles["Title"]), Spacer(1, 12)]

                grouped = dataframe.groupby('product-name')
                for product_name, group in grouped:
                    table_data = [['tracking-id', 'qty', 'pickup-slot']]
                    for _, row in group.iterrows():
                        table_data.append([
                            row['tracking-id'],
                            str(row['qty']),
                            row['pickup-slot']
                        ])

                    table = Table(table_data, repeatRows=1, colWidths=[180, 60, 90])
                    table.hAlign = 'LEFT'
                    style = TableStyle([
                        ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
                        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                        ('FONTSIZE', (0, 0), (-1, -1), 10),
                        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                        ('GRID', (0, 0), (-1, -1), 0.25, colors.grey),
                    ])

                    for i, row in enumerate(group.itertuples(), start=1):
                        if row.highlight:
                            style.add('BACKGROUND', (1, i), (1, i), colors.lightgrey)
                            style.add('FONTNAME', (1, i), (1, i), 'Helvetica-Bold')

                    table.setStyle(style)

                    block = KeepTogether([
                        Paragraph(f"{product_name}", left_align_style),
                        Spacer(1, 4),
                        table,
                        Spacer(1, 4)
                    ])
                    elements.append(block)

                doc.build(elements)
                buffer.seek(0)
                return buffer

            if st.button("📄 Generate PDF (Grouped by Item)"):
                pdf_buffer = generate_grouped_pdf(df, orientation)
                st.download_button(
                    label="📥 Download PDF",
                    data=pdf_buffer,
                    file_name=f"Easy_Ship_Report_{len(df)}_Orders_{date.today()}.pdf",
                    mime="application/pdf"
                )

        except Exception as e:
            st.error(f"❌ Error processing file: {e}")
