import os
from dotenv import load_dotenv
from litellm import completion
from crewai import Agent, Task, Crew
from pydantic import BaseModel, Field
from typing import List
import google.generativeai as genai
import streamlit as st
from model_config import get_available_model, get_model_fallbacks, set_model_from_env
from database_manager import get_latest_teacher_notes

# Setup the API with correct configuration
api_key = st.secrets.get("GOOGLE_API_KEY") or os.environ.get("GOOGLE_API_KEY")

# Configure the SDK
genai.configure(api_key=api_key)

# Use configurable model with fallback logic
def initialize_model():
    """Initialize model with fallback logic."""
    # Try environment override first
    model_name = set_model_from_env()
    if model_name:
        try:
            return genai.GenerativeModel(model_name)
        except Exception as e:
            st.warning(f"Model {model_name} not available: {e}")
    
    # Try preferred models in order
    for fallback_model in get_model_fallbacks():
        try:
            return genai.GenerativeModel(fallback_model)
        except Exception as e:
            continue
    
    # If no models work, raise error
    raise Exception("No available Gemini models found")

# Initialize model globally
model = initialize_model()

def get_ai_coaching_report(student_alias, g_level, history=None):
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

Student: '{student_alias}'
Current G-Level: {g_level}

=== FULL ASSESSMENT HISTORY (Oldest to Newest) ===
{history_context}

=== RECENT ENTRIES (Higher Priority) ===
{recent_context}

Based on this holistic review:
1. Identify persistent phonetic struggles (patterns appearing across multiple assessments)
2. Note any improvements or regression
3. Factor in teacher observations for context

Provide a coaching report with:
1. **Diagnostic Insight**: What phonetic patterns are they consistently missing?
2. **Progress Analysis**: How has their trajectory changed over time?
3. **Three Targeted Activities**: Specific practice for this week
4. **Next Step Recommendation**: Clear direction for continued growth

