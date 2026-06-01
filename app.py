import json
import os
os.environ["OTEL_SDK_DISABLED"] = "true"
import pandas as pd
import streamlit as st
import random
import csv
import time
import base64
import database_manager as db
from datetime import datetime

from utils import preprocess_image
from spelling_logic import get_ai_discrepancy_feedback, transcribe_handwriting, run_scoring_crew, generate_personalized_practice_words
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
    save_draft_assessment, get_draft_assessments, delete_draft_assessment, get_sheet_data,
    save_named_list, get_named_lists, get_named_list_by_id, init_correction_tables,
    get_historical_corrections, delete_specific_correction, get_student_current_group_focus, log_ai_discrepancy, update_student_current_group_focus,
)
import constants

# Initialize correction tables on boot
init_correction_tables()

from database_manager import delete_assessment # Import the new delete function
from ai_learning_engine import ingest_teacher_calibration # Import the AI learning engine

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
        ("student_attempts_for_report", ""), ("classroom_data", None), ("selected_student", None), ("is_admin", False), ("logged_in", False), ("user_email", None),
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
                    f'shadow_data_{st.session_state.get("current_student_id")}', # Clear previous student's classroom data
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
    student_name = get_name_for_id(current_teacher_email, student_id) or f"Student {student_id}" # Use get_name_for_id for consistency
    
    # Display student name as large header
    st.title(student_name)
    
    # Fetch current group focus from student_identity
    current_student_group_focus = get_student_current_group_focus(student_id)
    
    # Group Focus Selector at the top
    def on_group_focus_change():
        update_student_current_group_focus(student_id, st.session_state[f"group_focus_selector_{student_id}"])
        st.rerun()

    group_keys = list(constants.DIAGNOSTIC_GROUPS.keys())
    default_group_index = group_keys.index(current_student_group_focus) if current_student_group_focus in group_keys else 0

    st.subheader("Current Group Focus")
    
    st.selectbox(
        label="Select Focus Group", # Standard clean label since the subheader sits above it now
        label_visibility="collapsed", # Hides the small duplicate label so the subheader does the talking
        options=group_keys,
        index=default_group_index,
        format_func=lambda k: f"{k.upper()}: {constants.DIAGNOSTIC_GROUPS[k]['name']}",
        key=f"group_focus_selector_{student_id}",
        on_change=on_group_focus_change
    )   


    # Fetch latest assessment data from database
    from database_manager import get_student_history
    history = get_student_history(student_id, teacher_id=current_teacher_email, admin=False)
    
    # For practice list generation, always use the dynamically selected current_student_group_focus
    target_group = current_student_group_focus
    
    # Get the most recent assessment data for struggles/mastered (if needed for display/context)
    struggles = []
    mastered = []
    if history:
        latest = history[-1]  # Most recent assessment
        if latest.get('struggling_words'):
            struggles = latest.get('struggling_words', '').split(',') if latest.get('struggling_words') else []
        # 'mastered' is not directly saved in history, so we'll rely on generating from raw_text or external state if needed.

    # Use student-specific key for classroom data
    classroom_data_key = f"shadow_data_{student_id}"

    # Fetch teacher settings to get the Google Sheet URL
    current_settings = get_teacher_settings(current_teacher_email)
    sheet_url = current_settings.get('google_sheet_url', '')

    # Fetch classroom data if URL is configured and data is not already in session state
    if sheet_url and not st.session_state.get(classroom_data_key):
        with st.spinner("Fetching classroom observation data..."): # Add a spinner for UX
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
    
    st.markdown("---")
    
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

    # Diagnostic Assessment History Section
    st.subheader("Diagnostic Assessment History")
    
    # Reuse the 'history' fetched at the top of display_student_detail_view
    if history:
        # Display assessments in reverse chronological order (most recent first)
        for assessment in reversed(history):
            # Attempt to get the list name from teacher_refinement first
            test_name = "Ad-hoc Assessment" # Default fallback
            if assessment.get('teacher_refined_notes'): # Use correct key
                refinement_notes = assessment['teacher_refined_notes'] # Use correct key
                # Check for the prepended "Word List:"
                if refinement_notes.startswith("Word List:"):
                    first_line = refinement_notes.split('\n')[0]
                    test_name = first_line.replace("Word List: ", "").strip()
                elif assessment.get('test_template'): # Fallback to test_template_id if present (column is 'test_template')
                    template_data = get_test_template(assessment['test_template'])
                    if template_data:
                        test_name = template_data.get('test_name', 'Unnamed Test')
                # Removed 'intended_words' fallback as it's not fetched and is embedded in teacher_refined_notes

            created_at = assessment.get('created_at', 'N/A')
            date_only = created_at.split(' ')[0] if created_at and ' ' in created_at else created_at
            suggested_group = assessment.get('suggested_next', 'N/A').upper()
            
            expander_title = f"**{test_name}** – {date_only} (Suggested: {suggested_group})"

            with st.expander(expander_title, expanded=False):
                st.subheader("Student Responses")
                if assessment.get('raw_transcription'): # Use correct key
                    st.code(assessment['raw_transcription'], language='text') # Use correct key
                else:
                    st.info("No student responses recorded for this assessment.")

                st.subheader("Teacher Notes")
                if assessment.get('teacher_refined_notes'): # Use correct key
                    # Display the full notes, including the prepended list name
                    st.markdown(assessment['teacher_refined_notes']) # Use correct key
                else:
                    st.info("No teacher notes recorded for this assessment.")
                
                # Removed redundant check for 'intended_words' as it's part of teacher_refined_notes

                # Optional: Display G-level scores if available
                g_score_keys = [
                    'g0_phonemic', 'g1_cvc', 'g2_digraphs', 'g3_silent_e', # Update keys to match DB columns
                    'g4_vowel_teams', 'g5_r_controlled', 'g6_clusters', 'g7_multisyllabic',
                    'g8_reduction' # Update keys to match DB columns
                ]
                g_scores_found = {k: assessment.get(k) for k in g_score_keys if assessment.get(k) is not None}
                if g_scores_found:
                    st.subheader("G-Level Scores")
                    for k, v in g_scores_found.items():
                        # Format key for display: e.g., 'g0_phonemic' -> 'G0'
                        display_key = k.split('_')[0].upper()
                        st.write(f"- {display_key}: {v}")
                
                # Delete Assessment Button with confirmation
                col_del_btn, _ = st.columns([1, 4])
                with col_del_btn:
                    with st.popover("Delete this assessment?", use_container_width=True):
                        st.write("Are you sure you want to delete this assessment? This action cannot be undone.")
                        if st.button("Confirm Delete", type="primary", key=f"confirm_delete_assessment_{assessment['id']}"):
                            if delete_assessment(assessment['id']):
                                st.success("Assessment deleted successfully!")
                                st.rerun()
                            else:
                                st.error("Failed to delete assessment.")

    else:
        st.info("No diagnostic assessments recorded yet for this student.")

    st.markdown("---")

    # Display classroom data if available for this student (moved to be before Add New Assessment)
    # Ensure the key is consistently defined as f"shadow_data_{student_id}"
    if st.session_state.get(classroom_data_key):
        st.subheader("Classroom Data")
        st.write(f"**Found {len(st.session_state[classroom_data_key])} recent observations.**")
    else:
        st.info("No classroom observation data recorded yet. Ensure Google Sheet URL is configured in settings.")
    
    st.divider()

    # Add New Assessment section with Step 1-5 workflow
    st.subheader("Add New Assessment")
    # The actual workflow is now split, with Step 1-6 above, and Step 7 below,
    # to ensure Step 7 elements are always visible.
    
    # Logic to prepare the visual review content (moved out of if uploaded_file block)
    intended_words_raw = st.session_state.get("processed_intended_words", "")
    student_attempts_raw = st.session_state.get('student_attempts_for_report', "")
    
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
                            
                            st.session_state[f'edited_transcription_{student_id}'] = cleaned_text
                            st.session_state['raw_transcription'] = cleaned_text # Keep raw for potential debugging/diffing if needed
                            st.session_state['processing'] = False
                            print(f"DEBUG: Saved to state: {st.session_state[f'edited_transcription_{student_id}'][:20]}...")
                        else:
                            st.error("AI returned empty string for transcription.")
                            st.session_state['processing'] = False
                    except Exception as e:
                        st.error(f"Failed to transcribe handwriting: {e}")
                        st.session_state['processing'] = False
        
        with col_text:
            st.subheader("Step 4: Verify & Edit Transcription")
            
            if not st.session_state.get(transcription_key):
                st.info("Waiting for handwriting analysis...")
            
            edited_text = st.text_area(
                "Verify & Edit Transcription", 
                value=st.session_state.get(transcription_key, ""),
                height=200,
                key=transcription_key
            )

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
                # Capture latest state
                st.session_state['student_attempts_for_report'] = st.session_state.get(f"edited_transcription_{student_id}", "")
                
                with st.spinner('AI Crew is analyzing spelling patterns...'):
                        try:
                            # Use intended words from session state, or fall back to default if not provided
                            intended_words_for_analysis = st.session_state.get("processed_intended_words")
                            if not intended_words_for_analysis:
                                # Fallback if target words were not provided in step 1
                                intended_words_for_analysis = "fan, pet, dig, rob, hope, wait, gum, sled, stick, shine" 
                            
                            shadow_data = st.session_state.get(classroom_data_key, [])

                            print(f"DEBUG: Sending attempts to AI Crew...")

                            analysis_result = run_scoring_crew(
                                student_id,
                                st.session_state['student_attempts_for_report'],
                                intended_words=intended_words_for_analysis,
                                shadow_data=shadow_data,
                                analysis_complexity=analysis_complexity
                            )
                            
                            teacher_notes = getattr(analysis_result, 'teacher_notes', 'No analysis available yet.')
                            st.session_state.final_diagnostic_notes = teacher_notes
                            print(f"DEBUG: AI Analysis complete. Teacher notes extracted: {bool(teacher_notes)}")
                            
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
                            
                            st.success("Analysis complete! Review and confirm below.")
                            st.rerun()

                        except Exception as e:
                            st.error(f"Failed to run AI analysis: {e}. Please check your input and try again.")
                            st.session_state.final_diagnostic_notes = "AI analysis failed."
    
    
    display_assessment_workflow(student_id, student_name)

    # Insert Step 7 content here, at the same indentation level as the rest of the workflow steps
    st.subheader("Step 7: Teacher Refinement")
    st.caption("Review the AI's notes and spelling analysis. Verify and record your final diagnostic decision.")

    highlighted_content = ""
    min_len = 0 # Initialized safely outside the if block

    # Logic for preparing visual review content - this block should render conditionally
    if st.session_state.get("processed_intended_words") and st.session_state.get('student_attempts_for_report'):
        intended_words_raw = st.session_state.get("processed_intended_words", "")
        student_attempts_raw = st.session_state.get('student_attempts_for_report', "")
            
        intended_list = [w.strip().lower() for w in intended_words_raw.replace('\n', ',').split(',') if w.strip()]
        attempts_raw = [a.strip().lower() for a in student_attempts_raw.replace('\n', ',').split(',') if a.strip()]
            
        min_len = min(len(intended_list), len(attempts_raw))
            
        for i in range(min_len):
            try:
                if attempts_raw[i] == intended_list[i]:
                    highlighted_content += f"{i+1}. {attempts_raw[i]}  \n"
                else:
                    highlighted_content += f"{i+1}. <span style='color:#d9534f; font-weight:bold;'>{attempts_raw[i]}</span>  \n"
            except Exception as e:
                print(f"DEBUG: Error matching index {i}: {e}")
                highlighted_content += f"{i+1}. {attempts_raw[i]} (error)  \n"
    else:
        highlighted_content = "No attempt data available."

    # These columns and their content (including selectbox) now render unconditionally
    col1, col2 = st.columns(2)
    with col1:
                st.markdown("**Student's Spelling Attempts**")
                st.markdown(
                    f"""<div style="background-color: #1e1e1e; padding: 15px; border-radius: 8px; border: 1px solid #333333; color: #f0f2f6; font-family: monospace; line-height: 1.6;">
                    {highlighted_content}
                    </div>""",
                    unsafe_allow_html=True
    )

    with col2:
                group_keys = list(constants.DIAGNOSTIC_GROUPS.keys())
                ai_suggested_list = st.session_state.get('targets_display', [])
                ai_suggested = ai_suggested_list[0] if ai_suggested_list else 'g1'
                if ai_suggested not in group_keys: ai_suggested = 'g1'

                if "teacher_refined_group" not in st.session_state:
                    st.session_state.teacher_refined_group = ai_suggested

                st.selectbox(
                    "Suggested Group Focus (Adjust if needed):",
                    options=group_keys,
                    index=group_keys.index(st.session_state.teacher_refined_group),
                    format_func=lambda k: f"{k.upper()}: {constants.DIAGNOSTIC_GROUPS[k]['name']}",
                    key="teacher_refined_group"
                )

    # These fields and button are now outside of the conditional column display and render unconditionally
    st.text_area(
        "Final Diagnostic Notes (The 'Gold Standard')",
        value=st.session_state.get('final_diagnostic_notes', ''),
        height=330,
        key="final_diagnostic_notes"
    )

    teacher_logic_feedback = st.text_area(
        "Feedback on AI Logic / Blind Spots",
        placeholder="e.g., The AI missed short vowel struggles in CVC words...",
        key=f"logic_feedback_{student_id}"
    )

    if st.button("Confirm & Save to Student History", key=f"save_btn_{student_id}"):
                # Capture finalized inputs
                student_attempts_raw = st.session_state.get('student_attempts_for_report', "")
                final_group = st.session_state.get("teacher_refined_group", 'g1') # Use direct access or 'g1' fallback
                teacher_feedback = st.session_state.get(f"logic_feedback_{student_id}", "")

                assessment_name = st.session_state.get(f"select_word_list_{student_id}", "Unspecified Assessment List")

                # Prepare assessment_data as a dictionary, then convert to an object for save_assessment
                assessment_data_dict = {
                    "student_id": student_id,
                    "teacher_id": current_teacher_email, # Now sourced from the data object in db.save_assessment
                    "raw_transcription": student_attempts_raw,
                    "teacher_refined_notes": st.session_state.get("final_diagnostic_notes", ""), # Now sourced from the data object
                    "suggested_next": final_group, # This will be the teacher_assigned_group
                    "test_name": assessment_name, # Now sourced from the data object (as test_template)
                    "g0_phonemic_awareness": getattr(st.session_state.get('analysis_result'), 'g0_phonemic_awareness', 0),
                    "g1_cvc_mapping": getattr(st.session_state.get('analysis_result'), 'g1_cvc_mapping', 0),
                    "g2_digraphs": getattr(st.session_state.get('analysis_result'), 'g2_digraphs', 0),
                    "g3_silent_e": getattr(st.session_state.get('analysis_result'), 'g3_silent_e', 0),
                    "g4_vowel_teams": getattr(st.session_state.get('analysis_result'), 'g4_vowel_teams', 0),
                    "g5_r_controlled": getattr(st.session_state.get('analysis_result'), 'g5_r_controlled', 0),
                    "g6_clusters": getattr(st.session_state.get('analysis_result'), 'g6_clusters', 0),
                    "g7_multisyllabic": getattr(st.session_state.get('analysis_result'), 'g7_multisyllabic', 0),
                    "g8_reduction_morphology": getattr(st.session_state.get('analysis_result'), 'g8_reduction_morphology', 0),
                    "teacher_notes": getattr(st.session_state.get('analysis_result'), 'teacher_notes', ''),
                    "struggling_words": getattr(st.session_state.get('analysis_result'), 'struggling_words', ''), # Now sourced from the data object
                }

                # Create a dummy object to mimic the `data` parameter in save_assessment
                class AssessmentDataObject:
                    def __init__(self, d):
                        self.__dict__ = d
                
                assessment_data_obj = AssessmentDataObject(assessment_data_dict)

                # Simplified call to db.save_assessment as requested
                if db.save_assessment(assessment_data_obj, raw_text=student_attempts_raw):

                    # Safely capture the original AI notes and the teacher's updated notes
                    original_notes = getattr(st.session_state.get('analysis_result'), 'teacher_notes', '')
                    refined_notes = st.session_state.get("final_diagnostic_notes", "")

                    ai_suggested_list_for_calibration = st.session_state.get('targets_display', [])
                    ai_suggested_group_for_calibration = ai_suggested_list_for_calibration[0] if ai_suggested_list_for_calibration else 'Unassigned' # Default for AI group

                    ingest_teacher_calibration(
                        student_id=student_id,
                        assessment_id=None, # assessment_id will be None for now as it's not directly returned by save_assessment
                        ai_suggested_group=ai_suggested_group_for_calibration,
                        teacher_assigned_group=final_group,
                        teacher_feedback=teacher_feedback,
                        original_notes=original_notes,
                        refined_notes=refined_notes
                    )

                    st.success("Assessment saved successfully!")

                    # Clean up session state
                    for key in [f"edited_transcription_{student_id}", "final_diagnostic_notes", f"logic_feedback_{student_id}", "analysis_result", "g_scores_display", "targets_display", "processed_intended_words"]: # Clear more relevant keys
                        if key in st.session_state:
                            del st.session_state[key]
                    
                    # Also clear teacher_refined_group so it resets for next assessment
                    if "teacher_refined_group" in st.session_state:
                        del st.session_state["teacher_refined_group"]

                    st.rerun()

