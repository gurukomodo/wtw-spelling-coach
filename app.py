import pandas as pd
import streamlit as st
from utils import preprocess_image
from spelling_logic import transcribe_handwriting, run_scoring_crew
from database_manager import init_db, get_all_latest_results

# --- INITIALIZE DATABASE ---
init_db()  

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
    student_name = st.text_input("Student Name (required)", key="name_input")

    st.divider()
    
    # THE RESET BUTTON
    if st.button("♻️ Start New Student"):
        st.session_state.raw_transcription = ""
        st.session_state.analysis_result = None
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
                st.session_state.raw_transcription = transcribe_handwriting(clean_base64)
                st.rerun() 

    with col_text:
        st.subheader("✍️ Step 3: Verify & Edit")
        edited_text = st.text_area(
            "Verify and edit student attempts here:", 
            value=st.session_state.raw_transcription,
            height=400 
        )

    # --- 3. THE ANALYSIS BUTTON ---
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
                
                if result is None:
                    st.error("The AI returned nothing. Check your internet or API key.")
                else:
                    st.session_state.analysis_result = result
                    
                    # FALLBACK CHECK: If result isn't a strict object, grab the text!
                    if not hasattr(result, 'g0_phonemic_awareness') and hasattr(result, 'raw'):
                        st.warning("⚠️ The AI struggled to structure the scores perfectly, but here is its raw analysis:")
                        st.info(result.raw)
                    
    # --- 4. DISPLAY RESULTS ---
    if st.session_state.analysis_result:
        data = st.session_state.analysis_result 

        st.subheader(f"📝 Diagnostic for {student_name}") # Pulled directly from sidebar to stop crashes
        
        # 1. ATTEMPT TO READ STRUCTURED DATA OR PARSE RAW JSON
        import json
        
        # Pre-fill defaults
        g_scores = {f"g{i}": 0 for i in range(9)}
        notes = "No notes generated."
        targets = []
        
        # Scenario A: Crew AI successfully mapped to Pydantic
        if hasattr(data, 'g0_phonemic_awareness'):
            g_scores = {
                "g0": data.g0_phonemic_awareness, "g1": data.g1_cvc_mapping, "g2": data.g2_digraphs,
                "g3": data.g3_silent_e, "g4": data.g4_vowel_teams, "g5": data.g5_r_controlled,
                "g6": data.g6_clusters, "g7": data.g7_multisyllabic, "g8": data.g8_reduction_morphology
            }
            notes = data.teacher_notes
            targets = data.suggested_next_groups
            
        # Scenario B: Crew AI returned a raw JSON string like it just did for Alice!
        elif hasattr(data, 'raw') and data.raw:
            try:
                raw_json = json.loads(data.raw)
                g_scores = {
                    "g0": raw_json.get("g0_phonemic_awareness", 0),
                    "g1": raw_json.get("g1_cvc_mapping", 0),
                    "g2": raw_json.get("g2_digraphs", 0),
                    "g3": raw_json.get("g3_silent_e", 0),
                    "g4": raw_json.get("g4_vowel_teams", 0),
                    "g5": raw_json.get("g5_r_controlled", 0),
                    "g6": raw_json.get("g6_clusters", 0),
                    "g7": raw_json.get("g7_multisyllabic", 0),
                    "g8": raw_json.get("g8_reduction_morphology", 0)
                }
                notes = raw_json.get("teacher_notes", "No notes generated.")
                targets = raw_json.get("suggested_next_groups", [])
            except:
                notes = "AI returned text but couldn't parse scores automatically. See below."

        # Display the scores in the clean UI metrics
        cols = st.columns(3)
        cols[0].metric("g0: Phonemic", f"{g_scores['g0']}%")
        cols[1].metric("g1: CVC", f"{g_scores['g1']}%")
        cols[2].metric("g2: Digraphs", f"{g_scores['g2']}%")
        
        cols2 = st.columns(3)
        cols2[0].metric("g3: Silent E", f"{g_scores['g3']}%")
        cols2[1].metric("g4: Vowel Teams", f"{g_scores['g4']}%")
        cols2[2].metric("g5: R-Controlled", f"{g_scores['g5']}%")
        
        cols3 = st.columns(3)
        cols3[0].metric("g6: Clusters", f"{g_scores['g6']}%")
        cols3[1].metric("g7: Multisyllabic", f"{g_scores['g7']}%")
        cols3[2].metric("g8: Reduction", f"{g_scores['g8']}%")

        # Recommendations
        st.subheader("🎯 Instructional Targets")
        st.info(f"Priority Groups: {', '.join(targets) if targets else 'None suggested.'}")
            
        # 2. THE FEEDBACK LOOP: The "Gold Standard" Editor
        st.write("### 👩‍🏫 Teacher Refinement")
        st.caption("Review the AI's notes above. Use the text box below to correct hallucinations and record your final diagnostic decision.")
        
        # We give them placeholder text if the AI didn't return a perfect string!
        default_text_area_val = notes if notes != "No notes generated." else "Type your own diagnostic notes here for this student..."
        
        final_notes = st.text_area(
            "Final Diagnostic Notes (The 'Gold Standard')", 
            value=default_text_area_val, 
            height=250
        )

        # 3. THE SAVE BUTTON
        if st.button("💾 Confirm & Save to Student History"):
            from database_manager import save_assessment
            
            # Clean up the suggested groups so they are just "g1", "g2", etc.
            cleaned_targets = []
            if targets:
                for target in targets:
                    # If it looks like "g2_digraphs", just grab the "g2" part
                    if "_" in target:
                        cleaned_targets.append(target.split("_")[0])
                    else:
                        cleaned_targets.append(target)

            # Since the database expects a structured object, we can build a fake one 
            # with our extracted data to pass to save_assessment safely!
            class SaveObject:
                pass
            save_obj = SaveObject()
            save_obj.student_name = student_name
            save_obj.suggested_next_groups = cleaned_targets # Uses our newly cleaned list!
            save_obj.teacher_notes = notes
            save_obj.g0_phonemic_awareness = g_scores["g0"]
            save_obj.g1_cvc_mapping = g_scores["g1"]
            save_obj.g2_digraphs = g_scores["g2"]
            save_obj.g3_silent_e = g_scores["g3"]
            save_obj.g4_vowel_teams = g_scores["g4"]
            save_obj.g5_r_controlled = g_scores["g5"]
            save_obj.g6_clusters = g_scores["g6"]
            save_obj.g7_multisyllabic = g_scores["g7"]
            save_obj.g8_reduction_morphology = g_scores["g8"]

            save_assessment(save_obj, edited_text, teacher_refinement=final_notes)
            
            st.success(f"✅ Final assessment for {student_name} has been saved with clean tags!")
            st.balloons()
            