Keep the tone professional, encouraging, and actionable.
"""
    
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"AI Coaching currently unavailable: {str(e)}"
    
load_dotenv()

# --- 1. DYNAMIC WORD LIST LOGIC ---
def get_target_words(file_name="primary_inventory.txt"):
    folder_path = os.path.join("assessments", file_name)
    try:
        with open(folder_path, "r") as f:
            words = [line.strip() for line in f.readlines() if line.strip()]
            return ", ".join(words)
    except FileNotFoundError:
        return "fan, pet, dig, rob, hope, wait, gum, sled, stick, shine"

CURRENT_TEST_WORDS = get_target_words()

# --- 2. DATA STRUCTURE ---
''' This was the previous schema, it is not robust enough.
class WTWScoreSchema(BaseModel):
    student_name: str
    words_correct: int
    feature_points: int
    total_score: int
    spelling_stage: str
    next_focus: str
    short_explanation: str
'''
class AssessmentSchema(BaseModel):
    student_name: str

    # GROUP 0 — Phonemic Awareness
    g0_phonemic_awareness: int = Field(description="Ability to perceive and manipulate phonemes (minimal pairs, segmentation, blending)")

    # GROUP 1 — Basic CVC Mapping (phoneme ↔ grapheme)
    g1_cvc_mapping: int = Field(description="Single consonant and short vowel mapping (CVC words)")

    # GROUP 2 — Digraphs & Two-Letter Phonemes
    g2_digraphs: int = Field(description="sh, ch, th, ng and related phoneme-grapheme mappings")

    # GROUP 3 — Silent-e (VCe system)
    g3_silent_e: int = Field(description="Long vowel patterns with silent-e (a_e, i_e, etc.)")

    # GROUP 4 — Vowel Teams (multiple graphemes per phoneme)
    g4_vowel_teams: int = Field(description="ee, ea, ai, oa, ou, oi, etc.")

    # GROUP 5 — R-Controlled Vowels
    g5_r_controlled: int = Field(description="ar, or, er, ir, ur patterns")

    # GROUP 6 — Consonant Clusters & Complex Codas
    g6_clusters: int = Field(description="Blends and complex consonant clusters (CCVC, CVCC, CCCVC)")

    # GROUP 7 — Multisyllabic Words & Division
    g7_multisyllabic: int = Field(description="Syllable types and division patterns (VC/CV, V/CV, VC/V)")

    # GROUP 8 — Reduced Vowels, Stress & Morphology
    g8_reduction_morphology: int = Field(description="Schwa, stress patterns, inflections, morphological changes")

    # Flexible recommendation (NOT linear)
    suggested_next_groups: List[str] = Field(
        description="List of 1-3 groups that should be targeted next based on weakest areas and learning priority"
    )

    teacher_notes: str = Field(
        description="Concise diagnostic summary including phonological vs orthographic issues"
    )
# --- 3. VISION TRANSCRIPTION ---
def transcribe_handwriting(base64_image):
    target_words = get_target_words()
    
    # This prompt forces the AI to be a 'dumb' camera, not a 'smart' assistant
    system_prompt = f"""
    ROLE: Literal OCR Transcriber.
    TASK: Transcribe handwritten words from a spelling test.
    
    REFERENCE WORDS: {target_words}
    
    STRICT RULES:
    1. DO NOT CORRECT SPELLING. If you see 'h-u-p', write 'hup', even if the word is 'hope'.
    2. LOOK AT THE SHAPES. If a letter is ambiguous, choose the one that matches the ink.
    3. If a word is crossed out, ignore it.
    4. If some lines are fainter than others, it could indicate the student erased letters, ignore significantly fainter markings
    5. FORMAT: target_word: student_attempt (e.g., fan: fan)
    """

    response = completion(
        model="groq/meta-llama/llama-4-scout-17b-16e-instruct",
        messages=[{"role": "user", "content": [
            {"type": "text", "text": system_prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
        ]}],
        temperature=0.0 # Keep this at 0.0 for zero creativity!
    )
    return response.choices[0].message.content

# --- 4. CREWAI AGENTS ---
'''assessor = Agent(
    role="WTW Spelling Assessor",
    goal=f"Score student attempts against these targets: {CURRENT_TEST_WORDS}",
    backstory="Expert Grade 2 teacher trained in Words Their Way scoring.",
    llm="groq/llama-3.3-70b-versatile",
    allow_delegation=False
)'''
assessor = Agent(
    role="ESL Spelling and Phonology Assessor",
    goal=f"""
    Analyze student spelling attempts against target words: {CURRENT_TEST_WORDS}.
    
    Evaluate performance using a group-based system:
    - g0_phonemic_awareness
    - g1_cvc_mapping
    - g2_digraphs
    - g3_silent_e
    - g4_vowel_teams
    - g5_r_controlled
    - g6_clusters
    - g7_multisyllabic
    - g8_reduction_morphology

    Also identify key error patterns from a controlled list.
    """,
    
    backstory="""
    You are an expert ESL literacy assessor specializing in phonology (IPA-informed) 
    and English orthography. You analyze spelling errors by distinguishing:

    - phonological issues (sound perception/production)
    - orthographic issues (spelling patterns)
    - phonotactic issues (word structure constraints)

    You understand common transfer issues for Mandarin L1 learners, including:
    - difficulty with /ɪ/ vs /iː/
    - absence of /θ/ and /ð/
    - final consonant deletion
    - lack of vowel reduction (schwa)

    You do NOT use grade-level or native-speaker developmental assumptions.
    You assess each linguistic feature independently.
    """,
    
    llm="groq/llama-3.3-70b-versatile",
    allow_delegation=False
)
''' This is the previous function, it is not robust enough.
def run_scoring_crew(student_name, transcription_text):
    task = Task(
        description=f"""
        Analyze these attempts for {student_name}:
        {transcription_text}
        
        Compare them to: {CURRENT_TEST_WORDS}
        Calculate: Words Correct (/26), Feature Points (/56), and Stage.
        """,
        agent=assessor,
        expected_output="JSON assessment summary.",
        output_json=WTWScoreSchema
    )
    crew = Crew(agents=[assessor], tasks=[task])
    return crew.kickoff()
    return result
'''
def run_scoring_crew(student_id, transcription_text, intended_words=None):
    """
    Runs the AI scoring crew for a student's transcription.
    PRIVACY: Uses 'The Student' alias instead of real name in all AI prompts.
    
    Args:
        student_id: Internal student ID (never shown to AI)
        transcription_text: The student's spelling attempts
        intended_words: Optional comma-separated list of target words (from test template)
    """
    # Use provided words or fall back to global default
    target_words = intended_words if intended_words else CURRENT_TEST_WORDS
    
    # PRIVACY: Always use 'The Student' alias in AI prompts
    student_alias = "The Student"
    
    # 1. FETCH PREVIOUS FEEDBACK
    past_feedback = get_latest_teacher_notes(student_id)
    feedback_context = f"PREVIOUS TEACHER CORRECTIONS FOR {student_alias}: {past_feedback}" if past_feedback else ""

    # 2. DEFINE THE INSTRUCTIONS
    task_description = f"""
    {feedback_context}
    
    Analyze the following spelling attempts for {student_alias}:
    {transcription_text}
    
    Compare them to: {target_words}

    STRICT RULES:
    - Refer back to 'PREVIOUS TEACHER CORRECTIONS'. If the teacher previously 
      corrected a hallucination (e.g. 'Stop assuming /θ/ issues'), DO NOT repeat that error in your notes.
    - Base all notes on VISIBLE EVIDENCE in the current {transcription_text}.
    
    FORMATTING RULES (CRITICAL):
    - When referring to a SOUND (Phoneme), you MUST use slashes (e.g., /θ/, /d/, /st/).
    - When referring to a written LETTER or PATTERN (Grapheme), you MUST use angle brackets (e.g., <th>, <ed>, <st>).
    - Always provide at least TWO written examples from the student's attempts to prove an error pattern exists.

    INSTRUCTIONS:
    Evaluate mastery (0–100%) across linguistic groups (g0 through g8).
    - Distinguish phonological errors (sound perception/production) from orthographic errors (spelling pattern mistakes)
    - Pay CLOSE attention to Group 6 (Clusters/Blends). For Mandarin L1 speakers, look for:
        * Omitted letters in consonant blends (e.g., writing 'sed' instead of 'sled' or 'sik' instead of 'stick').
        * Extra vowels inserted in blends (e.g., 'seled' for 'sled').
    - Consider other ESL-specific issues (Mandarin L1 transfer):
        * Difficulty with /θ/, /ð/, /ɹ/, /ɪ/
        * Final consonant omission
        * Vowel reduction absence
    - A student may be strong in some higher groups while weak in earlier ones

    CRITICAL RULE: Do NOT use clinical speech therapy terms like "consonant cluster reduction" or "phonological processes." This is a spelling assessment, not a speech assessment. Focus purely on whether the student heard the sounds (listening) and whether they mapped them to the correct letters (spelling). If a student misses a letter in a blend, call it an "omitted letter in a consonant blend." Keep your analysis strictly educational and focused on written orthography.

    CRITICAL: You MUST reply with a valid JSON object only.
    Follow this exact structure:
    {{
        "suggested_next_groups": ["g1", "g2"],
        "raw_analysis": "Your analysis text goes here."
    }}
    """

    task = Task(
        description=task_description,
        agent=assessor,
        expected_output="JSON group-based linguistic assessment.",
        output_json=AssessmentSchema
    )

    # 3. KICK OFF THE CREW SAFELY
    crew = Crew(agents=[assessor], tasks=[task])
    
    try:
        crew_output = crew.kickoff()
        
        # If the crew actually gave us back the perfect structured Pydantic object:
        if hasattr(crew_output, 'pydantic') and crew_output.pydantic is not None:
            return crew_output.pydantic
            
        # If it just gave us raw text but didn't structure it:
        if hasattr(crew_output, 'raw') and crew_output.raw:
            return crew_output
            
        # Fallback if it returned something weird
        return crew_output
        
    except Exception as e:
        print(f"Crew execution error recorded: {e}")
        # Return a fake object so app.py doesn't see 'None' and crash!
        class FallbackResult:
            student_name = "The Student"  # PRIVACY: Use alias
            teacher_notes = f"Notice: The analysis failed to complete automatically (Error: {e}). Please score manually."
            suggested_next_groups = []
            # Fill in 0s so the UI metrics don't break
            g0_phonemic_awareness = 0; g1_cvc_mapping = 0; g2_digraphs = 0
            g3_silent_e = 0; g4_vowel_teams = 0; g5_r_controlled = 0
            g6_clusters = 0; g7_multisyllabic = 0; g8_reduction_morphology = 0
            raw = f"Analysis timed out or failed. Technical details: {e}"
            
        return FallbackResult()

# --- 5. PERSONALIZED WORD GENERATION ---
# Agent for generating personalized practice words
word_generator = Agent(
    role="Personalized Spelling Word Selector",
    goal="Generate 10 highly targeted spelling words for a specific student based on their G-level and struggle areas",
    backstory="""
    You are an expert literacy specialist who creates personalized word lists for spelling practice.
    You understand the Words Their Way (WTW) diagnostic groups and how to create effective practice lists.
    
    You understand:
    - G0: Phonemic Awareness (sound manipulation)
    - G1: Basic CVC Mapping (consonant-short vowel-consonant)
    - G2: Digraphs (sh, ch, th, ng)
    - G3: Silent-e (magic e, VCe patterns)
    - G4: Vowel Teams (ee, ea, ai, oa, ou, oi, etc.)
    - G5: R-Controlled Vowels (ar, or, er, ir, ur)
    - G6: Consonant Clusters/Blends (CCVC, CVCC words)
    - G7: Multisyllabic Words (syllable division)
    - G8: Reduction & Morphology (schwa, -ed, -ing, etc.)
    
    You specialize in ESL/Mandarin L1 learners who have specific phonological and orthographic challenges.
    """,
    llm="groq/llama-3.3-70b-versatile",
    allow_delegation=False
)

def generate_personalized_practice_words(student_id, target_group, teacher_notes, struggling_words, mastered_words="", unit_description="", custom_words_input=None):
    """
    Uses AI to generate 10 personalized spelling words based on:
    - Unit Description (global class focus)
    - Target G-level (e.g., G4 Vowel Teams)
    - Teacher's refinement notes (student's background/struggles)
    - struggling_words (in 'Correct:Attempt' format) to identify phonetic weaknesses
    - mastered_words (list of words student consistently spells correctly)
    - Custom words input by teacher
    
    PRIVACY: Uses 'The Student' alias instead of real name in all AI prompts.
    
    Args:
        student_id: Internal student ID (never shown to AI)
        target_group: Primary G-level to target (e.g., "g4")
        teacher_notes: Teacher's refinement notes with background/struggles
        struggling_words: Words student has struggled with before ('Correct:Attempt' format)
        mastered_words: Words the student has already mastered
        unit_description: The overall unit or theme for the whole class
        custom_words_input: Optional comma-separated string of words teacher wants included
    
    Returns:
        List of 10 personalized words, or fallback list if AI fails
    """
    
    # PRIVACY: Always use 'The Student' alias in AI prompts
    student_alias = "The Student"
    
    # Group descriptions and patterns
    GROUP_INFO = {
        "g0": {
            "name": "Phonemic Awareness",
            "patterns": "sound segmentation, blending, minimal pairs, phoneme manipulation",
            "examples": "bat-pat, fan-fan, cat-cut"
        },
        "g1": {
            "name": "Basic CVC Mapping",
            "patterns": "single consonants and short vowels (CVC words)",
            "examples": "cat, bed, sit, run, hop, map"
        },
        "g2": {
            "name": "Digraphs",
            "patterns": "sh, ch, th, ng",
            "examples": "shop, chip, thin, ring, chin, ship"
        },
        "g3": {
            "name": "Silent-e",
            "patterns": "a_e, i_e, o_e, u_e (long vowel with silent e)",
            "examples": "make, bike, hope, cute, cake, side"
        },
        "g4": {
            "name": "Vowel Teams",
            "patterns": "ee, ea, ai, oa, ou, oi, ay, ey patterns",
            "examples": "see, sea, rain, boat, sound, coin, day, they"
        },
        "g5": {
            "name": "R-Controlled Vowels",
            "patterns": "ar, or, er, ir, ur",
            "examples": "car, fork, her, bird, turn, star, form"
        },
        "g6": {
            "name": "Consonant Clusters/Blends",
            "patterns": "initial blends (bl, cl, fl, gl, pl, br, cr, dr, fr, gr, pr, tr, st, sk, sl, sw), final clusters",
            "examples": "sled, stick, swim, dress, crash, plant, sleep"
        },
        "g7": {
            "name": "Multisyllabic Words",
            "patterns": "compound words, syllable division (VC/CV, V/CV)",
            "examples": "rainbow, sunshine, basket, pencil, computer"
        },
        "g8": {
            "name": "Reduction & Morphology",
            "patterns": "schwa, -ed, -ing, -s, -es, prefixes, suffixes",
            "examples": "walked, jumping, cats, boxes, unhappy, quickly"
        }
    }
    
    group_key = target_group.lower().strip()
    group_info = GROUP_INFO.get(group_key, GROUP_INFO["g1"])
    
    # Build context for the AI
    custom_words_context = f"\n\nTEACHER REQUESTED CUSTOM WORDS (must include these):\n{custom_words_input}" if custom_words_input else ""
    
    struggling_context = f"\n\nWORDS STUDENT HAS STRUGGLED WITH (Correct:Attempt format):\n{struggling_words}" if struggling_words else "\n\n(No previous struggling words found in records.)"
    
    mastered_context = f"\n\nWORDS STUDENT HAS MASTERED (Spelled Correctly):\n{mastered_words}" if mastered_words else "\n\n(No mastered words provided.)"
    
    notes_context = f"\n\nTEACHER NOTES (Student Background & Struggles):\n{teacher_notes}" if teacher_notes else "\n\n(No teacher notes available.)"
    
    unit_context = f"\n\nGLOBAL UNIT DESCRIPTION: {unit_description}" if unit_description else "\n\n(No global unit description provided.)"
    
    task_description = f"""
