import pandas as pd
import streamlit as st
from utils import preprocess_image
from spelling_logic import transcribe_handwriting, run_scoring_crew, generate_personalized_practice_words
from database_manager import init_db, get_all_latest_results
import random
import os
from datetime import datetime


# --- HELPER: Convert practice lists to transposed DataFrame for Google Sheets ---
def practice_lists_to_table(practice_lists):
    """Convert practice lists into a transposed DataFrame.
    Columns = student names, Rows = word positions (Word 1-10)
    """
    if not practice_lists:
        return None
    
    # Build dict: student_name -> list of 10 words
    data = {}
    for slip in practice_lists:
        student_name = slip["student_name"]
        words = slip["words"]
        data[student_name] = words
    
    # Create DataFrame with rows as word positions
    df = pd.DataFrame(data)
    # Rename index to show word positions
    df.index = [f"Word {i+1}" for i in range(len(df))]
    return df

# --- INITIALIZE DATABASE ---
init_db()  

st.set_page_config(page_title="WTW Coach", page_icon="🍎")
st.title("🍎 WTW Digital Spelling Coach")

# --- 1. INITIALIZE ALL MEMORY ---
if "raw_transcription" not in st.session_state:
    st.session_state.raw_transcription = ""
if "analysis_result" not in st.session_state:
    st.session_state.analysis_result = None
if "practice_lists" not in st.session_state:
    st.session_state.practice_lists = None
if "diagnostic_test" not in st.session_state:
    st.session_state.diagnostic_test = None
if "struggling_words" not in st.session_state:
    st.session_state.struggling_words = ""

# --- SIDEBAR ---
with st.sidebar:
    st.header("📋 Class Settings")
    student_name = st.text_input("Student Name (required)", key="name_input")

    st.divider()
    
    # Group Legend
    st.write("**📚 Diagnostic Groups**")
    st.caption("G0 Phonemic Awareness")
    st.caption("G1 Basic CVC Mapping")
    st.caption("G2 Digraphs")
    st.caption("G3 Silent E")
    st.caption("G4 Vowel Teams")
    st.caption("G5 R-Controlled")
    st.caption("G6 Clusters (Blends)")
    st.caption("G7 Multisyllabic")
    st.caption("G8 Reduction & Morphology")
    
    st.divider()
    
    # STUDENT STRUGGLING WORDS INPUT
    st.write("**📝 Words Student Has Encountered & Struggled To Spell**")
    struggling_words_input = st.text_area(
        "Enter words student has misspelled before",
        value=st.session_state.get("struggling_words", ""),
        height=80,
        placeholder="e.g., slep, stik, wif (comma-separated or one per line)",
        key="struggling_words_input"
    )
    
    st.divider()
    
    # WORD BANK TOOLS
    st.write("**🛠️ Word Bank Tools**")

if st.button("🧠 AI-Generate Personalized Practice Lists"):
    with st.spinner("Generating personalized practice lists with AI..."):
        from database_manager import generate_class_groups
        
        # Get active groups (only groups with students assigned)
        teaching_groups = generate_class_groups()
        
        word_banks_path = "word_banks"
        student_slips = []
        
        # Mapping from group titles back to g-keys
        title_to_key = {
            "Group 0: Phonemic Awareness": "g0",
            "Group 1: Basic CVC Mapping": "g1",
            "Group 2: Digraphs": "g2",
            "Group 3: Silent E": "g3",
            "Group 4: Vowel Teams": "g4",
            "Group 5: R-Controlled": "g5",
            "Group 6: Clusters/Blends": "g6",
            "Group 7: Multisyllabic": "g7",
            "Group 8: Reduction & Morphology": "g8"
        }
        
        # For each active group, get students and generate their personalized slips
        for group_title, students in teaching_groups.items():
            g_key = title_to_key.get(group_title)
            if not g_key:
                continue
            
            # Load base word bank for fallback
            file_path = os.path.join(word_banks_path, f"{g_key}.txt")
            base_words = []
            if os.path.exists(file_path):
                with open(file_path, "r") as f:
                    base_words = [line.strip() for line in f.readlines() if line.strip()]
            
            # Create a personalized slip for each student in this group
            for student_name in students:
                # Fetch student's teacher notes and struggling words from database
                from database_manager import get_latest_teacher_notes, get_struggling_words
                teacher_notes = get_latest_teacher_notes(student_name)
                db_struggling_words = get_struggling_words(student_name)
                
                # Combine: custom input takes priority, then DB records
                custom_input = st.session_state.get("struggling_words_input", "")
                combined_struggling = custom_input if custom_input.strip() else db_struggling_words
                
                # Generate personalized words using AI
                try:
                    personalized_words = generate_personalized_practice_words(
                        student_name=student_name,
                        target_group=g_key,
                        teacher_notes=teacher_notes,
                        struggling_words=combined_struggling,
                        custom_words_input=custom_input if custom_input.strip() else None
                    )
                except Exception as e:
                    st.warning(f"AI generation failed for {student_name}, using fallback: {e}")
                    # Fallback to random selection from word bank
                    personalized_words = random.sample(base_words, min(10, len(base_words))) if base_words else ["word" + str(i) for i in range(1, 11)]
                
                student_slips.append({
                    "student_name": student_name,
                    "group_title": group_title,
                    "words": personalized_words
                })
        
        st.session_state.practice_lists = student_slips
        st.rerun()

