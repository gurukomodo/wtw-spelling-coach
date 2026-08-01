#!/bin/zsh
set -e

# Activate the local virtual environment
source .venv/bin/activate

# Inject decrypted secrets and start Streamlit
dotenvx run -- streamlit run app.py
