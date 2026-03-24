import os
from dotenv import load_dotenv
import litellm
from crewai import Agent, Task, Crew
from pydantic import BaseModel
from typing import List, Optional
import streamlit as st
from pathlib import Path

#debugging fault
print(f"DEBUG: Current Folder: {Path.cwd()}")
print(f"DEBUG: Looking for .env at: {Path(__file__).parent / '.env'}")
print(f"DEBUG: Does that file exist? {(Path(__file__).parent / '.env').exists()}")


# 1. LOAD SECRETS & SETTINGS
# This finds the folder where spelling_coach.py actually lives
env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)

api_key = os.getenv("GROQ_API_KEY")


if not api_key:
    st.error("🔑 API Key not found! Please check your .env file.")
    st.stop()
os.environ["GROQ_API_KEY"] = api_key
os.environ["OPENAI_API_KEY"] = "NA" # Keeps CrewAI from looking for OpenAI

# 2. LITELLM CONFIG (The "Patience" and "Silence" settings)
litellm.request_timeout = 300
litellm.suppress_debug_info = True
litellm.set_verbose = False 

# 3. CHOOSE YOUR BRAIN
# We are using Groq's biggest model for high-accuracy spelling analysis
llm = "groq/llama-3.3-70b-versatile"

class WTWScoreSchema(BaseModel):
    student_name: str
    words_correct: int
    words_incorrect_list: List[str]
    feature_points: int
    total_score: int
    spelling_stage: str
    mastered_patterns: List[str]
    struggle_patterns: List[str]
    next_focus: str
    short_explanation: str
# ────────────────────────────────────────────────
#  AGENT: WTW Primary Spelling Inventory Assessor
# ────────────────────────────────────────────────

assessor = Agent(
    role="WTW Primary Spelling Inventory Assessor",
    goal="Accurately score a grade 2 student's Primary Spelling Inventory using official Words Their Way rules.",
    backstory="""You are an experienced grade 2 English teacher who knows the official WTW Primary Spelling Inventory feature guide inside out.
    You carefully score:
    - Words correct (/26)
    - Feature points (/56) — consonants, short vowels, digraphs/blends, long vowels, r-controlled, diphthongs, etc.
    - Total score (/82)
    Then assign the correct stage (most grade 2 students are in Letter Name-Alphabetic or Within Word Pattern).
    Finally, suggest the next 1–2 targeted spelling features with examples.""",
    llm=llm,
    verbose=True,
    allow_delegation=False
)

# ────────────────────────────────────────────────
#  TASK: Score one student's spellings
# ────────────────────────────────────────────────

task = Task(
    description="""
    Analyze the following student spelling attempts:
    {student_spellings}

    Follow this EXACT scoring method to ensure mathematical accuracy:
    
    1. WORD SCORE: Check each word. If it is 100% correct, 1 point. (Total out of 26).
    2. FEATURE SCORE: Check the specific phonetic features (For short vowels, give a point for each of these features, the correct initial and final consonants and the correct vowel. For words with other vowels give points for each digraph, blend, long vowel patterns, inflected endings, -r controlled vowels). 
       - Award 1 point for every correct feature identified in the student's attempt.
    
    COMPUTATION:
    - Step A: Count the number of words spelled correctly.
    - Step B: Count the total number of phonetic feature points earned.
    - Step C: Count the total number of possible phonetic features in the inventory (56).
    - Step C: total_score = (Step A + Step B).
    
    Finalize the assessment by identifying the student's spelling stage and next instructional focus.
    """,
    agent=assessor,
    expected_output="A structured JSON object with precise numerical totals and phonetic analysis.",
    output_json=WTWScoreSchema
)

from litellm import completion

