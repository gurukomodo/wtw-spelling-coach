from crewai import Agent, Task, Crew
#from langchain_ollama import ChatOllama
import os
# This line is a "safety net" to stop CrewAI from ever asking for a key
os.environ["OPENAI_API_KEY"] = "NA"

# ────────────────────────────────────────────────
#  SECTION 1: CHOOSE YOUR OLLAMA CONNECTION
# ────────────────────────────────────────────────

# OPTION A: Use Tailscale IP (recommended once Tailscale is working)
# Replace 100.64.xxx.xxx with your NAS's actual Tailscale IP
# (found in Tailscale menu bar on your Mac → device list → NAS entry)
TAILSCALE_NAS_IP = "100.64.55.61:11434"   # ← EDITed

# OPTION B: Use local IP (only works when on home network)
LOCAL_NAS_IP = "192.168.12.104"

# Choose which one to use (uncomment the line you want)
base_url="http://100.64.55.61:11434"  # ← your NAS Tailscale IP
# base_url = f"http://{LOCAL_NAS_IP}:11434"        # ← use this for home testing only

# ────────────────────────────────────────────────
#  SECTION 2: MODEL SETTINGS
# ────────────────────────────────────────────────

#llm = ChatOllama(
#    model="qwen2.5:7b",          # ← change to "llama3.2:3b" if you want to test with the smaller model
#    base_url=base_url,           # ← uses the URL you chose above
#    temperature=0.2,             # low = more consistent & accurate scoring
#    verbose=True                 # shows thinking steps (good for debugging)
llm = ChatOllama(
    model="ollama/qwen2.5:7b",
    base_url=base_url,
    temperature=0.2,
)

# ────────────────────────────────────────────────
#  AGENT: WTW Primary Spelling Inventory Assessor
# ────────────────────────────────────────────────

assessor = Agent(
    role="WTW Primary Spelling Inventory Assessor",
    goal="Accurately score a grade 2 student's Primary Spelling Inventory using official Words Their Way rules.",
    backstory="""You are an experienced Taiwanese grade 2 English teacher who knows the official WTW Primary Spelling Inventory feature guide inside out.
You carefully score:
- Words correct (/26)
- Feature points (/56) — consonants, short vowels, digraphs/blends, long vowels, r-controlled, diphthongs, etc.
- Total score (/82)
Then assign the correct stage (most grade 2 students are in Letter Name-Alphabetic or Within Word Pattern).
Finally, suggest the next 1–2 targeted spelling features with examples.""",
    llm=llm,
    verbose=True
    allow_delegation=False  # Keeps the agent focused on its own task
)

# ────────────────────────────────────────────────
#  TASK: Score one student's spellings
# ────────────────────────────────────────────────

task = Task(
    description="""Score this student's Primary Spelling Inventory responses.

Official 26 words (in order):
1. fan  2. pet  3. dig  4. rob  5. hope  6. wait  7. gum  8. sled  9. stick
10. shine  11. dream  12. blade  13. coach  14. fright  15. chewed  16. crawl
17. wishes  18. thorn  19. shouted  20. spoil  21. growl  22. third  23. camped
24. tries  25. clapping  26. riding

Student's spellings (word: their attempt):
{student_spellings}

Output in this exact format:
Words correct: X/26 (briefly list which ones were wrong)
Feature points: Y/56 (highlight the main missed features)
Total score: Z/82
Spelling stage: [exact stage name, e.g. Within Word Pattern - Early]
Next focus features: [1–2 specific patterns with examples, e.g. long vowels ai/ay/a-e, r-controlled ar/or]
Short explanation for parents/teachers (1–3 sentences)""",
    agent=assessor,
    expected_output="Structured WTW scoring report"
)

# ────────────────────────────────────────────────
#  CREATE & RUN THE CREW (just one agent for now)
# ────────────────────────────────────────────────

crew = Crew(
    agents=[assessor],
    tasks=[task],
    verbose=2   # detailed logs — change to 1 when it's working smoothly
)

# ────────────────────────────────────────────────
#  EXAMPLE STUDENT DATA — EDIT THIS WHEN YOU WANT TO TEST A REAL STUDENT
# ────────────────────────────────────────────────

example_student = """
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

# ────────────────────────────────────────────────
#  RUN THE SCRIPT
# ────────────────────────────────────────────────

if __name__ == "__main__":
    print("Running WTW Spelling Inventory Assessor...")
    result = crew.kickoff(inputs={"student_spellings": example_student})
    print("\n" + "="*50)
    print("FINAL WTW ASSESSMENT RESULT")
    print("="*50 + "\n")
    print(result)