if st.button("📋 Generate New 20-Word Diagnostic Test"):
    with st.spinner("Creating diagnostic test..."):
        word_banks_path = "word_banks"
        test_words = []
        
        # 5 words from g1/g2
        g1_path = os.path.join(word_banks_path, "g1.txt")
        g2_path = os.path.join(word_banks_path, "g2.txt")
        g1_words = []
        g2_words = []
        if os.path.exists(g1_path):
            with open(g1_path, "r") as f:
                g1_words = [line.strip() for line in f.readlines() if line.strip()]
        if os.path.exists(g2_path):
            with open(g2_path, "r") as f:
                g2_words = [line.strip() for line in f.readlines() if line.strip()]
        combined = g1_words + g2_words
        test_words.extend(random.sample(combined, min(5, len(combined))))
        
        # 5 words from g3/g4
        g3_path = os.path.join(word_banks_path, "g3.txt")
        g4_path = os.path.join(word_banks_path, "g4.txt")
        g3_words = []
        g4_words = []
        if os.path.exists(g3_path):
            with open(g3_path, "r") as f:
                g3_words = [line.strip() for line in f.readlines() if line.strip()]
        if os.path.exists(g4_path):
            with open(g4_path, "r") as f:
                g4_words = [line.strip() for line in f.readlines() if line.strip()]
        combined = g3_words + g4_words
        test_words.extend(random.sample(combined, min(5, len(combined))))
        
        # 5 words from g5/g6
        g5_path = os.path.join(word_banks_path, "g5.txt")
        g6_path = os.path.join(word_banks_path, "g6.txt")
        g5_words = []
        g6_words = []
        if os.path.exists(g5_path):
            with open(g5_path, "r") as f:
                g5_words = [line.strip() for line in f.readlines() if line.strip()]
        if os.path.exists(g6_path):
            with open(g6_path, "r") as f:
                g6_words = [line.strip() for line in f.readlines() if line.strip()]
        combined = g5_words + g6_words
        test_words.extend(random.sample(combined, min(5, len(combined))))
        
        # 5 words from g7/g8
        g7_path = os.path.join(word_banks_path, "g7.txt")
        g8_path = os.path.join(word_banks_path, "g8.txt")
        g7_words = []
        g8_words = []
        if os.path.exists(g7_path):
            with open(g7_path, "r") as f:
                g7_words = [line.strip() for line in f.readlines() if line.strip()]
        if os.path.exists(g8_path):
            with open(g8_path, "r") as f:
                g8_words = [line.strip() for line in f.readlines() if line.strip()]
        combined = g7_words + g8_words
        test_words.extend(random.sample(combined, min(5, len(combined))))
        
        # Save to assessments folder
        assessments_folder = "assessments"
        if not os.path.exists(assessments_folder):
            os.makedirs(assessments_folder)
        
        date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_name = f"dynamic_test_{date_str}.txt"
        file_path = os.path.join(assessments_folder, file_name)
        
        with open(file_path, "w") as f:
            for word in test_words:
                f.write(word + "\n")
        
        st.session_state.diagnostic_test = {
            "words": test_words,
            "file_name": file_name
        }
        st.rerun()

st.divider()

