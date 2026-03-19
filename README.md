{\rtf1\ansi\ansicpg1252\cocoartf2867
\cocoatextscaling0\cocoaplatform0{\fonttbl\f0\fswiss\fcharset0 Helvetica;}
{\colortbl;\red255\green255\blue255;}
{\*\expandedcolortbl;;}
\paperw11900\paperh16840\margl1440\margr1440\vieww11520\viewh8400\viewkind0
\pard\tx720\tx1440\tx2160\tx2880\tx3600\tx4320\tx5040\tx5760\tx6480\tx7200\tx7920\tx8640\pardirnatural\partightenfactor0

\f0\fs24 \cf0 # WTW Spelling Inventory Assessor \uc0\u55356 \u57166 \
\
An automated agent-based tool to score the **Words Their Way (WTW) Primary Spelling Inventory**. This project uses **CrewAI** and **Ollama** to analyze student spelling attempts and provide feature-based scoring.\
\
---\
\
## \uc0\u55357 \u56960  Quick Start (Work Computer Setup)\
\
Follow these steps to get the project running on a new machine:\
\
### 1. Prerequisites\
* **Python 3.10+** installed.\
* **Tailscale** installed and logged in (to access the NAS).\
* **Ollama** running on your NAS with `qwen2.5:7b` or `llama3.2:3b` pulled.\
\
### 2. Installation\
Clone the repository and set up a virtual environment:\
\
```bash\
# Clone the repo\
git clone [https://github.com/gurukomodo/wtw-spelling-coach.git](https://github.com/gurukomodo/wtw-spelling-coach.git)\
cd wtw-spelling-coach\
\
# Create a virtual environment\
python3 -m venv .venv\
\
# Activate the environment\
# On Mac/Linux:\
source .venv/bin/activate\
# On Windows:\
# .venv\\Scripts\\activate\
\
# Install dependencies\
pip install -r requirements.txt}