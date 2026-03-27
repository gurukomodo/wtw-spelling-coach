import os
from dotenv import load_dotenv
from litellm import completion
from crewai import Agent, Task, Crew
from pydantic import BaseModel, Field
from typing import List
from database_manager import get_latest_teacher_notes

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
def run_scoring_crew(student_name, transcription_text):
    # 1. FETCH PREVIOUS FEEDBACK
    past_feedback = get_latest_teacher_notes(student_name)
    feedback_context = f"PREVIOUS TEACHER CORRECTIONS FOR THIS STUDENT: {past_feedback}" if past_feedback else ""

    task_description = f"""
    {feedback_context}
    
    Analyze {student_name}'s attempts: {transcription_text}
    
    STRICT RULES:
    - Refer back to 'PREVIOUS TEACHER CORRECTIONS'. If the teacher previously 
      corrected a hallucination (e.g. 'Stop assuming /θ/ issues'), DO NOT repeat that error.
    - Base all notes on VISIBLE EVIDENCE in the current {transcription_text}.
    """
    
    task_description = f"""
    Analyze the following spelling attempts for {student_name}:

    {transcription_text}
    Compare them to: {CURRENT_TEST_WORDS}

    Evaluate mastery (0–100%) across linguistic groups (g0 through g8):

    IMPORTANT:
    - Distinguish phonological errors (incorrect sound perception/production) from orthographic errors (spelling pattern mistakes)
    - Consider ESL-specific issues (Mandarin L1 transfer):
        * Difficulty with /θ/, /ð/, /ɹ/, /ɪ/
        * Final consonant omission
        * Vowel reduction absence
    - A student may be strong in some higher groups while weak in earlier ones

    Output:
    - Score each group (0–100)
    - Suggest 1–3 target groups (NOT necessarily the lowest only—prioritize impact)
    - Provide a concise diagnostic summary
    
    STRICT EVIDENCE RULES:
    1. Only mention an error pattern if you can cite at least TWO words from the student's attempts as proof.
    2. If a student didn't attempt enough words to judge a category (e.g., no g8 words were tested), score it as 'null' or 0 and state 'Insufficient data'.
    3. DO NOT assume Mandarin transfer issues (like /θ/) unless the student specifically failed a word containing that phoneme (e.g., 'thorn' or 'with').
    4. Distinguish between 'Omission' (left the letter out) and 'Substitution' (used the wrong letter).
    """

    task = Task(
        description=task_description,
        agent=assessor,
        expected_output="JSON group-based linguistic assessment.",
        output_json=AssessmentSchema
    )

    crew = Crew(agents=[assessor], tasks=[task])
    return crew.kickoff()
    return result