import streamlit as st
import pandas as pd
import os
from fpdf import FPDF
from datetime import datetime
from sidebar import sidebar_controls, MANUAL_PLAN_FILE

def manual_packing_plan():
    st.title("🔖 Manual Packing Plan Generator")
    sidebar_controls()

    def process_uploaded_file(path):
        xl = pd.ExcelFile(path)
        df = xl.parse(xl.sheet_names[0])
        df.columns = df.columns.str.strip()

        if 'Pouch Size' not in df.columns:
            df['Pouch Size'] = None
        if 'ASIN' not in df.columns:
            df['ASIN'] = None

        df['Total Weight Sold (kg)'] = None
        current_parent = None
        parent_indices = []

        for idx, row in df.iterrows():
            item = str(row['Row Labels']).strip()
            if not item.replace('.', '', 1).isdigit():
                current_parent = item
                parent_indices.append(idx)
            else:
                try:
                    weight = float(item)
                    units = row['Sum of Units Ordered']
                    df.at[idx, 'Total Weight Sold (kg)'] = weight * units
                except:
                    pass

        for idx in parent_indices:
            total = 0
            for next_idx in range(idx + 1, len(df)):
                next_item = str(df.at[next_idx, 'Row Labels']).strip()
                if not next_item.replace('.', '', 1).isdigit():
                    break
                weight = df.at[next_idx, 'Total Weight Sold (kg)']
                if pd.notna(weight):
                    total += weight
            df.at[idx, 'Total Weight Sold (kg)'] = total

        df['Contribution %'] = None
        current_parent_total = None

        for idx, row in df.iterrows():
            item = str(row['Row Labels']).strip()
            if not item.replace('.', '', 1).isdigit():
                current_parent_total = row['Total Weight Sold (kg)']
            else:
                try:
                    weight = row['Total Weight Sold (kg)']
                    if pd.notna(weight) and pd.notna(current_parent_total) and current_parent_total != 0:
                        df.at[idx, 'Contribution %'] = round((weight / current_parent_total) * 100, 2)
                except:
                    pass

        return df

    def round_to_nearest_2(x):
        return int(2 * round(x / 2)) if pd.notna(x) else None

    def adjust_packets(result_df, target_weight):
        packed_weight = result_df['Weight Packed (kg)'].sum()
        deviation = (target_weight - packed_weight) / target_weight

        while (packed_weight > target_weight) or (abs(deviation) > 0.05):
            if packed_weight > target_weight:
                idx = result_df['Variation (kg)'].idxmax()
                if result_df.at[idx, 'Packets to Pack'] >= 2:
                    result_df.at[idx, 'Packets to Pack'] -= 2
            elif deviation > 0:
                idx = result_df['Variation (kg)'].idxmin()
                result_df.at[idx, 'Packets to Pack'] += 2
            else:
                break

            result_df['Weight Packed (kg)'] = result_df['Variation (kg)'] * result_df['Packets to Pack']
            packed_weight = result_df['Weight Packed (kg)'].sum()
            deviation = (target_weight - packed_weight) / target_weight

        return result_df

    def generate_combined_pdf(packing_summary, combined_total, combined_loose):
        pdf = FPDF()
        pdf.add_page()

        pdf.set_font("Arial", "B", 14)
        pdf.cell(200, 10, "Mithila Foods Packing Plan", ln=True, align="C")
        pdf.set_font("Arial", size=11)
        pdf.cell(200, 10, f"Date: {datetime.now().strftime('%d-%m-%Y')}", ln=True, align="C")
        pdf.ln(5)

        for item_block in packing_summary:
            pdf.set_font("Arial", "B", 12)
            pdf.cell(200, 10, f"Item: {item_block['item']}", ln=True)
            pdf.set_font("Arial", size=11)
            pdf.cell(200, 8, f"Target: {item_block['target_weight']} kg | Packed: {item_block['packed_weight']:.2f} kg | Loose: {item_block['loose_weight']:.2f} kg", ln=True)

            pdf.set_font("Arial", size=10)
            pdf.cell(30, 8, "Variation", border=1)
            pdf.cell(35, 8, "Pouch Size", border=1)
            pdf.cell(45, 8, "ASIN", border=1)
            pdf.cell(30, 8, "Packets", border=1)
            pdf.cell(40, 8, "Packed (kg)", border=1)
            pdf.ln()

            for _, row in item_block['data'].iterrows():
                pdf.cell(30, 8, f"{row['Variation (kg)']}", border=1)
                pdf.cell(35, 8, str(row['Pouch Size']), border=1)
                pdf.cell(45, 8, str(row['ASIN']), border=1)
                pdf.cell(30, 8, f"{int(row['Packets to Pack'])}", border=1)
                pdf.cell(40, 8, f"{row['Weight Packed (kg)']:.2f}", border=1)
                pdf.ln()
            pdf.ln(5)

        pdf.set_font("Arial", "B", 12)
        pdf.cell(200, 10, f"TOTAL PACKED: {combined_total:.2f} kg | TOTAL LOOSE: {combined_loose:.2f} kg", ln=True, align="C")
        return pdf.output(dest="S").encode("latin1")

    if not os.path.exists(MANUAL_PLAN_FILE):
        st.error("No manual packing plan uploaded via sidebar.")
        return

    df_full = process_uploaded_file(MANUAL_PLAN_FILE)
    parent_items = df_full[~df_full['Row Labels'].astype(str).str.replace('.', '', 1).str.isnumeric()]['Row Labels'].tolist()

    selected_items = st.multiselect("Select Items to Pack:", parent_items)
    packing_summary = []
    total_combined_weight = 0
    total_combined_loose = 0

    for selected_item in selected_items:
        st.subheader(f"📦 {selected_item}")
        target_weight = st.number_input(f"Enter weight to pack for {selected_item} (kg):", min_value=1, value=100, step=10)

        idx_parent = df_full[df_full['Row Labels'] == selected_item].index[0]
        variations = []
        for i in range(idx_parent + 1, len(df_full)):
            label = str(df_full.at[i, 'Row Labels']).strip()
            if not label.replace('.', '', 1).isdigit():
                break
            variations.append({
                'Variation (kg)': float(label),
                'Contribution %': df_full.at[i, 'Contribution %'],
                'Pouch Size': df_full.at[i, 'Pouch Size'],
                'ASIN': df_full.at[i, 'ASIN']
            })

        result = []
        for var in variations:
            packets = (var['Contribution %'] / 100) * target_weight / var['Variation (kg)']
            packets = round_to_nearest_2(packets)
            weight_packed = packets * var['Variation (kg)']
            result.append({
                'Variation (kg)': var['Variation (kg)'],
                'Pouch Size': var['Pouch Size'],
                'ASIN': var['ASIN'],
                'Packets to Pack': packets,
                'Weight Packed (kg)': weight_packed
            })

        result_df = pd.DataFrame(result)
        result_df = adjust_packets(result_df, target_weight)
        packed_weight = result_df['Weight Packed (kg)'].sum()
        loose_weight = target_weight - packed_weight

        st.dataframe(result_df[['Variation (kg)', 'Pouch Size', 'ASIN', 'Packets to Pack', 'Weight Packed (kg)']])
        packing_summary.append({
            'item': selected_item,
            'target_weight': target_weight,
            'packed_weight': packed_weight,
            'loose_weight': loose_weight,
            'data': result_df
        })

        total_combined_weight += packed_weight
        total_combined_loose += loose_weight

    if packing_summary:
        pdf_data = generate_combined_pdf(packing_summary, total_combined_weight, total_combined_loose)
        st.download_button("📄 Download Combined Packing Plan PDF", data=pdf_data, file_name="MithilaFoods_PackingPlan.pdf", mime="application/pdf")