You are creating a personalized 10-word spelling practice list for a student.

STUDENT: {student_alias}

TARGET G-LEVEL: {target_group.upper()} - {group_info['name']}
Phonetic Patterns to Practice: {group_info['patterns']}
Example Patterns: {group_info['examples']}{notes_context}{struggling_context}{mastered_context}{unit_context}{custom_words_context}

TASK:
1. FIND THE LEARNING FRONTIER: Compare the 'Mastered Words' list against the 'Correct:Attempt' (struggles) list. Identify the exact point where the student's accuracy drops. This is the 'Frontier' of their learning.
2. ANALYZE PHONETIC WEAKNESSES: Closely examine the 'Correct:Attempt' list to identify specific phonetic gaps (e.g., if they spell 'ship' as 'sip', the gap is the <sh> digraph).
3. GENERATE 10 WORDS: Create a list of 10 spelling words that:
    - Target the 'Frontier': Focus on patterns just beyond what they have mastered but aligned with their current struggles.
    - Directly target the identified phonetic weaknesses.
    - Align with the {group_info['name']} target patterns.
    - CONTEXT: Incorporate the Global Unit Description to theme the words.
    - PROGRESSION: Progress from the edge of their mastery to more challenging words.
    - Include 2-3 words from their previous struggles for reinforcement.
    - If custom words were requested, include those.

