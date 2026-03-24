import streamlit as st
import pandas as pd
import os
# Import your existing logic here (assuming your main script is spelling_coach.py)
from spelling_coach import crew, WTWScoreSchema, append_to_ledger 

# Initialize session state if it doesn't exist yet
if "transcribed_text" not in st.session_state:
    st.session_state["transcribed_text"] = ""

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

# Use session_state to pre-fill the box if we just did an OCR scan
default_text = st.session_state.get("transcribed_text", "")

st.header("📸 Upload Student Assessment")
uploaded_file = st.file_uploader("Choose a photo of the spelling test...", type=["jpg", "jpeg", "png"])

if uploaded_file is not None:
    # Display the image
    st.image(uploaded_file, caption='Uploaded Assessment', width='stretch')
    
    if st.button("🔍 Read Handwriting"):
        with st.spinner("The AI is reading the handwriting..."):
            from spelling_coach import encode_image, transcribe_handwriting
            
            # Convert image to format AI understands
            base64_str = encode_image(uploaded_file)
            
            # Get AI's interpretation
            transcription = transcribe_handwriting(base64_str)
            
            # Save it so the text box below can show it
            st.session_state["transcribed_text"] = transcription
            
            # Show what the AI saw! (This was missing!)
            st.success("✅ AI finished reading!")
            st.subheader("What the AI thinks it says:")
            st.code(transcription)  # Display it clearly
            
            st.info("👆 Check if the AI read it correctly, then click 'Run Analysis' below")

student_attempts = st.text_area(
    "Student spellings (Verify transcription here):", 
    value=default_text,
    height=300
)

                
if st.button("🚀 Run Analysis"):
    if not student_name or not student_attempts:
        st.error("Please provide both a name and spelling attempts!")
    else:
        # SHOW what we're analyzing
        st.subheader("Analyzing these responses:")
        st.code(student_attempts)  # ← ADD THIS LINE
        
        with st.spinner(f"Analyzing {student_name}'s spelling..."):
            inputs = {"student_spellings": f"NAME: {student_name}\n{student_attempts}"}
            
            result = crew.kickoff(inputs=inputs)
            data = result.pydantic
            
            if data:
                st.success("Analysis Complete!")
                
                # Your existing metrics code stays the same...
                
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