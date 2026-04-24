"""
Model configuration for AI functions.
Handles model availability and fallback logic.
"""

import os
from typing import List, Dict, Optional

# Available models in order of preference
AVAILABLE_MODELS = [
    "gemini-1.5-flash-latest",
    "gemini-1.5-pro-latest", 
    "gemini-1.0-pro-latest",
    "gemini-1.0-flash-latest"
]

# Default model to use
DEFAULT_MODEL = "gemini-1.5-flash-latest"

def get_available_model() -> str:
    """
    Get the first available model from the preference list.
    Returns the model name or None if no models are available.
    """
    return DEFAULT_MODEL

def get_model_fallbacks() -> List[str]:
    """
    Get list of fallback models in order of preference.
    """
    return AVAILABLE_MODELS

def set_model_from_env() -> Optional[str]:
    """
    Allow environment override for model selection.
    """
    return os.getenv('GEMINI_MODEL', DEFAULT_MODEL)