IMPORTANT:
- Focus on real, common words.
- Ensure the words are not too easy (already mastered) nor too hard (completely out of reach). Target the Frontier.
- Theme the words creatively based on the Unit Description while ensuring they accurately target the phonetic pattern.

FORMAT:
Return ONLY a valid JSON array of 10 words, nothing else.
Example: ["word1", "word2", "word3", "word4", "word5", "word6", "word7", "word8", "word9", "word10"]
"""
    
    task = Task(
        description=task_description,
        agent=word_generator,
        expected_output="A JSON array of exactly 10 personalized spelling words"
    )
    
    crew = Crew(agents=[word_generator], tasks=[task])
    
    try:
        crew_output = crew.kickoff()
        
        # Try to parse the JSON response
        import json
        output_text = str(crew_output)
        
        # Look for JSON array in the response
        import re
        json_match = re.search(r'\[.*?\]', output_text, re.DOTALL)
        
        if json_match:
            words = json.loads(json_match.group(0))
            if isinstance(words, list) and len(words) >= 1:
                return words[:10]  # Return max 10 words
        
        # Fallback: try to extract words another way
        # Remove brackets and split by comma, then clean up
        cleaned = output_text.strip('[]').replace('"', '').replace("'", '')
        words = [w.strip() for w in cleaned.split(',') if w.strip()]
        if words:
            return words[:10]
        
        # If all parsing fails, return fallback
        return get_fallback_words(group_key)
        
    except Exception as e:
        print(f"Word generation error: {e}")
        return get_fallback_words(group_key)

def get_fallback_words(target_group):
    """Fallback word lists if AI generation fails."""
    fallback_by_group = {
        "g0": ["bat", "pat", "cat", "mat", "sat", "hat", "rat", "fat", "vat", "zat"],
        "g1": ["cat", "bed", "sit", "run", "hop", "map", "red", "big", "sun", "cup"],
        "g2": ["shop", "chip", "thin", "ring", "chin", "ship", "this", "that", "fish", "wish"],
        "g3": ["make", "bike", "hope", "cute", "cake", "side", "home", "note", "size", "game"],
        "g4": ["see", "sea", "rain", "boat", "sound", "day", "green", "team", "play", "snow"],
        "g5": ["car", "fork", "her", "bird", "turn", "star", "form", "burn", "hard", "work"],
        "g6": ["sled", "stick", "swim", "dress", "crash", "plant", "sleep", "green", "brick", "flash"],
        "g7": ["rainbow", "sunshine", "basket", "pencil", "window", "rabbit", "flower", "garden", "purple", "yellow"],
        "g8": ["walked", "jumping", "cats", "boxes", "unhappy", "quickly", "happier", "largest", "playing", "stopped"]
    }
    return fallback_by_group.get(target_group, fallback_by_group["g1"])