import os
from dotenv import load_dotenv
from litellm import completion
from crewai import Agent, Task, Crew
from pydantic import BaseModel
from typing import List

load_dotenv()

# --- 1. DYNAMIC WORD LIST LOGIC ---
def get_target_words(file_name="primary_inventory.txt"):
    folder_path = os.path.join("assessments", file_name)
    try:
        with open(folder_path, "r") as f:
            return f.read().strip()
    except FileNotFoundError:
        return "fan, pet, dig, rob, hope, wait, gum, sled, stick, shine"

CURRENT_TEST_WORDS = get_target_words()

# --- 2. DATA STRUCTURE ---
class WTWScoreSchema(BaseModel):
    student_name: str
    words_correct: int
    feature_points: int
    total_score: int
    spelling_stage: str
    next_focus: str
    short_explanation: str

# --- 3. VISION TRANSCRIPTION ---
def transcribe_handwriting(base64_image):
    """Sends the 'Clean' image to Llama 4 Scout for literal transcription."""
    try:
        response = completion(
            model="groq/meta-llama/llama-4-scout-17b-16e-instruct",
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "text", 
                        "text": f"""ACT AS A FORENSIC HANDWRITING EXPERT.
                        Transcribe EXACTLY what is written. Do NOT correct spelling.
                        TARGET WORDS: {CURRENT_TEST_WORDS}
                        Format: target_word: student_attempt"""
                    },
                    {
                        "type": "image_url", 
                        "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}
                    }
                ]
            }],
            temperature=0.0
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Error: {str(e)}"

# --- 4. CREWAI AGENTS ---
assessor = Agent(
    role="WTW Spelling Assessor",
    goal=f"Score student attempts against these targets: {CURRENT_TEST_WORDS}",
    backstory="Expert Grade 2 teacher trained in Words Their Way scoring.",
    llm="groq/llama-3.3-70b-versatile",
    allow_delegation=False
)

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