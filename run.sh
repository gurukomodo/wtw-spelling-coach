#!/bin/bash
# Runs the UnBoxEd spelling coach app with dotenvx decrypting .env on the fly.
# Usage: ./run.sh
set -e
dotenvx run -- streamlit run app.py
