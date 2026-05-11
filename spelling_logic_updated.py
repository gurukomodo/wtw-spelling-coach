import os
from dotenv import load_dotenv
from litellm import completion
from crewai import Agent, Task, Crew
from pydantic import BaseModel, Field
from typing import List
import google.genai as genai
import streamlit as st
from model_config import get_available_model, get_model_fallbacks, set_model_from_env
from database_manager import get_latest_teacher_notes

# Setup API with correct configuration
api_key = st.secrets.get("GOOGLE_API_KEY") or os.environ.get("GOOGLE_API_KEY")

# Configure SDK
if api_key:
    # Check if OTEL_SDK_DISABLED environment variable is set
    if os.environ.get("OTEL_SDK_DISABLED"):
        print("DEBUG: OTEL_SDK_DISABLED is set, skipping genai.configure()")
    else:
        genai.configure(api_key=api_key)
else:
    print("ERROR: No GOOGLE_API_KEY found in st.secrets or environment variables")

# Use configurable model with fallback logic
def initialize_model():
    """Initialize model with fallback logic."""
    # Try environment override first
    model_name = set_model_from_env()
    
    if model_name:
        try:
            model_obj = genai.GenerativeModel(model_name)
            return model_obj
        except Exception as e:
            st.warning(f"Model {model_name} not available: {e}")
    
    # Try preferred models in order
    for fallback_model in get_model_fallbacks():
        try:
            model_obj = genai.GenerativeModel(fallback_model)
            return model_obj
        except Exception as e:
            continue
    
    # If no models work, raise error
    raise Exception("No available Gemini models found")

# Initialize model globally
try:
    model = initialize_model()
except Exception as e:
    print(f"ERROR: Failed to initialize Gemini model: {e}")
    model = None

def get_ai_coaching_report(student_name, g_level, history=None):
    """
    Sends holistic student history to Gemini and returns a coaching plan.
    Reviews the provided history (ordered oldest to newest) to identify patterns.
    """
    
    # Build history context from list of assessments
    history_context = "No previous assessments."
    recent_context = ""
    
    if history and len(history) > 0:
        history_entries = []
        for i, entry in enumerate(history):
            # entry format: dictionary with keys like 'test_date', 'created_at', 'g0_phonemic', etc.
            test_date = entry.get('created_at', f"Assessment {i+1}")
            g_scores = f"G0:{entry.get('g0_phonemic', 0)}%, G1:{entry.get('g1_cvc', 0)}%, G2:{entry.get('g2_digraphs', 0)}%, G3:{entry.get('g3_silent_e', 0)}%, G4:{entry.get('g4_vowel_teams', 0)}%, G5:{entry.get('g5_r_controlled', 0)}%, G6:{entry.get('g6_clusters', 0)}%, G7:{entry.get('g7_multisyllabic', 0)}%, G8:{entry.get('g8_reduction', 0)}%"
            struggles = entry.get('struggling_words', "")
            notes = entry.get('teacher_refined_notes', "") or entry.get('teacher_notes', "")
            observations = entry.get('teacher_observations', "")
            
            entry_str = f"--- {test_date[:10]} ---\nScores: {g_scores}\n"
            if struggles:
                entry_str += f"Struggles: {struggles}\n"
            if observations:
                entry_str += f"Teacher Notes: {observations}\n"
            if notes:
                entry_str += f"AI Analysis: {notes}\n"
            
            history_entries.append(entry_str)
        
        history_context = "\n\n".join(history_entries)
        
        # Recent context for priority weighting
        recent = history[-2:] if len(history) >= 2 else history
        recent_entries = []
        for entry in recent:
            struggles = entry.get('struggling_words', "")
            observations = entry.get('teacher_observations', "")
            if struggles or observations:
                recent_entries.append(f"Recent: {struggles} | Notes: {observations}")
        recent_context = "\n".join(recent_entries) if recent_entries else ""
    
    prompt = f"""
You are an Un.Box.Ed. coach analyzing a student's spelling trajectory.
Reviews the provided history (ordered oldest to newest) to identify patterns.
{history_context}
{recent_context}

Analyze the following spelling attempts for {student_name}:
{transcription_text}

Compare them to: {CURRENT_TEST_WORDS}
Calculate: Words Correct (/26), Feature Points (/56), and Stage.
"""

    task = Task(
        description=prompt,
        agent=assessor,
        expected_output="JSON assessment summary.",
        output_json=AssessmentSchema
    )
    crew = Crew(agents=[assessor], tasks=[task])
    return crew.kickoff()

