import streamlit as st

st.set_page_config(page_title="📦 Mithila Tools Dashboard", layout="wide")

st.sidebar.title("🧰 Mithila Dashboard")
tool = st.sidebar.selectbox("Choose a tool", [
    "📦 Packing Plan Generator",
    "🔖 Manual Packing Plan Generator",
    "🔖 Label Generator",
    "📥 Easy Ship Report Generator"  # NEW
])

if tool == "📦 Packing Plan Generator":
    from packing_plan_tool import packing_plan_tool
    packing_plan_tool()

elif tool == "🔖 Label Generator":
    from label_generator_tool import label_generator_tool
    label_generator_tool()

elif tool == "🔖 Manual Packing Plan Generator":
    from manual_packing_plan import manual_packing_plan
    manual_packing_plan()

elif tool == "📥 Easy Ship Report Generator":
    from easy_ship_report import easy_ship_report
    easy_ship_report()  # NEW: function to be defined in easy_ship_report.py
