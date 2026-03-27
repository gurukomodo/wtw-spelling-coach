import pandas as pd
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
        data = st.session_state.analysis_result # (Use your existing extraction logic here)

        st.subheader(f"📝 Diagnostic for {data.student_name}")
        
        # 1. Show the AI's suggested scores (Read-only for now)
        cols = st.columns(3)
        cols[0].metric("g0: Phonemic", f"{data.g0_phonemic_awareness}%")
        # ... (Include your other metric columns here)

        # 2. THE FEEDBACK LOOP: Editable Notes
        st.write("### 👩‍🏫 Teacher Refinement")
        st.caption("Edit the notes below to correct any AI hallucinations (e.g., removing unproven /θ/ mentions).")
        
        if st.session_state.analysis_result:
        # 1. (Assuming 'data' and 'edited_text' are already defined above)
        
        st.subheader(f"📝 Diagnostic for {data.student_name}")
        
        # 2. THE FEEDBACK LOOP: The "Gold Standard" Editor
        st.write("### 👩‍🏫 Teacher Refinement")
        st.caption("Edit the AI's notes below to correct hallucinations before saving.")
        
        # We only need ONE text_area. 
        # It starts with the AI's 'teacher_notes' as the default value.
        final_notes = st.text_area(
            "Final Diagnostic Notes (The 'Gold Standard')", 
            value=data.teacher_notes, 
            height=250
        )

        # 3. THE SAVE BUTTON
        if st.button("💾 Confirm & Save to Student History"):
            from database_manager import save_assessment
            
            # We pass 'data' (the scores), 'edited_text' (the transcript), 
            # and 'final_notes' (YOUR refined version).
            save_assessment(data, edited_text, teacher_refinement=final_notes)
            
            st.success(f"✅ Final assessment for {data.student_name} has been saved to the database!")
            st.balloons() # Optional: A little celebration for finishing a student!

        if st.button("💾 Confirm & Save to Student History"):
            from database_manager import save_assessment
            # We pass the 'final_notes' separately so the DB saves your version
            save_assessment(data, edited_text, teacher_refinement=final_notes)
            st.success(f"Final assessment for {data.student_name} saved!")

            # Recommendations
            st.subheader("🎯 Instructional Targets")
            st.info(f"Priority Groups: {', '.join(data.suggested_next_groups)}")
            
            with st.expander("📝 Diagnostic Teacher Notes"):
                st.write(data.teacher_notes)

        except Exception as e:
            st.error(f"Error: {e}")
            
st.divider()
st.header("📊 Step 2: Class Analysis & Grouping")

if st.button("🔄 Refresh Class Overview"):
    data = get_all_latest_results()
    
    if data:
        # Note: Ensure the columns list matches the order in your SQL SELECT *
        # Based on our new schema: [ID, Name, Date, Transcription, g0...g8, Suggested, AI_Notes, Refined_Notes]
        df = pd.DataFrame(data, columns=[
            "ID", "Name", "Date", "Transcription", 
            "g0", "g1", "g2", "g3", "g4", "g5", "g6", "g7", "g8", 
            "Suggested", "AI_Notes", "Refined_Notes"
        ])
        
        # Create a 'Final Summary' column that prefers your edits
        df['Final Summary'] = df['Refined_Notes'].fillna(df['AI_Notes'] + " (AI Unrefined)")
        # If Refined_Notes is just an empty string, we also want to handle that:
        df['Final Summary'] = df.apply(
            lambda x: x['Refined_Notes'] if x['Refined_Notes'] and len(x['Refined_Notes']) > 5 
            else f"⚠️ Review Needed: {x['AI_Notes']}", axis=1
        )

        # 1. Show the Scores Table
        st.subheader("Current Linguistic Profiles")
        st.dataframe(df[["Name", "Date", "g0", "g1", "g2", "g3", "g4", "g5", "g6", "g7", "g8"]])
        
        # 2. Show the "Teacher-Approved" Notes
        st.subheader("Instructional Snapshots")
        for index, row in df.iterrows():
            with st.expander(f"👤 {row['Name']} - {row['Suggested']}"):
                st.write(row['Final Summary'])
            
    else:
        st.info("No student data found. Run an analysis to see the class overview.")