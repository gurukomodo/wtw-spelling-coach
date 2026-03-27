import streamlit as st
from utils import preprocess_image
from spelling_logic import transcribe_handwriting, run_scoring_crew
from database_manager import init_db  # <--- 1. Import it

# --- INITIALIZE DATABASE ---
init_db()  # <--- 2. Run it (It creates the tables if they don't exist)

st.set_page_config(page_title="WTW Coach", page_icon="🍎")
st.title("🍎 WTW Digital Spelling Coach")

# --- 1. INITIALIZE ALL MEMORY ---
if "raw_transcription" not in st.session_state:
    st.session_state.raw_transcription = ""
if "analysis_result" not in st.session_state:
    st.session_state.analysis_result = None

# Sidebar
with st.sidebar:
    st.header("📋 Class Settings")
    # Using a key here ensures Streamlit remembers the name across clicks
    student_name = st.text_input("Student Name", key="name_input")

uploaded_file = st.file_uploader("📸 Step 1: Upload Test Photo", type=["jpg", "jpeg", "png"])

# --- 2. PRE-PROCESS & LAYOUT ---
if uploaded_file:
    clean_base64, clean_img = preprocess_image(uploaded_file)
    
    col_img, col_text = st.columns([1, 1])
    
    with col_img:
        st.subheader("🖼️ AI's View (Cleaned)")
        st.image(clean_img, use_container_width=True)
        if st.button("🔍 Step 2: Read Handwriting"):
            with st.spinner("AI is reading..."):
                # Save to session state so it persists
                st.session_state.raw_transcription = transcribe_handwriting(clean_base64)
                st.rerun() 

    with col_text:
        st.subheader("✍️ Step 3: Verify & Edit")
        # This is the 'edited_text' the Analysis button is looking for
        edited_text = st.text_area(
            "Verify and edit student attempts here:", 
            value=st.session_state.raw_transcription,
            height=400 
        )

    # --- 3. THE ANALYSIS BUTTON ---
    if st.button("🚀 Step 4: Run Analysis"):
        if not student_name:
            st.warning("⚠️ Please enter a Student Name in the sidebar!")
        elif not edited_text:
            st.warning("⚠️ No text to analyze. Please read handwriting or type manually.")
        else:
            with st.spinner(f"Analyzing {student_name}..."):
                # We use 'edited_text' here to match the text_area variable above
                result = run_scoring_crew(student_name, edited_text)
                
                # DEBUG: If it's failing, let's see what the AI actually said
                if result is None:
                    st.error("The AI returned nothing. Check your internet or API key.")
                else:
                    st.session_state.analysis_result = result
                    
    # --- 4. DISPLAY RESULTS ---
    if st.session_state.analysis_result:
        res = st.session_state.analysis_result
        
        try:
            # This logic checks every possible place the data could be hiding
            if hasattr(res, 'pydantic') and res.pydantic:
                data = res.pydantic
            elif hasattr(res, 'json_dict') and res.json_dict:
                # If it's a dictionary, we turn it into an object-like structure
                from argparse import Namespace
                data = Namespace(**res.json_dict)
            else:
                # If all else fails, try parsing the raw string
                import json
                raw_data = json.loads(res.raw)
                from argparse import Namespace
                data = Namespace(**raw_data)

            st.success("✅ Analysis Complete!")
            
            # Now we use 'data' safely
            m1, m2, m3 = st.columns(3)
            m1.metric("Stage", data.spelling_stage)
            m2.metric("Total Score", f"{data.total_score}/82")
            m3.metric("Words Correct", f"{data.words_correct}/26")
            
            st.subheader("Instructional Focus")
            st.info(f"**Focus:** {data.next_focus}")
            
            with st.expander("📝 Teacher's Summary"):
                st.write(data.short_explanation)

        except Exception as e:
            st.error(f"Display Error: {e}")
            st.write("The AI sent data, but we couldn't format it. Here is the raw text:")
            st.code(res.raw)