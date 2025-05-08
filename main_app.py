import streamlit as st

st.set_page_config(page_title="📦 Mithila Tools Dashboard", layout="wide")

st.sidebar.title("🧰 Mithila Dashboard")
tool = st.sidebar.selectbox("Choose a tool", [
    "📦 Packing Plan Generator",
    "🔖 Label Generator"
])

if tool == "📦 Packing Plan Generator":
    from packing_plan_tool import packing_plan_tool
    packing_plan_tool()

elif tool == "🔖 Label Generator":
    from label_generator_tool import label_generator_tool
    label_generator_tool()
