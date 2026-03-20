import streamlit as st
import pandas as pd
import os
# Import your existing logic here (assuming your main script is spelling_coach.py)
from spelling_coach import crew, WTWScoreSchema, append_to_ledger 

# --- PAGE CONFIG ---
st.set_page_config(page_title="WTW Spelling Coach", page_icon="🍎")

st.title("🍎 WTW Digital Spelling Coach")
st.markdown("Assess student spelling and track progress every fortnight.")

# --- SIDEBAR: Teacher Settings ---
with st.sidebar:
    st.header("📋 Class Settings")
    teacher_name = st.text_input("Teacher Name", placeholder="e.g. Mr. Smith")
    year_level = st.selectbox("Year Level", ["Foundation", "Year 1", "Year 2", "Year 3", "Year 4+"])
    
    if st.button("View Previous Results"):
        if os.path.exists('students.csv'):
            df = pd.read_csv('students.csv')
            st.dataframe(df)
        else:
            st.warning("No data found yet!")

# --- MAIN AREA: Assessment ---
st.header("📝 New Assessment")

col1, col2 = st.columns(2)
with col1:
    student_name = st.text_input("Student Name")
with col2:
    test_date = st.date_input("Test Date")

student_attempts = st.text_area(
    "Paste student spellings (e.g., fan: fan, hope: hop):", 
    height=300
)

if st.button("🚀 Run Analysis"):
    if not student_name or not student_attempts:
        st.error("Please provide both a name and spelling attempts!")
    else:
        with st.spinner(f"Analyzing {student_name}'s spelling..."):
            # Prepare inputs for your Crew
            inputs = {"student_spellings": f"NAME: {student_name}\n{student_attempts}"}
            
            # Run the Crew
            result = crew.kickoff(inputs=inputs)
            data = result.pydantic # The JSON Brain
            
            if data:
                # 1. Display results immediately
                st.success("Analysis Complete!")
                
                # Metrics at a glance
                m1, m2, m3 = st.columns(3)
                m1.metric("Total Score", f"{data.total_score}/82")
                m2.metric("Words Correct", f"{data.words_correct}/26")
                m3.metric("Stage", data.spelling_stage)
                
                # Detailed Feedback
                st.subheader("Instructional Focus")
                st.write(f"**Next Steps:** {data.next_focus}")
                
                with st.expander("See Full Phonetic Breakdown"):
                    st.write(data.short_explanation)
                    st.write("**Struggles:**", ", ".join(data.struggle_patterns))
                
                # 2. Save to the CSV Ledger
                append_to_ledger(data)
                st.info("✅ Result saved to students.csv")
            else:
                st.error("The AI failed to return structured data. Check the terminal for errors.")