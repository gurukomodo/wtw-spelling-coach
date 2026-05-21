import json
import os
os.environ["OTEL_SDK_DISABLED"] = "true"
import pandas as pd
import streamlit as st
import random
import csv
import time
import base64
from datetime import datetime

from utils import preprocess_image
from spelling_logic import transcribe_handwriting, run_scoring_crew, generate_personalized_practice_words
from database_manager import (
    init_db, get_all_latest_results, assign_unowned_students, get_teacher_settings,
    save_teacher_settings, import_from_csv, get_student_history, get_mastered_words_from_raw,
    get_database_stats, fix_all_teacher_ids, clear_all_data, sync_identity_from_assessments,
    get_all_students_by_teacher, get_anonymized_history, get_all_students_for_allocation,
    update_student_teacher, register_teacher, get_all_teachers, get_all_students_with_status,
    assign_student_to_teacher, bulk_assign_orphans_to_teacher, bulk_assign_students,
    get_orphaned_students, get_all_students_with_status, get_teacher_student_status,
    get_raw_assessments, generate_class_groups, get_latest_teacher_notes, get_struggling_words,
    get_student_id_by_name, save_student_identity, get_student_name, get_pseudonym,
    generate_pseudonym, save_assessment, save_ai_report, get_name_for_id,
    get_all_test_templates, get_test_template, save_test_template, delete_test_template,
    save_draft_assessment, get_draft_assessments, delete_draft_assessment, get_sheet_data
)
import constants

# =============================================================================
# PAGE CONFIG
# =============================================================================
st.set_page_config(page_title="UnBoxEd Spelling Coach", layout="wide", page_icon="logo.svg")

# =============================================================================
# PERSISTENCE HELPERS
# =============================================================================
PROFILES_CSV = "students.csv"
SETTINGS_FILE = "settings.json"
ADMIN_EMAIL = "komododundee@gmail.com" 

def load_settings():
    """Load class-wide settings from JSON."""
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            st.error(f"Error loading settings: {e}")
    return {"unit_description": ""}

def save_settings_to_file(settings):
    """Save class-wide settings to JSON."""
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=4)
    except Exception as e:
        st.error(f"Error saving settings: {e}")

def get_or_create_student_id(teacher_id, name):
    """Returns the ID for a name, creating one if it doesn't exist in DB."""
    existing_id = get_student_id_by_name(teacher_id, name)
    if existing_id:
        return existing_id
    new_id = f"STU_{random.randint(1000, 9999)}"
    save_student_identity(teacher_id, new_id, name)
    return new_id