def display_assessment_workflow(student_id, student_name):
    """Display the complete Step 1-5 assessment workflow."""
    # 1. DYNAMIC SYNCHRONIZATION: Safety bridge to ensure handwriting flow
    transcription_key = f"edited_transcription_{student_id}" # Define transcription_key
    if st.session_state.get(transcription_key):
        st.session_state['student_attempts_for_report'] = st.session_state[transcription_key]
    
    # Safety initialization
    if 'student_attempts_for_report' not in st.session_state:
        st.session_state['student_attempts_for_report'] = ""

    current_teacher_email = st.session_state.get('user_email')
    current_settings = get_teacher_settings(current_teacher_email)
    sheet_url = current_settings.get('google_sheet_url', '')

    # Use student-specific key for classroom data
    classroom_data_key = f"shadow_data_{student_id}"
    
    # Step 1: Define Assessment Target Words
    with st.expander("1. Define Assessment Target Words", expanded=True):
        current_teacher_email = st.session_state.get('user_email')
        
        # UI for selecting or creating a word list
        st.session_state.current_word_list_mode = st.radio(
            "Choose a word list method:",
            options=["Select Existing List", "Create New List"],
            key=f"word_list_mode_{student_id}",
            index=0,
            horizontal=True
        )

        selected_list_name_display = None # To display selected list name

        if st.session_state.current_word_list_mode == "Select Existing List":
            named_lists = get_named_lists(current_teacher_email)
            
            list_options = {"Select a saved list...": None}
            for lst in named_lists:
                list_options[lst['list_name']] = lst['id']
            
            # Smart memory: default to last used list if available and in options
            default_index = 0
            if st.session_state.get("last_used_assessment_list_id"):
                last_used_list = get_named_list_by_id(st.session_state.last_used_assessment_list_id)
                if last_used_list and last_used_list['list_name'] in list_options:
                    default_index = list(list_options.keys()).index(last_used_list['list_name'])
            
        # Force a refresh of the named lists to ensure the dropdown renders
        named_lists = get_named_lists(current_teacher_email)
        list_options = {"Select a saved list...": None}
        for lst in named_lists:
            list_options[lst['list_name']] = lst['id']

        # Ensure default index is valid for the current list_options keys
        default_index = 0
        keys_list = list(list_options.keys())
        if st.session_state.get("last_used_assessment_list_id"):
            last_used_list = get_named_list_by_id(st.session_state.last_used_assessment_list_id)
            if last_used_list and last_used_list['list_name'] in list_options:
                default_index = keys_list.index(last_used_list['list_name'])

        selected_list_name = st.selectbox(
            "Select an existing word list:",
            options=keys_list,
                format_func=lambda x: x,
                key=f"select_word_list_{student_id}",
                index=default_index
            )
            
        if selected_list_name != "Select a saved list..." and selected_list_name in list_options:
            list_id = list_options[selected_list_name]
            list_data = get_named_list_by_id(list_id)
            if list_data:
                st.session_state.intended_words_input = list_data['target_words']
                st.session_state.current_list_id = list_data['id']
                st.session_state.last_used_assessment_list_id = list_data['id']
                st.info(f"Selected list: **{selected_list_name}** (ID: {list_data['id']})")
            else:
                st.session_state.intended_words_input = ""
                st.session_state.current_list_id = None
                st.info("No list selected. Please create one or select from above.")

        else: # Create New List
            new_list_name = st.text_input(
                "Name for this new word list (e.g., 'Weekly Spelling 1'):",
                key=f"new_list_name_{student_id}"
            )
            st.session_state.intended_words_input = st.text_area(
                "Enter the intended words (comma-separated or one per line):",
            value=st.session_state.get("intended_words_input", ""),
                height=150,
                key=f"intended_words_input_{student_id}",
                placeholder="e.g., cat, dog, run, jump\nor\ncat\ndog\nrun\njump"
            )
            if st.button("Save New List", key=f"save_new_list_btn_{student_id}"):
                if new_list_name and st.session_state.intended_words_input:
                    success = save_named_list(
                        current_teacher_email,
                        new_list_name.strip(),
                        st.session_state.intended_words_input.strip()
                    )
                    if success:
                        st.success(f"Word list '{new_list_name}' saved!")
                        st.session_state.current_word_list_mode = "Select Existing List"
                        named_lists_after_save = get_named_lists(current_teacher_email)
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
    
    # Data fetching for classroom data is now handled in display_student_detail_view
    
    
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
                            
                            st.session_state[f'edited_transcription_{student_id}'] = cleaned_text
                            st.session_state['raw_transcription'] = cleaned_text # Keep raw for potential debugging/diffing if needed
                            st.session_state['processing'] = False
                            print(f"DEBUG: Saved to state: {st.session_state[f'edited_transcription_{student_id}'][:20]}...")
                        else:
                            st.error("AI returned empty string for transcription.")
                            st.session_state['processing'] = False
                    except Exception as e:
                        st.error(f"Failed to transcribe handwriting: {e}")
                        st.session_state['processing'] = False
        
        with col_text:
            st.subheader("Step 4: Verify & Edit Transcription")
            
            if not st.session_state.get(transcription_key):
                st.info("Waiting for handwriting analysis...")
            
            edited_text = st.text_area(
                "Verify & Edit Transcription", 
                value=st.session_state.get(transcription_key, ""),
                height=200,
                key=transcription_key
            )

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
                # Capture latest state
                st.session_state['student_attempts_for_report'] = st.session_state.get(f"edited_transcription_{student_id}", "")
                
                with st.spinner('AI Crew is analyzing spelling patterns...'):
                        try:
                            # Use intended words from session state, or fall back to default if not provided
                            intended_words_for_analysis = st.session_state.get("processed_intended_words")
                            if not intended_words_for_analysis:
                                # Fallback if target words were not provided in step 1
                                intended_words_for_analysis = "fan, pet, dig, rob, hope, wait, gum, sled, stick, shine" 
                            
                            shadow_data = st.session_state.get(classroom_data_key, [])

                            print(f"DEBUG: Sending attempts to AI Crew...")

                            analysis_result = run_scoring_crew(
                                student_id,
                                st.session_state['student_attempts_for_report'],
                                intended_words=intended_words_for_analysis,
                                shadow_data=shadow_data,
                                analysis_complexity=analysis_complexity
                            )
                            
                            teacher_notes = getattr(analysis_result, 'teacher_notes', 'No analysis available yet.')
                            st.session_state.final_diagnostic_notes = teacher_notes
                            print(f"DEBUG: AI Analysis complete. Teacher notes extracted: {bool(teacher_notes)}")
                            
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
                            
                            st.success("Analysis complete! Review and confirm below.")
                            st.rerun()

                        except Exception as e:
                            st.error(f"Failed to run AI analysis: {e}. Please check your input and try again.")
                            st.session_state.final_diagnostic_notes = "AI analysis failed."
            
            # The Step 7 content has been moved to the end of display_student_detail_view function.


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

    st.markdown("---")

    # Platform Administrator Report: Active AI Corrections
    from ai_learning_engine import get_unified_learning_ledger

    st.subheader("Platform Administrator Report: Active AI Corrections")

    ledger_data = get_unified_learning_ledger()

    if not ledger_data:
                st.info("No AI macro calibrations recorded yet.")
    else:
                # Convert list of dicts to DataFrame for neat visualization
                df_ledger = pd.DataFrame(ledger_data)

                # Ensure expected columns exist, provide defaults if missing
                cols_to_show = {
                    "timestamp": "Timestamp",
                    "student_id": "Student ID",
                    "ai_suggested_group": "AI Group",
                    "teacher_assigned_group": "Teacher Group",
                    "teacher_feedback": "Teacher Note",
                    "calibration_note": "AI Calibration"
                }

                # Reorder and rename columns for the UI
                available_cols = [c for c in cols_to_show.keys() if c in df_ledger.columns]
                display_df = df_ledger[available_cols].rename(columns=cols_to_show)

                # Render using interactive dataframe
                st.dataframe(
                    display_df,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "Teacher Note": st.column_config.TextColumn("Teacher Note", width="medium"),
                        "AI Calibration": st.column_config.TextColumn("AI Calibration", width="large")
                    }
                )

# =============================================================================
# RUN THE APP
# =============================================================================
if __name__ == "__main__":
    main()