def transcribe_handwriting(base64_image):
    '''
    This is from POE
    '''
    """
    Sends a photo of student handwriting to Groq's vision model.
    Returns the AI's best guess at what words were written.
    """
    print("🚀 Sending image to AI for transcription...")
    
    try:
        response = completion(
            model="groq/meta-llama/llama-4-scout-17b-16e-instruct",  # Groq's vision model
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": """You are helping a grade 2 teacher transcribe student spelling attempts.
                            
                            Look at this handwritten spelling test and transcribe ONLY the words the student wrote.
                            
                            Format your response EXACTLY like this:
                            fan: fan
                            pet: pet
                            dig: dig
                            
                            (That means: test_word: student_attempt)
                            
                            If you can't read a word, write: word: [unclear]
                            Do not add any other commentary."""
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{base64_image}"
                            }
                        }
                    ]
                }
            ]
        )
        
        transcribed_text = response.choices[0].message.content
        print("✅ Transcription successful!")
        return transcribed_text
        
    except Exception as e:
        error_msg = f"Error reading handwriting: {str(e)}"
        print(f"❌ {error_msg}")
        return error_msg
    
import base64

def encode_image(image_file):
    """Converts the uploaded image into a format the AI can understand."""
    return base64.b64encode(image_file.read()).decode('utf-8')

# This is the specialized 'Vision' prompt for the AI
VISION_PROMPT = """
You are an expert at reading primary school student handwriting. 
Analyze the spelling test image provided.
For each word:
1. Number the test words in order (1. fan, 2. pet, etc.)
1. Identify the target word (the word the teacher said).
2. Identify exactly what the student wrote.

Format the output as a clean list like this:
1. fan: fan
2. pet: pet
3. dig: dig

If a student wrote something that isn't a word, transcribe the letters exactly as they appear. 
Do not repeat words and do not add conversational filler.
"""
# ────────────────────────────────────────────────
#  CREATE & RUN THE CREW
# ────────────────────────────────────────────────

crew = Crew(
    agents=[assessor],
    tasks=[task],
    verbose=True 
)

example_student = """
NAME: Sam Smith
YEAR: 2
SPELLINGS:
fan: fan
pet: pet
dig: dig
rob: rob
hope: hop
wait: wate
gum: gum
sled: sled
stick: stik
shine: shyn
dream: drem
blade: blayd
coach: coch
fright: frite
chewed: chud
crawl: crol
wishes: wishis
thorn: thron
shouted: shoutid
spoil: spoyl
growl: growl
third: thurd
camped: campd
tries: trys
clapping: claping
riding: ryding
"""

import csv
from datetime import datetime

def append_to_ledger(data_object):
    file_name = 'students.csv'
    file_exists = os.path.isfile(file_name)
    
    # Define the columns for our Spreadsheet
    headers = [
        'Date', 'Student Name', 'Stage', 'Score', 
        'Correct Words', 'Total Feature Points', 'Mastered', 'Struggles', 'Next Steps'
    ]
    
    with open(file_name, mode='a', newline='') as file:
        writer = csv.writer(file)
        if not file_exists:
            writer.writerow(headers) # Write the header only once
            
        writer.writerow([
            datetime.now().strftime("%Y-%m-%d"),
            data_object.student_name,
            data_object.spelling_stage,
            f"{data_object.total_score}/82",
            data_object.words_correct,
            data_object.feature_points,
            ", ".join(data_object.mastered_patterns),
            ", ".join(data_object.struggle_patterns),
            data_object.next_focus
        ])
    print(f"\n📁 Data for '{data_object.student_name}' has been saved to students.csv")
    

import json

if __name__ == "__main__":
    print("Running Structured Assessment...")
    result = crew.kickoff(inputs={"student_spellings": example_student})
    
    # 1. Try to get the data from pydantic first
    data = result.pydantic
    
    # 2. If that's empty, try to manually pull it from the raw text
    if not data:
        try:
            # This looks for the JSON inside the AI's response
            raw_text = result.raw
            # Remove any triple backticks if the AI added them
            clean_json = raw_text.replace("```json", "").replace("```", "").strip()
            data_dict = json.loads(clean_json)
            
            # Use a simple 'Namespace' so our ledger function still works
            from types import SimpleNamespace
            data = SimpleNamespace(**data_dict)
        except Exception as e:
            print(f"Manual parsing failed: {e}")

    if data:
        print(f"\nAnalysis Complete for {data.student_name}!")
        print(f"Stage: {data.spelling_stage} | Score: {data.total_score}/82")
        append_to_ledger(data)
    else:
        print("\n❌ Error: Could not extract data from AI response.")