# --- STEP 2: CLASS ANALYSIS ---
    st.header("📊 Class Overview & Grouping")
    
    if st.button("🔄 Refresh Class Overview"):
        from database_manager import get_all_latest_results, generate_class_groups
        
        data = get_all_latest_results()
        
        if not data:
            st.info("No student data found. Save an assessment first!")
        else:
            # 1. Draw the Master Table
            df = pd.DataFrame(data, columns=[
                "ID", "Student", "Date", "Raw Text", 
                "g0", "g1", "g2", "g3", "g4", "g5", "g6", "g7", "g8", 
                "Suggested", "Notes", "Refined Notes"
            ])
            
            # Show the table but hide the database IDs and raw transcriptions for a cleaner look
            st.dataframe(df.drop(columns=["ID", "Raw Text", "Notes"]))
            
            st.markdown("---")
            
            # 2. Draw the Physical Teaching Groups!
            st.subheader("🎯 Auto-Generated Teaching Groups")
            st.caption("Students are grouped here based on the targeted G-levels suggested by the AI.")
            
            teaching_groups = generate_class_groups()
            
            if not teaching_groups:
                st.warning("No teaching groups could be formed. Ensure students have 'Suggested' targets saved.")
            else:
                # Let's display them in a dynamic grid of columns
                cols = st.columns(3)
                col_idx = 0
                
                for group_name, students in teaching_groups.items():
                    with cols[col_idx]:
                        # A nice clean card for each group
                        st.markdown(f"### {group_name}")
                        for student in students:
                            st.markdown(f"- **{student}**")
                        st.write("") # Add spacing
                    
                    # Cycle through the 3 columns
                    col_idx = (col_idx + 1) % 3