# THE RESET BUTTON
if st.button("♻️ Start New Student"):
    st.session_state.raw_transcription = ""
    st.session_state.analysis_result = None
    st.session_state.practice_lists = None
    st.session_state.diagnostic_test = None
    st.session_state.struggling_words = ""
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
    if st.button("🚀 Step 4: Run Analysis"):
        if not student_name:
            st.warning("⚠️ Please enter a Student Name in the sidebar!")
        elif not edited_text:
            st.warning("⚠️ No text to analyze. Please read handwriting or type manually.")
        else:
            with st.spinner(f"Analyzing {student_name}..."):
                # Save the edited text to session state so it persists after analysis
                st.session_state.edited_transcription = edited_text
                # We use 'edited_text' here to match the text_area variable above
                result = run_scoring_crew(student_name, edited_text)
                
                if result is None:
                    st.error("The AI returned nothing. Check your internet or API key.")
                else:
                    st.session_state.analysis_result = result
                    
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
            import re
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
                # Fallback: silently extract g0-g8 mentions from raw_analysis using regex
                notes = "AI returned text but couldn't parse scores automatically. See below."
                # Extract any mentions of g0 through g8 from the raw text
                raw_text = data.raw if hasattr(data, 'raw') else str(data)
                found_groups = re.findall(r'g[0-8]', raw_text)
                # Remove duplicates while preserving order
                targets = list(dict.fromkeys(found_groups))

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
        
        # Mapping from ugly g-names to pretty human-readable titles
        GROUP_NAME_MAP = {
            "g0": "G0 Phonemic Awareness",
            "g1": "G1 Basic CVC Mapping",
            "g2": "G2 Digraphs",
            "g3": "G3 Silent E",
            "g4": "G4 Vowel Teams",
            "g5": "G5 R-Controlled",
            "g6": "G6 Clusters (Blends)",
            "g7": "G7 Multisyllabic",
            "g8": "G8 Reduction & Morphology"
        }
        
        # Create checkboxes for each group, pre-checked if AI suggested them
        selected_targets = []
        for g_key, pretty_name in GROUP_NAME_MAP.items():
            is_checked = g_key in targets
            if st.checkbox(pretty_name, value=is_checked, key=f"target_{g_key}"):
                selected_targets.append(g_key)
        
        # Use the checkbox selections as the targets
        targets = selected_targets
            
        # 2. THE FEEDBACK LOOP: The "Gold Standard" Editor (Side-by-Side Layout)
        st.write("### 👩‍🏫 Teacher Refinement")
        st.caption("Review the AI's notes above. Verify the student's attempts and record your final diagnostic decision.")
        
        # Create two columns for side-by-side text areas
        col1, col2 = st.columns(2)
        
        with col1:
            # Use the teacher's edited transcription (saved before analysis)
            edited_text = st.text_area(
                "Student's Spelling Attempts", 
                value=st.session_state.get('edited_transcription', st.session_state.raw_transcription),
                height=400,
                key="edited_text_final"
            )
        
        with col2:
            # We give them placeholder text if the AI didn't return a perfect string!
            default_text_area_val = notes if notes != "No notes generated." else "Type your own diagnostic notes here for this student..."
            
            final_notes = st.text_area(
                "Final Diagnostic Notes (The 'Gold Standard')", 
                value=default_text_area_val, 
                height=400
            )

        # 3. THE SAVE BUTTON
        if st.button("💾 Confirm & Save to Student History"):
            from database_manager import save_assessment
            
            # targets is already clean (g0, g1, etc.) from the checkboxes
            cleaned_targets = targets

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

            # Get struggling words from session state
            struggling_words = st.session_state.get("struggling_words_input", "")
            
            save_assessment(save_obj, edited_text, teacher_refinement=final_notes, struggling_words=struggling_words)
            
            st.success(f"✅ Final assessment for {student_name} has been saved with clean tags!")
            st.balloons()
            
# --- STEP 2: CLASS ANALYSIS ---
st.header("📊 Class Overview & Grouping")

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
    st.caption("Students are grouped here based on the targeted G-levels.")
    
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

# --- PRACTICE LISTS DISPLAY ---
# Display practice lists if generated
if st.session_state.practice_lists:
    st.header("🧠 AI-Generated Personalized Practice Lists")
    st.caption("💡 Copy the table below to paste into Google Sheets. Words are personalized based on each student's G-level and struggle areas.")
    
    # Convert to transposed table
    table_df = practice_lists_to_table(st.session_state.practice_lists)
    
    if table_df is not None:
        st.dataframe(
            table_df,
            hide_index=False,
            use_container_width=True
        )
        
        # Show summary
        st.success(f"✅ Table contains {len(table_df)} words for {len(table_df.columns)} students.")
    
    st.divider()

# Display diagnostic test if generated
if st.session_state.diagnostic_test:
    st.header("📋 New Diagnostic Test")
    st.caption(f"Generated test saved as: {st.session_state.diagnostic_test['file_name']}")
    
    st.subheader("20-Word Diagnostic Test")
    st.write("**Instructions:** Read these words aloud to the student and have them spell each one.")
    
    # Display words in a numbered list
    for i, word in enumerate(st.session_state.diagnostic_test['words'], 1):
        st.write(f"{i}. {word}")
    
    st.success(f"✅ Test saved to assessments/{st.session_state.diagnostic_test['file_name']}")
    st.divider()
