# Test Google Sheets Integration
import streamlit as st
import pandas as pd
from sidebar import load_from_google_sheet

def test_google_sheets():
    st.title("🧪 Google Sheets Integration Test")
    
    # Your Google Sheet URL
    sheet_url = "https://docs.google.com/spreadsheets/d/11dBw92P7Bg0oFyfqramGqdAlLTGhcb2ScjmR_1wtiTM/export?format=csv&gid=0"
    
    st.write("**Testing connection to your Google Sheet...**")
    st.code(sheet_url)
    
    try:
        with st.spinner("Loading data from Google Sheets..."):
            df, error = load_from_google_sheet(sheet_url)
        
        if error:
            st.error(f"❌ Error: {error}")
        else:
            st.success(f"✅ Successfully loaded {len(df)} rows from Google Sheets!")
            
            # Show basic info
            st.subheader("📊 Data Summary")
            col1, col2 = st.columns(2)
            with col1:
                st.metric("Total Rows", len(df))
            with col2:
                st.metric("Total Columns", len(df.columns))
            
            # Show columns
            st.subheader("📋 Available Columns")
            st.write(list(df.columns))
            
            # Show preview
            st.subheader("👀 Data Preview")
            st.dataframe(df.head())
            
            # Check for required columns
            st.subheader("🔍 Column Validation")
            required_cols = ['Name', 'ASIN', 'Net Weight', 'FNSKU']
            for col in required_cols:
                if col in df.columns:
                    st.success(f"✅ {col} column found")
                else:
                    st.error(f"❌ {col} column missing")
                    
    except Exception as e:
        st.error(f"❌ Unexpected error: {str(e)}")

if __name__ == "__main__":
    test_google_sheets()