def run_scoring_crew(student_id, transcription_text, intended_words=None, shadow_data=None, analysis_complexity="Brief"):
    """
    Runs AI scoring crew for a student's transcription.
    PRIVACY: Uses 'The Student' alias instead of real name in all AI prompts.
    
    Args:
        student_id: Internal student ID (never shown to AI)
        transcription_text: The student's spelling attempts
        intended_words: Optional comma-separated list of target words (from test template)
        analysis_complexity: "Brief", "Standard", or "Detailed" analysis level
    """
    # Use provided words or fall back to global default
    target_words = intended_words if intended_words else CURRENT_TEST_WORDS
    
    # PRIVACY: Always use 'The Student' alias in AI prompts
    student_alias = "The Student"
    
    # 1. FETCH PREVIOUS FEEDBACK
    past_feedback = get_latest_teacher_notes(student_id)
    feedback_context = f"PREVIOUS TEACHER CORRECTIONS FOR {student_alias}: {past_feedback}" if past_feedback else ""
    
    # 2. ADD SHADOW DATA CONTEXT
    shadow_context = ""
    if shadow_data:
        shadow_observations = []
        for entry in shadow_data:
            shadow_observations.append(f"Daily misspelling ({entry['timestamp']}): '{entry['incorrect']}' instead of '{entry['intended']}'")
        
        if shadow_observations:
            shadow_context = f"\n\nRECENT DAILY OBSERVATIONS:\n" + "\n".join(shadow_observations)
        else:
            shadow_context = "\n\nNo recent daily observations available.\n"
    
    # 2. DEFINE THE INSTRUCTIONS
    task_description = f"""
{feedback_context}
{shadow_context}

Analyze the following spelling attempts for {student_alias}:
{transcription_text}

Compare them to: {target_words}

STRICT RULES:
- Refer back to 'PREVIOUS TEACHER CORRECTIONS'. If teacher previously 
  corrected a hallucination (e.g. 'Stop assuming /θ/ issues'), DO NOT repeat that error in your notes.
- Base all notes on VISIBLE EVIDENCE in current transcription.
- When referring to a SOUND (Phoneme), you MUST use slashes (e.g., /θ/, /d/, /st/).
- When referring to a written LETTER or PATTERN (Grapheme), you MUST use angle brackets (e.g., <th>, <ed>, <st>).
- Always provide at least TWO written examples from the student's attempts to prove an error pattern exists.
- When referring to a SOUND (Phoneme), you MUST use slashes (e.g., /θ/, /d/, /st/).
- When referring to a written LETTER or PATTERN (Grapheme), you MUST use angle brackets (e.g., <th>, <ed>, <st>).
- When referring to a SOUND (Phoneme), you MUST use slashes (e.g., /θ/, /d/, /st/).
- When referring to a written LETTER or PATTERN (Grapheme), you MUST use angle brackets (e.g., <th>, <ed>, <st>).
- When referring to a SOUND (Phoneme), you MUST use slashes (e.g., /θ/, /d/, /st/).
- When referring to a written LETTER or PATTERN (Grapheme), you MUST use angle brackets (e.g., <th>, <ed>, <st>).

INSTRUCTIONS:
Evaluate mastery (0–100%) across linguistic groups (g0 through g8).
- Distinguish phonological errors (sound perception/production) from orthographic errors (spelling pattern mistakes).
- Pay CLOSE attention to Group 6 (Clusters/Blends). For Mandarin L1 speakers, look for:
    * Omitted letters in consonant blends (e.g., writing 'sed' instead of 'sled' or 'sik' instead of 'stick').
    * Extra vowels inserted in blends (e.g., 'seled' for 'sled').
- Consider other ESL-specific issues (Mandarin L1 transfer):
    * Difficulty with /θ/, /ð/, /ɹ/, /ɪ/
    * Omitted final consonant
    * Vowel reduction absence
    * Lack of schwa
- A student may be strong in some higher groups while weak in earlier ones
- CRITICAL: Do NOT use clinical speech therapy terms like "consonant cluster reduction" or "phonological processes." This is a spelling assessment, not a speech assessment. Focus purely on whether the student heard sounds (listening) and whether they mapped them to correct letters (spelling). If a student misses a letter in a blend, call it an "omitted letter in a consonant blend." Keep your analysis strictly educational and focused on written orthography.
SCORING CRITICAL: For each group level (g0-g8), you MUST check if the student attempted any words from that group in their transcription. If NO words from a specific group were attempted, you MUST assign "NA" (Not Assessed) instead of a numerical score. Only assign percentage scores (0-100) for groups where the student actually attempted words.
ANALYSIS COMPLEXITY: {analysis_complexity}
- Brief: Provide a 2-3 sentence pedagogical summary in teacher_notes
- Standard: Provide moderate detail with specific examples
- Detailed: Provide deep phonological breakdown with extensive analysis

CRITICAL: You MUST reply with a valid JSON object only.
Follow this exact structure:
{{
    "student_name": "The Student",
    "g0_phonemic_awareness": score_0,
    "g1_cvc_mapping": score_1,
    "g2_digraphs": score_2,
    "g3_silent_e": score_3,
    "g4_vowel_teams": score_4,
    "g5_r_controlled": score_5,
    "g6_clusters": score_6,
    "g7_multisyllabic": score_7,
    "g8_reduction_morphology": score_8,
    "suggested_next_groups": ["g1", "g2"],
    "teacher_notes": "Your analysis text goes here."
}}
"""

    task = Task(
        description=task_description,
        agent=assessor,
        expected_output="JSON group-based linguistic assessment.",
        output_json=AssessmentSchema
    )
    crew = Crew(agents=[assessor], tasks=[task])
    
    try:
        crew_output = crew.kickoff()
        
        # If crew actually gave us back a perfect structured Pydantic object:
        if hasattr(crew_output, 'pydantic') and crew_output.pydantic is not None:
            return crew_output.pydantic
            
        # If it just gave us raw text but didn't structure it:
        if hasattr(crew_output, 'raw') and crew_output.raw:
            # Try to parse the raw JSON into AssessmentSchema
            try:
                import json
                raw_data = json.loads(crew_output.raw)
                
                # Create AssessmentSchema object from parsed data
                result = AssessmentSchema(**raw_data)
                return result
                
            except json.JSONDecodeError as e:
                print(f"JSON parsing error in run_scoring_crew: {e}")
                return crew_output
            
        # Fallback if it returned something weird
        return crew_output
        
    except Exception as e:
        print(f"Crew execution error in run_scoring_crew: {e}")
        # Return a fake object so app.py doesn't see 'None' and crash!
        class FallbackResult:
            student_name = "The Student"  # PRIVACY: Use alias
            teacher_notes = f"Notice: The analysis failed to complete automatically (Error: {e}). Please score manually."
            suggested_next_groups = []
            # Fill in 0s so UI metrics don't break
            g0_phonemic_awareness = 0; g1_cvc_mapping = 0; g2_digraphs = 0
            g3_silent_e = 0; g4_vowel_teams = 0; g5_r_controlled = 0
            g6_clusters = 0; g7_multisyllabic = 0; g8_reduction_morphology = 0
            raw = f"Analysis timed out or failed. Technical details: {e}"
            
        return FallbackResult()

# --- 3. VISION TRANSCRIPTION ---
def transcribe_handwriting(base64_image):
    target_words = get_target_words()
    
    # Initialize GenAI client with new SDK structure
    try:
        client = genai.Client(api_key=api_key)
        print("DEBUG: Using new google.genai client structure")
    except Exception as e:
        print(f"ERROR: Failed to initialize GenAI client: {e}")
        client = None

    response = completion(
        model="groq/meta-llama/llama-4-scout-17b-16e-instruct",
        messages=[{"role": "reer", "content": [
            {"type": "text", "text": system_prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
        }],
        temperature=0.0 # Keep this at 0.0 for zero creativity!
    )
    
    # Terminal tracing: Output raw text from AI model
    raw_result = response.choices[0].message.content
    
    return raw_result

# --- 4. CREWAI AGENTS ---
'''assessor = Agent(
    role="WTW Spelling Assessor",
    goal=f"Score student attempts against these targets: {CURRENT_TEST_WORDS}",
    backstory="Expert Grade 2 teacher trained in Words Their Way scoring.",
    llm="groq/llama-3.3-70b-versatile",
    allow_delegation=False
)'''