def migrate_legacy_profiles():
    """Scan students.csv for real names instead of IDs. Migrate them into the SQL student_identity table."""
    if not os.path.exists(PROFILES_CSV):
        return

    updated = False
    profiles_data = []
    teacher_id = st.session_state.get("user_name", "admin@example.com")  # Use user_name which contains the email
    
    try:
        with open(PROFILES_CSV, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            id_col = "Student ID" if "Student ID" in fieldnames else "Student Name"
            
            for row in reader:
                val = row.get(id_col, "")
                if val and not val.startswith("STU_"):
                    new_id = get_or_create_student_id(teacher_id, val)
                    row[id_col] = new_id
                    updated = True
                profiles_data.append(row)
                
        if updated:
            new_fieldnames = ["Student ID", "Struggles", "Mastered Words", "Target_Group"]
            with open(PROFILES_CSV, mode='w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=new_fieldnames)
                writer.writeheader()
                for row in profiles_data:
                    updated_row = {
                        "Student ID": row.get("Student ID") or row.get("Student Name"),
                        "Struggles": row.get("Sruggles", ""),
                        "Mastered Words": row.get("Mastered Words", ""),
                        "Target_Group": row.get("Target_Group", "g1")
                    }
                    writer.writerow(updated_row)
            st.toast(" Legacy student profiles migrated to Cloud-hosted Map.")
            
    except Exception as e:
        st.error(f"Migration error: {e}")

def load_profiles():
    """Load student profiles from CSV into a dictionary."""
    profiles = {}
    if os.path.exists(PROFILES_CSV):
        try:
            with open(PROFILES_CSV, mode='r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    sid = row.get("Student ID")
                    teacher_id = row.get("teacher_id", st.session_state.get("user_email"))
                    if sid:
                        profiles[sid] = {
                            "struggles": row.get("Struggles", ""),
                            "mastered": row.get("Mastered Words", ""),
                            "target_group": row.get("Target_Group", "g1"),
                            "teacher_id": teacher_id
                        }
        except Exception as e:
            st.error(f"Error loading profiles: {e}")
    return profiles

def save_profile(student_id, struggles, mastered, target_group):
    """Save/Update a student profile in the CSV."""
    profiles = load_profiles()
    profiles[student_id] = {"struggles": struggles, "mastered": mastered, "target_group": target_group, "teacher_id": st.session_state.get("user_email")}
    
    try:
        with open(PROFILES_CSV, mode='w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=["Student ID", "Struggles", "Mastered Words", "Target_Group", "teacher_id"])
            writer.writeheader()
            for sid, data in profiles.items():
                writer.writerow({
                    "Student ID": sid,
                    "Struggles": data["struggles"],
                    "Mastered Words": data["mastered"],
                    "Target_Group": data["target_group"],
                    "teacher_id": data["teacher_id"]
                })
    except Exception as e:
        st.error(f"Error saving profile: {e}")

def practice_lists_to_table(practice_lists):
    """Convert practice lists into a transposed DataFrame."""
    if not practice_lists:
        return None
    
    data = {}
    for slip in practice_lists:
        student_name = slip["student_name"]
        words = slip["words"]
        data[student_name] = words
    
    df = pd.DataFrame(data)
    df.index = [f"Word {i+1}" for i in range(len(df))]
    return df

# =============================================================================
# INITIALIZE SESSION STATE
# =============================================================================
def initialize_session_state():
    """Initialize all session state variables and database."""
    # Initialize database first - must happen before any DB queries
    init_db()
    
    # Only set authenticated to False if it doesn't exist (preserve existing state)
    if 'authenticated' not in st.session_state:
        st.session_state.authenticated = False
    
    if 'role' not in st.session_state:
        st.session_state.role = None
    
    if "user_email" not in st.session_state:
        st.session_state.user_email = None
    
    for key, default in [
        ("raw_transcription", ""), ("analysis_result", None), ("practice_lists", None),
        ("diagnostic_test", None), ("struggling_words", ""), ("students", load_profiles()),
        ("edited_transcription", ""), ("classroom_data", None), ("selected_student", None), ("is_admin", False), ("logged_in", False), ("user_email", None),
        ("authenticated", False), ("role", None), ("intended_words_input", ""), ("processed_intended_words", ""),
        ("current_word_list_mode", "select_existing"), # Default to selecting existing list
        ("last_used_assessment_list_id", None), # For smart memory of last used list
    ]:
        if key not in st.session_state:
            st.session_state[key] = default

    if "unit_description" not in st.session_state:
        st.session_state.unit_description = load_settings().get("unit_description", "")

# =============================================================================
# MAIN ROUTER
# =============================================================================
def main():
    # Router: Handle pending navigation before sidebar widget creation
    if 'next_page' in st.session_state:
        st.session_state.navigation_menu = st.session_state.next_page
        del st.session_state.next_page
    
    initialize_session_state()
    
    # Initialize navigation_menu only if it doesn't exist
    if 'navigation_menu' not in st.session_state:
        st.session_state.navigation_menu = 'Class'
    
    # 1. Catch the Interceptor (Login button click)
    if st.session_state.get('login_button'):
        selection = st.session_state.get('login_teacher_select')
        if selection:
            # logic to define both 'name' and 'email' from the selection string
            if '(' in selection:
                # Splits "Glen Pamment (email@test.com)" into name and email
                name = selection.split(' (')[0].strip()
                email = selection.split('(')[-1].replace(')', '').strip()
            else:
                # Fallback if the string doesn't follow the "Name (Email)" format
                name = selection.strip()
                email = selection.strip()

            # Now that both variables are defined, save them to session_state
            st.session_state.logged_in = True
            st.session_state.user_email = email
            st.session_state.user_name = name  # This won't error now
            st.session_state.authenticated = True
            
            if email == 'komododundee@gmail.com':
                st.session_state.is_admin = True
                
            st.rerun()

    # 2. Check for URL Persistence
    if st.query_params.get("email"):
        st.session_state.logged_in = True
        st.session_state.user_email = st.query_params.get("email")

    # 3. Final Routing
    if st.session_state.get('logged_in'):
        show_teacher_dashboard()
    elif st.session_state.get('go_to_login'):
        show_login_page()
    else:
        show_registration_page()

# =============================================================================
# PAGE: REGISTRATION
# =============================================================================
def show_registration_page():
    st.image("logo.svg", width=200)
    st.title("Welcome to UnBoxEd Spelling Coach")
    
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Returning Coach")
        st.info("Already have an account? Click below to select your profile and log in.")
        # This is the trigger for your new main() routing logic
        if st.button("Go to Login Page →", use_container_width=True):
            st.session_state.go_to_login = True
            st.rerun()
    
    with col2:
        st.subheader("New Coach")
        with st.form("registration_form", clear_on_submit=True):
            new_name = st.text_input("Full Name")
            new_email = st.text_input("Email Address")
            submit_button = st.form_submit_button("Register & Log In")

            if submit_button:
                if new_name and new_email:
                    from database_manager import register_teacher
                    register_teacher(new_email, new_name)
                    
                    # Log them in immediately after registration
                    st.session_state.authenticated = True
                    st.session_state.user_email = new_email
                    st.session_state.logged_in = True
                    st.session_state.role = 'teacher'
                    
                    st.query_params["email"] = new_email
                    st.rerun()
                else:
                    st.error("Please provide both name and email.")

# =============================================================================
# PAGE: LOGIN
# =============================================================================
def show_login_page():
    """Separate login page for existing teachers."""
    st.image("logo.svg", width=200)
    st.title("Teacher Login")
    
    from database_manager import get_all_teachers
    existing_teachers = get_all_teachers()
    
    if existing_teachers:
        # Create a list of "Name (Email)" for the dropdown
        teacher_options = []
        for t in existing_teachers:
            if t['name'] and t['name'].strip():
                name = t['name']
            else:
                # Extract name from email if name is None or empty
                name = t['email'].split('@')[0]
            teacher_options.append(f"{name} ({t['email']})")

        print(f"DEBUG: Login page - Teacher options: {teacher_options}")
        
        selected_teacher = st.selectbox("Select your account:", teacher_options, key='login_teacher_select')
        print(f"DEBUG: Login page - Selected teacher: {selected_teacher}")
        
        # Login button
        if st.button("Login", key="login_button"):
            print(f"DEBUG: Login button clicked for: {selected_teacher}")
            print(f"DEBUG: Session state before login: {st.session_state}")
            
            # Extract email from string "Name (email@test.com)"
            if '(' in selected_teacher and ')' in selected_teacher:
                email = selected_teacher.split('(')[-1].replace(')', '')
                name = selected_teacher.split(' (')[0]
                print(f"DEBUG: Extracted from parentheses - Name: {name}, Email: {email}")
            else:
                # Handle case where selection might be just an email
                if '@' in selected_teacher:
                    email = selected_teacher
                    name = selected_teacher.split('@')[0]
                    print(f"DEBUG: Extracted from email - Name: {name}, Email: {email}")
                else:
                    email = selected_teacher
                    name = selected_teacher
                    print(f"DEBUG: Using as-is - Name: {name}, Email: {email}")
        
            print(f"DEBUG: Parsed from selection - Name: {name}, Email: {email}")
            
            # Use the extracted email directly as actual_email
            actual_email = email
            
            print(f"DEBUG: Teacher lookup - Using extracted email: {actual_email}")
            print(f"DEBUG: Teacher lookup - Name: {name}, Found email: {actual_email}")
            print(f"DEBUG: Teacher lookup completed successfully")
            
            st.session_state.authenticated = True
            st.session_state.user_name = actual_email or email  # Store actual email
            st.session_state.user_email = actual_email or email  # Store actual email
            st.session_state.logged_in = True  # Set logged_in flag
            st.session_state.user_email = actual_email or email  # Set user_email for consistency
            st.session_state.role = 'teacher'
            
            print(f"DEBUG: LOGIN SUCCESS - Setting logged_in=True, user_email={email}")
            print(f"DEBUG: VERIFYING ADMIN - Is {email} == komododundee@gmail.com? {email == 'komododundee@gmail.com'}")
            
            # Clear the registration selection to avoid confusion
            if 'reg_teacher_select' in st.session_state:
                del st.session_state['reg_teacher_select']
            
            # Park login status in URL for persistence
            st.query_params["email"] = email
            st.query_params["login"] = email
            st.rerun()
    
    else:
        st.info("No accounts found. Please register first.")
        
    # Back to registration button
    if st.button("← Back to Registration", key="back_to_reg"):
        if 'reg_teacher_select' in st.session_state:
            del st.session_state['reg_teacher_select']
        st.rerun()

# =============================================================================
# PAGE: TEACHER DASHBOARD (with sidebar navigation)
# =============================================================================
def show_teacher_dashboard():
    """Main dashboard with sidebar navigation for authenticated users."""
    # Sidebar branding and logout
    st.sidebar.image("logo.svg", width=200)
    st.sidebar.success(f"👤 Logged in: {st.session_state.user_name}")
    
    if st.sidebar.button("Log Out", key="logout_button"):
        # Nuclear Logout - complete key deletion
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        
        # Force app back to login screen
        st.rerun()
    
    # Sidebar navigation using radio buttons
    page_options = ["Class", "Student", "Admin"]
    
    # Only use index parameter if navigation_menu is not already set in session state
    # This prevents Double Value error when session state already has a value
    if 'navigation_menu' in st.session_state:
        page = st.sidebar.radio("Navigation", page_options, key="navigation_menu")
    else:
        default_page_idx = 0  # Default to Class page
        page = st.sidebar.radio("Navigation", page_options, index=default_page_idx, key="navigation_menu")
    
    # Initialize database and migrate legacy data 
    migrate_legacy_profiles()
    
    # Get current teacher email (standardized)
    current_teacher_email = st.session_state.get('user_email')
    
    # Student selector in sidebar (shown when Student page is active)
    selected_student_id = None
    if page == "Student":
        # 1. Fetch real students from the database
        from database_manager import get_all_students_by_teacher
        all_students = get_all_students_by_teacher(current_teacher_email)
        
        student_options = {}
        for s in all_students:
            # We use 'name' and 'student_id' keys from the database results
            student_options[s['name']] = s['student_id']
        
        if student_options:
            # Determine the starting index (so it stays on the student you clicked)
            current_names = list(student_options.keys())
            start_index = 0
            
            # Check if a student was selected from the Class page
            if st.session_state.get('selected_student_id'):
                try:
                    # Get the name for the selected student ID
                    selected_sid = st.session_state.get('selected_student_id')
                    selected_name = get_student_name(current_teacher_email, selected_sid)
                    if selected_name in current_names:
                        start_index = current_names.index(selected_name)
                except:
                    start_index = 0
                
            selected_name = st.sidebar.selectbox("Select Student", options=current_names, index=start_index, key="sidebar_student_selector")
            newly_selected_student_id = student_options[selected_name]

            # Check if student changed and perform state sweep
            if st.session_state.get('current_student_id') != newly_selected_student_id:
                st.session_state.current_student_id = newly_selected_student_id
                st.session_state.current_student_name = selected_name
                
                # Full state sweep to prevent data leakage from previous student
                for key in [
                    'uploaded_file', 'raw_transcription', 'edited_transcription', 'analysis_result',
                    'practice_lists', 'diagnostic_test', 'struggling_words', 'struggling_words_input',
                    'mastered_words_input', 'teacher_observations_input', 'final_diagnostic_notes',
                    'analysis_notes', 'raw_ai_result', 'shadow_data', 'last_fetched_student',
                    'student_attempts_for_report', 'pending_student_name', 'pending_student_id',
                    'pending_pseudonym', 'selected_student', # Clear any pending/previous student context
                    'g0_score', 'g1_score', 'g2_score', 'g3_score', 'g4_score', 'g5_score', 'g6_score', 'g7_score', 'g8_score', # G-level scores
                    f'progress_review_{st.session_state.get("current_student_id")}', # Clear previous student's progress review
                    f'classroom_data_{st.session_state.get("current_student_id")}', # Clear previous student's classroom data
                    'selected_test_template', # Clear selected test template
                ]:
                    if key in st.session_state:
                        del st.session_state[key]
                
                # Rerun to clear UI elements and load new student data cleanly
                st.rerun()
            
            selected_student_id = newly_selected_student_id # Use the confirmed student ID
    
    # Route to appropriate page function
    if page == "Class":
        display_class_page()
    elif page == "Student":
        if selected_student_id:
            display_student_detail_view(selected_student_id, current_teacher_email) # Pass teacher_email
        else:
            st.info("No students assigned to your class yet. Add a student via the 'Class' page.")
    elif page == "Admin":
        display_admin_page()

# =============================================================================
# COMPONENT: CLASS PAGE (student-centric view)
# =============================================================================
def display_class_page():
    st.title("Class Overview")
    
    # 1. Fetch Students from DB
    from database_manager import get_all_students_by_teacher
    # Note: Ensure this returns student_id, real_name, and suggested_next
    students = get_all_students_by_teacher(st.session_state.user_email)
    
    # 2. SHOW STUDENT LIST FIRST
    if not students:
        st.info("No students in your class yet. Use the form below to add one.")
    else:
        st.subheader("Your Students")
        h1, h2, h3 = st.columns([3, 1, 2])
        h1.caption("NAME")
        h2.caption("GROUP")
        h3.caption("ACTION")

        for s in students:
            # We use 'student_id' and 'name' to match your database_manager logic
            sid = s.get('student_id')
            sname = s.get('name')
            sgroup = s.get('current_g_level', 'g1')
            
            col1, col2, col3 = st.columns([3, 1, 2])
            col1.write(f"**{sname}**")
            col2.write(f"Group {sgroup[-1] if sgroup else '1'}")
            
            # Use 'student_id' for the key to avoid the KeyError
            if col3.button("View Profile", key=f"btn_{sid}"):
                st.session_state.selected_student_id = sid
                st.session_state.next_page = "Student"
                st.rerun()

    st.divider()

    # 3. ADD STUDENT SECTION AT THE BOTTOM
    with st.expander("➕ Add New Student"):
        with st.form("add_new_student", clear_on_submit=True):
            name = st.text_input("Full Name")
            group = st.selectbox(
                "Assign to Group",
                options=list(constants.DIAGNOSTIC_GROUPS.keys()),
                format_func=lambda x: constants.DIAGNOSTIC_GROUPS[x]['name'],
                index=1
            )

            if st.form_submit_button("Create Student Record"):
                if name:
                    from database_manager import add_student
                    if add_student(st.session_state.user_email, name, group): # Changed from f"g{group}" to group
                        st.success(f"Success! {name} added.")
                        st.rerun()
                else:
                    st.error("Please enter a name.")

def display_student_detail_view(student_id, current_teacher_email):
    """Display simplified detail view for a selected student."""
    # Get student name with proper fallback
    student_name = get_student_name(current_teacher_email, student_id) or f"Student {student_id}"
    
    # Display student name as large header
    st.title(student_name)
    
    # Fetch latest assessment data from database
    from database_manager import get_student_history
    history = get_student_history(student_id, teacher_id=current_teacher_email, admin=False)
    
    # Get the most recent assessment for word analysis
    struggles = []
    mastered = []
    target_group = 'g1'
    
    if history:
        latest = history[-1]  # Most recent assessment
        if latest.get('struggling_words'):
            struggles = latest.get('struggling_words', '').split(',') if latest.get('struggling_words') else []
        if latest.get('suggested_next'):
            target_group = latest.get('suggested_next', 'g1')
    
    # Display only specific word analysis data used for coaching
    st.subheader("Word Analysis Data")
    
    # Display current struggling words in a 3-column grid
    if struggles:
        st.write("**Current Struggling Words:**")
        filtered_struggles = [w.strip() for w in struggles if w.strip()]
        cols = st.columns(3)
        for i, word in enumerate(filtered_struggles):
            cols[i % 3].write(f"• {word}")
    
    # Display current mastered words
    if mastered:
        st.write("**Current Mastered Words:**")
        for word in mastered:
            if word.strip():
                st.write(f"• {word.strip()}")
    
    if not struggles and not mastered:
        st.info("No word analysis data recorded yet.")

    st.divider()

    # Run Global Analysis section
    st.subheader("Global Analysis")
    st.caption("Generate coaching report and practice list from existing data without new photo upload")

    if st.button("🔄 Refresh Coaching Plan", key=f"refresh_analysis_{student_id}"):
        with st.spinner("Running global analysis..."):
            try:
                # Fetch latest classroom data from Google Sheets
                current_settings = get_teacher_settings(current_teacher_email)
                sheet_url = current_settings.get('google_sheet_url', '')

                shadow_data = []
                if sheet_url:
                    try:
                        shadow_data_result = get_sheet_data(sheet_url, student_name, None)
                        if isinstance(shadow_data_result, dict) and "error" in shadow_data_result:
                            st.error(f"Failed to fetch Google Sheet data: {shadow_data_result['error']}")
                            shadow_data = [] # Ensure shadow_data is empty on error
                        elif isinstance(shadow_data_result, list):
                            shadow_data = shadow_data_result
                            if shadow_data:
                                st.success(f"Fetched {len(shadow_data)} entries from Google Sheets")
                            else:
                                st.info(f"No recent classroom observations found for '{student_name}' in Google Sheet.")
                        else:
                            st.error(f"Unexpected response from Google Sheet fetch: {shadow_data_result}")
                            shadow_data = []
                    except Exception as e:
                        st.error(f"Failed to fetch Google Sheet data: {e}. Please check the URL and permissions.")
                        shadow_data = [] # Ensure shadow_data is empty on error

                # Get most recent assessment scores
                latest_assessment = None
                if history:
                    latest_assessment = history[-1]
                    st.info(f"Using latest assessment from {latest_assessment.get('created_at', 'unknown date')}")

                if not latest_assessment:
                    st.error("No assessment data found. Please complete an assessment first.")
                else:
                    # Prepare data for progress review analysis
                    transcription_text = ""  # Empty = progress review mode
                    current_g_level = latest_assessment.get('suggested_next', 'g1')
                    g_scores = {gid: latest_assessment.get(field, 0) for gid, field in constants.DIAGNOSTIC_GROUPS.items()}

                    try:
                        analysis_result = run_scoring_crew(
                            student_id,
                            transcription_text,
                            intended_words="",
                            shadow_data=shadow_data,
                            analysis_complexity="Standard"
                        )

                        st.session_state[f'progress_review_{student_id}'] = {
                            'analysis_result': analysis_result,
                            'current_g_level': current_g_level,
                            'g_scores': g_scores,
                            'shadow_data_count': len(shadow_data) if shadow_data else 0
                        }

                        st.success("Progress review complete! Review and confirm the group allocation below.")
                        st.rerun()

                    except Exception as e:
                        st.error(f"Failed to run global analysis: {str(e)}. Please check AI service status.")
            except Exception as e: # Catch any errors from the main try block within the button
                st.error(f"An unexpected error occurred during the 'Refresh Coaching Plan' process: {e}")

    progress_review_key = f'progress_review_{student_id}'
    if st.session_state.get(progress_review_key):
        review_data = st.session_state[progress_review_key]
        analysis_result = review_data['analysis_result']
        current_g_level = review_data['current_g_level']
        g_scores = review_data['g_scores']
        shadow_data_count = review_data['shadow_data_count']

        st.subheader("Progress Review Results")

        col1, col2 = st.columns(2)

        with col1:
            st.write("**Current Group Allocation:**")
            st.metric("Current G-Level", current_g_level)
            st.write("**Current Scores:**")
            for g, score in g_scores.items():
                st.write(f"{g.upper()}: {score}%")

        with col2:
            st.write("**AI Analysis Based on Google Sheet Data:**")
            teacher_notes = getattr(analysis_result, 'teacher_notes', '')
            st.write(teacher_notes)

            suggested_groups = getattr(analysis_result, 'suggested_next_groups', [])
            st.write(f"**Suggested Groups:** {', '.join(suggested_groups)}")

        if shadow_data_count > 0:
            st.write(f"**Evidence Source:** Based on {shadow_data_count} recent classroom observations from Google Sheets")

        st.subheader("Confirm Group Allocation")
        suggested_g_level = suggested_groups[0] if suggested_groups else current_g_level

        col_confirm, col_override = st.columns([1, 2])

        with col_confirm:
            if st.button("✅ Confirm Suggested Group", key=f"confirm_group_{student_id}"):
                # This logic should update the student's group (e.g., in latest assessment or profile)
                st.success(f"Group allocation updated to {suggested_g_level}")
                del st.session_state[progress_review_key]
                st.rerun()

        with col_override:
            override_options = list(constants.DIAGNOSTIC_GROUPS.keys())
            override_selection = st.selectbox(
                "Or manually select a different group:",
                override_options,
                index=override_options.index(current_g_level) if current_g_level in override_options else 1,
                key=f"override_group_{student_id}"
            )

            if st.button("📝 Override with Manual Selection", key=f"override_btn_{student_id}"):
                st.success(f"Group allocation manually set to {override_selection}")
                del st.session_state[progress_review_key]
                st.rerun()

        st.divider()
    
    # Section for AI-Generated Practice Lists
    st.subheader("AI-Generated Practice Lists")
    if st.button("✨ Generate Personalized Practice Lists", key=f"gen_practice_{student_id}"):
        with st.spinner("Generating personalized practice lists with AI..."):
            try:
                # Fetch necessary data for generation
                teacher_notes = get_latest_teacher_notes(student_id)
                db_struggling_words = get_struggling_words(student_id)
                
                # Using dummy values for now, this would be from student profile/latest assessment
                mastered_words = st.session_state.get("mastered_words_input", "") 
                unit_description = st.session_state.get("unit_description", "")
                
                personalized_words = generate_personalized_practice_words(
                    student_id=student_id,
                    target_group=target_group, # Use current_g_level from above or a selected target
                    teacher_notes=teacher_notes,
                    struggling_words=db_struggling_words,
                    mastered_words=mastered_words,
                    unit_description=unit_description,
                    custom_words_input=None # No custom input from this flow
                )
                
                st.session_state[f'practice_list_{student_id}'] = {
                    "student_name": student_name, "group_title": target_group,
                    "words": personalized_words
                }
                st.success("Personalized practice list generated!")
                st.rerun()
            except Exception as e:
                st.error(f"Failed to generate practice lists: {str(e)}. Please check AI service status.")

    # Display practice list if available
    practice_list_key = f'practice_list_{student_id}'
    if st.session_state.get(practice_list_key):
        practice_data = st.session_state[practice_list_key]
        st.write(f"**Practice List for {practice_data['student_name']} ({practice_data['group_title']}):**")
        for i, word in enumerate(practice_data['words']):
            st.write(f"{i+1}. {word}")
        
        # Option to clear the practice list
        if st.button("Clear Practice List", key=f"clear_practice_{student_id}"):
            del st.session_state[practice_list_key]
            st.rerun()

    st.divider()

    # AI Coach Report section
    st.subheader("AI Coach Report")
    st.caption("Generate a comprehensive coaching report based on student's history.")
    
    # AI Coaching button for each student
    if st.button(f"Generate AI Coach Report for {student_name}", key=f"ai_{student_id}"):
        with st.spinner(f"Consulting AI about {student_name} (pseudonym: {get_pseudonym(current_teacher_email, student_id)})..."):
            try:
                history = get_student_history(student_id, teacher_id=current_teacher_email, admin=False)
                from spelling_logic import get_ai_coaching_report
                
                # Assuming current_g_level is available from the latest assessment or student profile
                latest_assessment = history[-1] if history else {}
                student_g_level = latest_assessment.get('suggested_next', 'g1')
                
                raw_report = get_ai_coaching_report(
                    student_alias=get_pseudonym(current_teacher_email, student_id), 
                    g_level=student_g_level, 
                    history=history
                )
                st.session_state[f'raw_report_{student_id}'] = raw_report
                st.session_state[f'edit_mode_{student_id}'] = True
                st.success("AI coaching report generated!")
                st.rerun()
            except Exception as e:
                st.error(f"Failed to generate AI coach report: {str(e)}. Please check AI service status and student history.")
                st.session_state[f'edit_mode_{student_id}'] = False # Ensure edit mode is off

    # Display editable report if in edit mode
    edit_key = f'edit_mode_{student_id}'
    if st.session_state.get(edit_key, False):
        raw_report = st.session_state.get(f'raw_report_{student_id}', '')
        
        st.markdown("---*")
        st.subheader(f"AI Coaching Report for {student_name}")
        st.caption("Review and edit the AI's suggestions before saving.")
        
        edited_report = st.text_area(
            "Coach Report (editable)",
            value=raw_report,
            height=300,
            key=f'report_editor_{student_id}'
        )
        
        col_save1, col_save2 = st.columns([1, 4])
        with col_save1:
            if st.button("Confirm & Save Report", key=f'save_report_{student_id}', type="primary"):
                if edited_report.strip():
                    try:
                        save_ai_report(
                            student_id=student_id,
                            teacher_id=current_teacher_email,
                            report_content=edited_report
                        )
                        st.success(f"Report saved for {student_name}!")
                        st.session_state[edit_key] = False
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed to save AI report: {e}. Please try again.")
                else:
                    st.warning("Report cannot be empty.")
        with col_save2:
            if st.button("Discard", key=f'discard_report_{student_id}'):
                st.session_state[edit_key] = False
                st.rerun()
        st.markdown("---*")
        
    st.divider()

    # Add Assessment section with Step 1-5 workflow
    st.subheader("Add New Assessment")
    display_assessment_workflow(student_id, student_name)

def display_assessment_workflow(student_id, student_name):
    """Display the complete Step 1-5 assessment workflow."""
    current_teacher_email = st.session_state.get('user_email')
    current_settings = get_teacher_settings(current_teacher_email)
    sheet_url = current_settings.get('google_sheet_url', '')
    
    # Use student-specific key for classroom data
    classroom_data_key = f'classroom_data_{student_id}'

    # Step 1: Define Assessment Target Words
    with st.expander("1. Define Assessment Target Words", expanded=True):
        current_teacher_email = st.session_state.get('user_email')
        
        # UI for selecting or creating a word list
        st.session_state.current_word_list_mode = st.radio(
            "Choose a word list method:",
            options=["Select Existing List", "Create New List"],
            key=f"word_list_mode_{student_id}",
            index=0 if st.session_state.current_word_list_mode == "select_existing" else 1,
            horizontal=True
        )

        selected_list_name_display = None # To display selected list name

        if st.session_state.current_word_list_mode == "Select Existing List":
            named_lists = database_manager.get_named_lists(current_teacher_email)
            
            list_options = {"Select a saved list...": None}
            for lst in named_lists:
                list_options[lst['list_name']] = lst['id']
            
            # Smart memory: default to last used list if available and in options
            default_index = 0
            if st.session_state.get("last_used_assessment_list_id"):
                last_used_list = database_manager.get_named_list_by_id(st.session_state.last_used_assessment_list_id)
                if last_used_list and last_used_list['list_name'] in list_options:
                    default_index = list(list_options.keys()).index(last_used_list['list_name'])
            
            selected_list_id = st.selectbox(
                "Select an existing word list:",
                options=list(list_options.keys()),
                format_func=lambda x: x,
                key=f"select_word_list_{student_id}",
                index=default_index
            )
            
            if selected_list_id and list_options[selected_list_id] is not None:
                list_data = database_manager.get_named_list_by_id(list_options[selected_list_id])
                if list_data:
                    st.session_state.intended_words_input = list_data['target_words']
                    st.session_state.current_list_id = list_data['id'] # Store ID for smart memory
                    selected_list_name_display = list_data['list_name']
                else:
                    st.session_state.intended_words_input = ""
                    st.session_state.current_list_id = None
            else:
                st.session_state.intended_words_input = ""
                st.session_state.current_list_id = None
            
            if st.session_state.current_list_id:
                st.info(f"Selected list: **{selected_list_name_display}** (ID: {st.session_state.current_list_id})")
            else:
                st.info("No list selected. Please create one or select from above.")


        else: # Create New List
            new_list_name = st.text_input(
                "Name for this new word list (e.g., 'Weekly Spelling 1'):",
                key=f"new_list_name_{student_id}"
            )
            st.session_state.intended_words_input = st.text_area(
                "Enter the intended words (comma-separated or one per line):",
                value=st.session_state.get("intended_words_input", ""), # Keep value if typed before switching modes
                height=150,
                key=f"intended_words_input_{student_id}",
                placeholder="e.g., cat, dog, run, jump\nor\ncat\ndog\nrun\njump"
            )
            if st.button("Save New List", key=f"save_new_list_btn_{student_id}"):
                if new_list_name and st.session_state.intended_words_input:
                    success = database_manager.save_named_list(
                        current_teacher_email,
                        new_list_name.strip(),
                        st.session_state.intended_words_input.strip()
                    )
                    if success:
                        st.success(f"Word list '{new_list_name}' saved!")
                        st.session_state.current_word_list_mode = "Select Existing List" # Switch to select after saving
                        # Automatically select the newly saved list
                        named_lists_after_save = database_manager.get_named_lists(current_teacher_email)
                        for lst in named_lists_after_save:
                            if lst['list_name'] == new_list_name.strip():
                                st.session_state.last_used_assessment_list_id = lst['id']
                                break
                        st.rerun()
                    else:
                        st.error("Failed to save list. A list with this name might already exist.")
                else:
                    st.warning("Please provide both a name and words for the new list.")

    # Normalize target words for consistent passing
    if st.session_state.intended_words_input:
        processed_intended_words = [
            word.strip()
            for part in st.session_state.intended_words_input.split(',')
            for word in part.split('\n')
            if word.strip()
        ]
        st.session_state.processed_intended_words = ", ".join(processed_intended_words)
    else:
        st.session_state.processed_intended_words = "" # Ensure it's empty if no input
    
    if sheet_url and not st.session_state.get(classroom_data_key):
        # Fetch classroom data for this student
        try:
            shadow_data_result = get_sheet_data(sheet_url, student_name, None)
            if isinstance(shadow_data_result, dict) and "error" in shadow_data_result:
                st.error(f"Failed to fetch classroom data: {shadow_data_result['error']}")
            elif isinstance(shadow_data_result, list):
                st.session_state[classroom_data_key] = shadow_data_result
                if shadow_data_result:
                    print(f"DEBUG: Fetched {len(shadow_data_result)} classroom data entries for {student_name}")
                else:
                    st.info(f"No recent classroom observations found for '{student_name}' in Google Sheet.")
            else:
                st.error(f"Unexpected response from classroom data fetch: {shadow_data_result}")
        except Exception as e:
            st.error(f"Failed to fetch classroom data: {e}. Please check the Google Sheet URL and permissions.")
    
    # Display classroom data if available for this student
    if st.session_state.get(classroom_data_key):
        st.subheader("Classroom Data")
        st.write(f"Found {len(st.session_state[classroom_data_key])} recent observations:")
        
        for entry in st.session_state[classroom_data_key][:5]:  # Show latest 5
            st.write(f"• {entry.get('incorrect', '')} → {entry.get('intended', '')}")
    
    # Step 2: Photo Upload
    st.subheader("Step 2: Upload Photo")
    uploaded_file = st.file_uploader("Upload student's handwriting photo", type=['png', 'jpg', 'jpeg'], key=f"upload_photo_{student_id}")
    
    if uploaded_file:
        # Pre-process & Layout
        clean_base64, clean_img = preprocess_image(uploaded_file)
        
        col_img, col_text = st.columns([1, 1])
        
        with col_img:
            st.subheader("AI's View (Cleaned)")
            st.image(clean_img, width="stretch")
            
            if st.button("Step 3: Read Handwriting", key=f"read_handwriting_{student_id}") and not st.session_state.get('processing', False):
                st.session_state['processing'] = True
                print('DEBUG: Handwriting Analysis Started...')
                with st.spinner('AI is reading handwriting...'):
                    try:
                        # Pass intended words to transcription
                        result_text = transcribe_handwriting(clean_base64, intended_words=st.session_state.processed_intended_words)
                        
                        if result_text:
                            st.success("Data received from AI")
                            
                            # The AI's transcription format might be "intended:attempt", so we don't hardcode "fan:"
                            # We keep the raw result to allow the analysis crew to process it as is.
                            cleaned_text = result_text # Use raw result directly
                            
                            st.session_state['edited_transcription'] = cleaned_text
                            st.session_state['raw_transcription'] = cleaned_text
                            st.session_state['processing'] = False
                            print(f"DEBUG: Saved to state: {st.session_state['edited_transcription'][:20]}...")
                        else:
                            st.error("AI returned empty string for transcription.")
                            st.session_state['processing'] = False
                    except Exception as e:
                        st.error(f"Failed to transcribe handwriting: {e}")
                        st.session_state['processing'] = False
        
        with col_text:
            st.subheader("Step 4: Verify & Edit Transcription")
            
            if not st.session_state.get("edited_transcription"):
                st.info("Waiting for handwriting analysis...")
            
            edited_text = st.text_area(
                "Verify & Edit Transcription", 
                value=st.session_state.get("edited_transcription", ""),
                height=200,
                key=f"edited_transcription_{student_id}" # Use student_id in key for uniqueness
            )
            st.session_state.edited_transcription = edited_text # Keep session state updated

            # Analysis Complexity Control
            st.subheader("Step 5: Analysis Settings")
            analysis_complexity = st.select_slider(
                "Analysis Complexity",
                options=["Brief", "Standard", "Detailed"],
                value="Brief",
                key=f"analysis_complexity_{student_id}",
                help="Brief: 2-3 sentence summary | Standard: Moderate detail | Detailed: Deep phonological breakdown"
            )
            
            # Step 6: Run Analysis
            if st.button("Step 6: Run Analysis", key=f"run_analysis_{student_id}"):
                if not student_name:
                    st.warning("Please select a student!")
                elif not edited_text:
                    st.warning("Please complete the transcription first!")
                else:
                    with st.spinner("Running AI analysis..."):
                        try:
                            # Sync Step 3 data to Step 5 report field
                            st.session_state['student_attempts_for_report'] = st.session_state.edited_transcription
                            print(f"DEBUG: Syncing {len(st.session_state.edited_transcription)} chars to Step 5 report field.")
                            
                            # Use intended words from session state, or fall back to default if not provided
                            intended_words_for_analysis = st.session_state.get("processed_intended_words")
                            if not intended_words_for_analysis:
                                # Fallback if target words were not provided in step 1
                                intended_words_for_analysis = "fan, pet, dig, rob, hope, wait, gum, sled, stick, shine" 
                            
                            shadow_data = st.session_state.get(classroom_data_key, [])

                            print(f"DEBUG: Sending {len(st.session_state.edited_transcription)} chars to AI Crew with intended words: {intended_words_for_analysis[:50]}...")
                            print(f"DEBUG: Contextual evidence entries: {len(shadow_data) if shadow_data else 0}")

                            analysis_result = run_scoring_crew(
                                student_id,
                                st.session_state.edited_transcription,
                                intended_words=intended_words_for_analysis, # Pass the collected intended words
                                shadow_data=shadow_data,
                                analysis_complexity=analysis_complexity
                            )
                            
                            teacher_notes = getattr(analysis_result, 'teacher_notes', 'No analysis available yet.')
                            st.session_state.final_diagnostic_notes = teacher_notes
                            print(f"DEBUG: AI Analysis complete. Teacher notes extracted: {bool(teacher_notes)}")
                            
                            st.success("Analysis complete! Review and confirm below.")
                            st.session_state.analysis_result = analysis_result # Store full object for later use
                            
                            # Extract G-scores and targets
                            g_scores = {
                                'g0': getattr(analysis_result, 'g0_phonemic_awareness', 0),
                                'g1': getattr(analysis_result, 'g1_cvc_mapping', 0),
                                'g2': getattr(analysis_result, 'g2_digraphs', 0),
                                'g3': getattr(analysis_result, 'g3_silent_e', 0),
                                'g4': getattr(analysis_result, 'g4_vowel_teams', 0),
                                'g5': getattr(analysis_result, 'g5_r_controlled', 0),
                                'g6': getattr(analysis_result, 'g6_clusters', 0),
                                'g7': getattr(analysis_result, 'g7_multisyllabic', 0),
                                'g8': getattr(analysis_result, 'g8_reduction_morphology', 0)
                            }
                            suggested_groups = getattr(analysis_result, 'suggested_next_groups', [])

                            st.session_state.g_scores_display = g_scores
                            st.session_state.targets_display = suggested_groups

                        except Exception as e:
                            st.error(f"Failed to run AI analysis: {e}. Please check your input and try again.")
                            st.session_state.final_diagnostic_notes = "AI analysis failed."
            
            # Step 7: Teacher Refinement
            st.subheader("Step 7: Teacher Refinement")
            st.caption("Review the AI's notes above. Verify and record your final diagnostic decision.")
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.text_area(
                    "Student's Spelling Attempts", 
                    value=st.session_state.get("student_attempts_for_report", ""),
                    height=400,
                    key=f"student_attempts_for_report_{student_id}"
                )
            
            with col2:
                final_notes_value = st.session_state.get('final_diagnostic_notes', '')
                final_notes = st.text_area(
                    "Final Diagnostic Notes (The 'Gold Standard')", 
                    value=final_notes_value if final_notes_value and final_notes_value not in ["No analysis available yet.", "AI analysis failed."] else "Type your own diagnostic notes here...", 
                    height=400,
                    key=f"final_diagnostic_notes_{student_id}"
                )
            
            # Save Button
            if st.button("Confirm & Save to Student History", key=f"save_assessment_{student_id}"):
                if not student_id:
                    st.error("Please select a student first.")
                elif not st.session_state.get("edited_transcription"):
                    st.error("Please complete the transcription first.")
                elif not st.session_state.get("analysis_result"):
                    st.error("Please run the AI analysis first.")
                else:
                    try:
                        analysis_result = st.session_state.analysis_result
                        g_scores_to_save = st.session_state.get("g_scores_display", {})
                        targets_to_save = st.session_state.get("targets_display", [])
                        
                        class SaveObject:
                            pass
                        save_obj = SaveObject()
                        save_obj.student_id = student_id
                        save_obj.real_name = student_name
                        # Use teacher's refined notes with appended target words for temporary storage
                        intended_words_for_saving = st.session_state.get("processed_intended_words")
                        if intended_words_for_saving:
                            if final_notes and final_notes.strip() not in ["No analysis available yet.", "AI analysis failed.", "Type your own diagnostic notes here..."]:
                                final_notes_with_target = f"{final_notes}\n\nIntended Test Words: {intended_words_for_saving}"
                            else:
                                final_notes_with_target = f"Intended Test Words: {intended_words_for_saving}"
                        else:
                            final_notes_with_target = final_notes

                        save_obj.teacher_notes = final_notes_with_target # Use teacher's refined notes with appended target words
            
                        # Populate g-scores from display, with fallback to 0
                        save_obj.g0_phonemic_awareness = g_scores_to_save.get("g0", 0)
                        save_obj.g1_cvc_mapping = g_scores_to_save.get("g1", 0)
                        save_obj.g2_digraphs = g_scores_to_save.get("g2", 0)
                        save_obj.g3_silent_e = g_scores_to_save.get("g3", 0)
                        save_obj.g4_vowel_teams = g_scores_to_save.get("g4", 0)
                        save_obj.g5_r_controlled = g_scores_to_save.get("g5", 0)
                        save_obj.g6_clusters = g_scores_to_save.get("g6", 0)
                        save_obj.g7_multisyllabic = g_scores_to_save.get("g7", 0)
                        save_obj.g8_reduction_morphology = g_scores_to_save.get("g8", 0)

                        save_obj.suggested_next_groups = targets_to_save
            
                        struggling_words = st.session_state.get("struggling_words_input", "")
                        teacher_observations = st.session_state.get("teacher_observations_input", "")
            
                        # Get test template info (need to ensure it's selected in the UI)
                        templates = get_all_test_templates()
                        template_options = {t['test_name']: t for t in templates}
                        selected_template_name = st.session_state.get("test_template_selector")
                        selected_template = template_options.get(selected_template_name)
                        test_template_id = selected_template.get('id') if selected_template else None

                        save_assessment(save_obj, st.session_state.edited_transcription, teacher_refinement=final_notes_with_target, # Pass the modified notes
                                    struggling_words=struggling_words, teacher_id=current_teacher_email,
                                    teacher_observations=teacher_observations, test_template=test_template_id)
                        
                        print(f"DEBUG: Final report using attempts from Step 3: {st.session_state.edited_transcription[:15]}...")
                        
                        st.success(f"Assessment for {student_name} has been saved!")
                        
                        # Store the ID of the used list for "smart memory"
                        if st.session_state.get('current_list_id'):
                            st.session_state.last_used_assessment_list_id = st.session_state.current_list_id
                        else:
                            st.session_state.last_used_assessment_list_id = None

                        # Clear assessment-specific state after saving
                        for key in [
                            'uploaded_file', 'raw_transcription', 'edited_transcription', 'analysis_result',
                            'student_attempts_for_report', 'final_diagnostic_notes', 'analysis_notes',
                            'g_scores_display', 'targets_display', 'raw_ai_result', classroom_data_key,
                            'intended_words_input', 'processed_intended_words', 'current_list_id',
                            f"new_list_name_{student_id}" # Clear new list name input
                        ]:
                            if key in st.session_state:
                                del st.session_state[key]
                        
                        for i in range(9):
                            if f'g{i}_score' in st.session_state:
                                del st.session_state[f'g{i}_score']

                        st.rerun()
                    except Exception as e:
                        st.error(f"Error saving assessment: {e}")
            
    # Remove this block as it's no longer needed in the main assessment workflow
    # teacher_id = st.session_state.get('user_name')  # Use user_name which contains the email
    # teacher_students_list = get_all_students_by_teacher(teacher_id)
    
    # if not teacher_students_list:
    #     st.info("No students assigned to you yet. Use 'Add New Assessment' to get started!")
    #     return

    # st.write(f"{len(teacher_students_list)} students in your class")
    
    # # Show student cards with AI coaching buttons
    # for student in teacher_students_list:
    #     with st.container():
    #         col1, col2 = st.columns([2, 1])
            
    #         current_student_name = student['name']

    #         with col1:
    #             st.markdown(f"**{current_student_name}**")
    #             st.caption(f"Alias: {student['pseudonym']} | Attempts: {student['total_attempts']}")
            
    #         with col2:
    #             g_val = student.get('current_g_level', 'N/A')
    #             st.metric("Current G-Level", g_val.split(',')[0] if g_val else "N/A")

    #         # AI Coaching button for each student
    #         if st.button(f"Generate AI Coach Report for {current_student_name}", key=f"ai_{current_student_name}"):
    #             with st.spinner(f"Consulting AI about {student['pseudonym']}..."):
    #                 try:
    #                     # Get full history as list for holistic AI analysis
    #                     history = get_student_history(student['student_id'], teacher_id=teacher_id, admin=False)
    #                     from spelling_logic import get_ai_coaching_report
    #                     raw_report = get_ai_coaching_report(
    #                         student_alias=student['pseudonym'], 
    #                         g_level=student.get('current_g_level', 'N/A'), 
    #                         history=history
    #                     )
    #                     # Store raw report in session state for editing
    #                     st.session_state[f'raw_report_{current_student_name}'] = raw_report
    #                     st.session_state[f'edit_mode_{current_student_name}'] = True
    #                     st.rerun()
    #                 except Exception as e:
    #                     st.error(f"Failed to generate AI coach report: {str(e)}")
    #                     st.info("Please try again later or contact support if the issue persists.")
            
    #         # Display editable report if in edit mode
    #         edit_key = f'edit_mode_{current_student_name}'
    #         if st.session_state.get(edit_key, False):
    #             raw_report = st.session_state.get(f'raw_report_{current_student_name}', '')
                
    #             st.markdown("---*")
    #             st.subheader(f"AI Coaching Report for {current_student_name}")
    #             st.caption("Review and edit the AI's suggestions before saving.")
                
    #             # Editable text area for the report
    #             edited_report = st.text_area(
    #                 "Coach Report (editable)",
    #                 value=raw_report,
    #                 height=300,
    #                 key=f'report_editor_{current_student_name}'
    #             )
                
    #             # Confirm and Save Report button
    #             col_save1, col_save2 = st.columns([1, 4])
    #             with col_save1:
    #                 if st.button("Confirm & Save Report", key=f'save_report_{current_student_name}', type="primary"):
    #                     if edited_report.strip():
    #                         # Save the edited report as part of the assessment
    #                         from database_manager import save_ai_report
    #                         save_ai_report(
    #                             student_id=student['student_id'],
    #                             teacher_id=teacher_id,
    #                             report_content=edited_report
    #                         )
    #                         st.success(f"Report saved for {current_student_name}!")
    #                         st.session_state[edit_key] = False
    #                         st.rerun()
    #                     else:
    #                         st.warning("Report cannot be empty.")
    #             with col_save2:
    #                 if st.button("Discard", key=f'discard_report_{current_student_name}'):
    #                     st.session_state[edit_key] = False
    #                     st.rerun()
    #             st.markdown("---*")
        
    #     st.divider()


# =============================================================================
# COMPONENT: ADMIN PAGE (Factory Reset & Student Allocation)
# =============================================================================
def display_admin_page():
    """Display the Admin dashboard with factory reset and student allocation tools."""
    ADMIN_EMAIL = "komododundee@gmail.com"
    
    if st.session_state.get('user_email', '').lower().strip() != ADMIN_EMAIL.lower().strip():
        st.error(" Admin access required.")
        return
    
    st.header("Admin Dashboard")
    
    # CSV Status & Force Import
    with st.expander(" CSV Data Management"):
        st.subheader(" CSV File Status")
        
        students_csv_exists = os.path.exists("students.csv")
        assessments_csv_exists = os.path.exists("assessments.csv")
        
        col_status1, col_status2 = st.columns(2)
        with col_status1:
            if students_csv_exists:
                st.success(" students.csv: FOUND")
                try:
                    with open("students.csv", 'r') as f:
                        line_count = sum(1 for _ in f) - 1
                    st.caption(f"   → {line_count} student records")
                except:
                    pass
            else:
                st.error(" students.csv: MISSING")
        
        with col_status2:
            if assessments_csv_exists:
                st.success(" assessments.csv: FOUND")
                try:
                    with open("assessments.csv", 'r') as f:
                        line_count = sum(1 for _ in f) - 1
                    st.caption(f"   → {line_count} assessment records")
                except:
                    pass
            else:
                st.error(" assessments.csv: MISSING")
        
        st.markdown("---")
        st.subheader(" Force Import from CSV")
        st.warning(" This will import ALL data from CSV files as orphaned (teacher_id = NULL)")
        
        if st.button(" FORCE IMPORT FROM CSV", type="primary", width="stretch"):
            with st.spinner("Importing data..."):
                result = import_from_csv()
                sync_result = sync_identity_from_assessments()
                st.success(f" Import Complete!")
                st.write(f"   • Students imported: {result['students']}")
                st.write(f"   • Assessments imported: {result['assessments']}")
                st.write(f"   • Identity records synced: {sync_result['created']}")
                if result['students'] > 0 or result['assessments'] > 0:
                    st.info(" Imported records are marked as ORPHANED.")
                else:
                    st.info("No new records were imported.")
            st.rerun()
    
    st.markdown("---")
    
    # Database Maintenance
    with st.expander(" Database Maintenance"):
        st.subheader(" Maintenance Tools")
        
        stats = get_database_stats()
        col_s1, col_s2 = st.columns(2)
        with col_s1:
            st.metric("Total Assessments", stats.get('total_assessments', 0))
            st.metric("Total Students", stats.get('total_students', 0))
        with col_s2:
            st.metric("Orphaned Students", stats.get('orphaned_students', 0))
            st.metric("Orphaned Assessments", stats.get('orphaned_assessments', 0))
        
        st.markdown("---")
        
        col_fix1, col_fix2 = st.columns([2, 1])
        with col_fix1:
            st.write("**Fix Teacher ID Consistency**")
            st.caption("Updates ALL assessment rows to match student_identity table")
        with col_fix2:
            if st.button(" Fix All Teacher IDs", width="stretch"):
                result = fix_all_teacher_ids()
                st.success(f" Fixed! Synced {result['students_synced']} students.")
                st.rerun()
    
    st.markdown("---")
    
    # Identity Manager
    with st.expander(" Identity Manager"):
        st.subheader(" Student Identity Management")
        
        # Get all unique student IDs from database
        from database_manager import get_all_student_ids
        all_student_ids = get_all_student_ids()
        
        if all_student_ids:
            st.write(f"**Found {len(all_student_ids)} unique student IDs:**")
            
            # Create manual mapping interface
            selected_code = st.selectbox("Select student code to map:", all_student_ids, key="identity_code_select")
            
            col_name, col_save = st.columns([2, 1])
            
            with col_name:
                student_name = st.text_input("Enter student's real name:", key="student_name_input", placeholder="e.g., John Smith")
            
            with col_save:
                if st.button("Save Mapping", type="primary", use_container_width=True):
                    if student_name.strip():
                        # Save to student_identity table
                        from database_manager import save_student_identity
                        save_student_identity(st.session_state.get('user_email'), selected_code, student_name.strip(), None)
                        st.success(f"Saved: {selected_code} → {student_name.strip()}")
                        st.rerun()
                    else:
                        st.error("Please enter a student name.")
            
            # Show current mappings
            st.markdown("**Current Identity Mappings:**")
            from database_manager import get_all_student_identities
            identities = get_all_student_identities()
            
            if identities:
                for identity in identities:
                    st.write(f"• **{identity['student_id']}** → {identity['real_name']}")
            else:
                st.info("No identity mappings found yet.")
        else:
            st.info("No student IDs found in database.")
    
    st.markdown("---")
    
    # FACTORY RESET
    with st.expander(" FACTORY RESET (Big Red Button)", expanded=False):
        st.error(" This will DELETE ALL assessments and student records. Teacher accounts will be PRESERVED.")
        
        if "confirm_factory_reset" not in st.session_state:
            st.session_state.confirm_factory_reset = False
        
        if not st.session_state.confirm_factory_reset:
            if st.button(" FACTORY RESET", type="primary", width="stretch"):
                st.session_state.confirm_factory_reset = True
                st.rerun()
        else:
            st.warning(" Are you absolutely sure? This cannot be undone!")
            col_reset1, col_reset2 = st.columns(2)
            with col_reset1:
                if st.button(" YES, RESET EVERYTHING", type="primary", width="stretch"):
                    result = clear_all_data()
                    st.success(f" Factory Reset Complete!")
                    st.write(f"   • Assessments deleted: {result['assessments_deleted']}")
                    st.write(f"   • Student identities deleted: {result['identity_deleted']}")
                    st.write(f"   • Teacher accounts: PRESERVED")
                    st.session_state.confirm_factory_reset = False
                    st.rerun()
            with col_reset2:
                if st.button(" Cancel", width="stretch"):
                    st.session_state.confirm_factory_reset = False
                    st.rerun()
    
    st.markdown("---")
    
    # Student Allocation
    with st.expander(" Manage Student Allocations", expanded=False):
        st.subheader("Assign Students to Teachers")
        st.caption("Reassign students to different teachers.")
        
        all_students = get_all_students_for_allocation()
        all_teachers_list = get_all_teachers()
        
        if not all_students:
            st.info("No students found in database.")
        else:
            st.write(f"{len(all_students)} students total")
            st.markdown("---")
            
            for i, student in enumerate(all_students):
                with st.container():
                    col_name, col_teacher, col_btn = st.columns([2, 2, 1])
                    
                    with col_name:
                        st.markdown(f"**{student['name']}**")
                        st.caption(f"ID: {student['student_id'][:16]}... | Alias: {student['pseudonym']}")
                    
                    with col_teacher:
                        # Build dropdown with "Name (email)" format
                        teacher_display_options = ["Unassigned"]
                        teacher_emails = [None]  # None for Unassigned
                        
                        for t in all_teachers_list:
                            teacher_display_options.append(f"{t['name']} ({t['email']})")
                            teacher_emails.append(t['email'])
                        
                        # Find current selection index
                        current_idx = 0
                        if student['current_teacher'] and student['current_teacher'] != "Unassigned":
                            try:
                                current_idx = teacher_emails.index(student['current_teacher'])
                            except ValueError:
                                current_idx = 0
                        
                        selected_display = st.selectbox(
                            f"Assign {student['name']} to:",
                            options=teacher_display_options,
                            index=current_idx,
                            key=f"teacher_select_{i}_{student['student_id']}",
                            label_visibility="collapsed"
                        )
                    
                    with col_btn:
                        if st.button("Update", key=f"update_btn_{i}_{student['student_id']}", width="stretch"):
                            # Extract email from selection
                            if selected_display == "Unassigned":
                                new_teacher = None
                            else:
                                new_teacher = selected_display.split('(')[-1].replace(')', '')
                            
                            result = update_student_teacher(student['student_id'], new_teacher)
                            if result['assessments_updated'] > 0:
                                st.success(f"Updated!")
                            else:
                                st.info(f"No changes needed.")
                            st.rerun()
    
    st.markdown("---")
    
    # Test Templates Management
    with st.expander(" Manage Assessment Templates", expanded=False):
        st.subheader("Assessment Library")
        st.caption("Create and manage diagnostic assessment templates.")
        
        from database_manager import get_all_test_templates, save_test_template, delete_test_template
        
        # Form to add/edit test template
        with st.form("test_template_form", clear_on_submit=True):
            col1, col2 = st.columns([1, 3])
            with col1:
                test_id_input = st.text_input("Test ID", placeholder="e.g., g2_digraphs_v1", help="Unique identifier for this test")
            with col2:
                test_name_input = st.text_input("Test Name", placeholder="e.g., G2 Digraphs Assessment")
            
            intended_words_input = st.text_area(
                "Intended Words (comma-separated)",
                height=100,
                placeholder="e.g., ship, shed, fish, dish, rush, mash, wish, cash, flash"
            )
            
            col_btn1, col_btn2 = st.columns([1, 4])
            with col_btn1:
                submitted = st.form_submit_button("Save Template", type="primary")
            
            if submitted:
                if test_name_input and intended_words_input:
                    save_test_template(test_name_input.strip(), intended_words_input.strip())
                    st.success(f"Saved template: {test_name_input}")
                    st.rerun()
                else:
                    st.error("Please fill in Test Name and Intended Words.")
        
        st.markdown("---")
        st.subheader("Available Templates")
        
        templates = get_all_test_templates()
        if templates:
            for i, t in enumerate(templates):
                with st.container():
                    col1, col2, col3 = st.columns([3, 3, 1])
                    with col1:
                        st.markdown(f"**{t['test_name']}**")
                        st.caption(f"ID: {t.get('id', 'N/A')} | {len(t['intended_words'].split(','))} words")
                    with col2:
                        words_preview = ', '.join(t['intended_words'].split(',')[:5])
                        if len(t['intended_words'].split(',')) > 5:
                            words_preview += '...'
                        st.caption(words_preview)
                    with col3:
                        if t.get('id') != 1:  # Don't allow deleting the first/default template
                            if st.button("Delete", key=f"del_template_{t.get('id', i)}"):
                                success = delete_test_template(t.get('id'))
                                if success:
                                    st.success("Template deleted")
                                else:
                                    st.error("Failed to delete template")
                                st.rerun()
                        else:
                            st.caption("Default")
        else:
            st.info("No test templates found.")
    
    st.markdown("---")
    
    # School-Wide Research Dashboard
    st.subheader("School-Wide Research Dashboard")
    
    sync_result = sync_identity_from_assessments()
    
    stats = get_database_stats()
    col_s1, col_s2, col_s3 = st.columns(3)
    col_s1.metric("Total Assessments", stats.get('total_assessments', 0))
    col_s2.metric("Unique Students", stats.get('unique_students_in_assessments', 0))
    col_s3.metric("Teachers", stats.get('total_teachers', 0))
    
    st.markdown("---")
    
    # Complete Student Table
    st.subheader("All Students in Database")
    
    all_students = get_all_students_with_status()
    
    if not all_students:
        st.info("No students found. Import legacy CSV data or save new assessments.")
    else:
        from database_manager import get_teacher_name
        
        table_data = []
        for s in all_students:
            teacher_display = s["teacher"]
            if s["teacher"] and s["teacher"] != "Unassigned":
                # Show teacher's name instead of email
                teacher_display = get_teacher_name(s["teacher"])
            
            table_data.append({
                "Name": s["name"],
                "Last Assessment": s["last_date"][:10] if s["last_date"] else "Never",
                "Total Attempts": s["total_attempts"],
                "Teacher": teacher_display,
            })
        
        table_df = pd.DataFrame(table_data)
        st.dataframe(table_df, width="stretch", hide_index=True)
        st.caption(f"Showing {len(all_students)} students")
        
        # Quick Assign Section
        st.markdown("### Quick Assign Students")
        orphans = [s for s in all_students if s["teacher"] == "Unassigned"]
        
        if orphans:
            st.warning(f"{len(orphans)} students need assignment")
            
            all_teachers_for_assign = get_all_teachers()
            if all_teachers_for_assign:
                # Show teacher names in dropdown
                teacher_options = [f"{t['name']} ({t['email']})" for t in all_teachers_for_assign]
                teacher_display_options = [f"{t['name']} ({t['email']})" for t in teacher_options]
                
                col_bulk, col_btn = st.columns([3, 1])
                with col_bulk:
                    selected_display = st.selectbox("Assign unassigned students to:", options=["Select..."] + teacher_display_options, key="bulk_admin_assign")
                with col_btn:
                    st.write("")
                    if selected_display != "Select..." and st.button("Assign All", type="primary", width="stretch"):
                        # Extract email from selection
                        selected_email = selected_display.split('(')[-1].replace(')', '')
                        orphan_ids = [s["student_id"] for s in orphans]
                        result = bulk_assign_students(orphan_ids, selected_email)
                        st.success(f"Assigned {result['students_assigned']} students to {selected_display}")
                        st.rerun()
        else:
            st.success("All students are assigned to a teacher.")

# =============================================================================
# RUN THE APP
# =============================================================================
if __name__ == "__main__":
    main()
