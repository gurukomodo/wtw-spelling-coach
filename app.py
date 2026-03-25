import streamlit as st
from utils import preprocess_image
from spelling_logic import transcribe_handwriting, run_scoring_crew

st.set_page_config(page_title="WTW Coach", page_icon="🍎")
st.title("🍎 WTW Digital Spelling Coach")

# Sidebar for history/settings
with st.sidebar:
    st.header("Settings")
    student_name = st.text_input("Student Name")

uploaded_file = st.file_uploader("Upload Test Photo", type=["jpg", "jpeg", "png"])

if uploaded_file and student_name:
    # 1. Clean the image using utils.py
    with st.spinner("Cleaning image..."):
        clean_base64 = preprocess_image(uploaded_file)
    st.image(uploaded_file, caption="Original Photo", width=300)

    # 2. Read the handwriting
    if st.button("🔍 Step 1: Read Handwriting"):
        with st.spinner("AI is reading..."):
            st.session_state.raw_transcription = transcribe_handwriting(clean_base64)
    
    # 3. Verify & Edit (Critical for teachers!)
    if "raw_transcription" in st.session_state:
        edited_text = st.text_area("Verify Transcription:", st.session_state.raw_transcription, height=200)
        
        # 4. Final Analysis
        if st.button("🚀 Step 2: Run Analysis"):
            with st.spinner("Calculating scores..."):
                result = run_scoring_crew(student_name, edited_text)
                data = result.pydantic
                
                st.success("Analysis Complete!")
                st.metric("Stage", data.spelling_stage)
                st.write(f"**Score:** {data.total_score}/82")
                st.write(f"**Next Steps:** {data.next_focus}")