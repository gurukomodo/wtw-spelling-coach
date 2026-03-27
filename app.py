from turtle import pd

import streamlit as st
from utils import preprocess_image
from spelling_logic import transcribe_handwriting, run_scoring_crew
from database_manager import init_db, get_all_latest_results# <--- 1. Import it

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
    student_name = st.text_input("Student Name (required)", key="name_input")

    st.divider()
    
    # THE RESET BUTTON
    if st.button("♻️ Start New Student"):
        # Clear the memory
        st.session_state.raw_transcription = ""
        st.session_state.analysis_result = None
        # This force-refreshes the page to a blank state
        st.rerun()

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
            # Flexible data extraction
            if hasattr(res, 'pydantic') and res.pydantic:
                data = res.pydantic
            elif hasattr(res, 'json_dict') and res.json_dict:
                from argparse import Namespace
                data = Namespace(**res.json_dict)
            else:
                import json
                data = Namespace(**json.loads(res.raw))

            # --- SAVE TO DB ---
            from database_manager import save_assessment
            save_assessment(data, edited_text)

            st.success(f"✅ Diagnostic Complete for {data.student_name}!")
            
            # Show the 9-Group Profile
            st.subheader("📊 Linguistic Profile")
            # Using columns for a compact view of g0-g8
            cols = st.columns(3)
            cols[0].metric("g0: Phonemic", f"{data.g0_phonemic_awareness}%")
            cols[1].metric("g1: CVC", f"{data.g1_cvc_mapping}%")
            cols[2].metric("g2: Digraphs", f"{data.g2_digraphs}%")
            
            cols2 = st.columns(3)
            cols2[0].metric("g3: Silent-E", f"{data.g3_silent_e}%")
            cols2[1].metric("g4: Vowel Teams", f"{data.g4_vowel_teams}%")
            cols2[2].metric("g5: R-Controlled", f"{data.g5_r_controlled}%")

            # Recommendations
            st.subheader("🎯 Instructional Targets")
            st.info(f"Priority Groups: {', '.join(data.suggested_next_groups)}")
            
            with st.expander("📝 Diagnostic Teacher Notes"):
                st.write(data.teacher_notes)

        except Exception as e:
            st.error(f"Error: {e}")
            
st.divider()
st.header("📋 Class Overview (Step 2 Prep)")

if st.button("🔄 Refresh Class Data"):
    results = get_all_latest_results() # Fetching the latest test for each of your 7 students
    if results:
        df = pd.DataFrame(results, columns=[
            "ID", "Name", "Date", "Transcription", 
            "g0", "g1", "g2", "g3", "g4", "g5", "g6", "g7", "g8", 
            "Targets", "Notes"
        ])
        # Displaying a clean table of the 9-group scores
        st.dataframe(df[["Name", "Date", "g0", "g1", "g2", "g3", "g4", "g5", "g6", "g7", "g8", "Targets"]])
    else:
        st.info("No data in the database yet. Run an analysis to see results here.")