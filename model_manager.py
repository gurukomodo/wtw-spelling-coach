import os
from litellm import completion

# Central Registry for all models across the application
MODEL_REGISTRY = {
   vision_models = [
       {"model": "gemini/gemini-2.0-flash", "api_key": os.getenv("GEMINI_API_KEY")},
       {"model": "groq/qwen/qwen3.6-27b", "api_key": os.getenv("GROQ_API_KEY")},
       {"model": "mistral/pixtral-12b-2409", "api_key": os.getenv("MISTRAL_API_KEY")},
       {"model": "mistral/mistral-medium-3.5", "api_key": os.getenv("MISTRAL_API_KEY")},
       {
           "model": "openai/Qwen/Qwen2.5-VL-72B-Instruct",
           "api_key": os.getenv("OVH_API_KEY"),
           "api_base": "https://oai.endpoints.kepler.ai.cloud.ovh.net/v1"
       },
       {"model": "openrouter/qwen/qwen-2.5-vl-72b-instruct:free", "api_key": os.getenv("OPENROUTER_API_KEY")},
       {"model": "openrouter/google/gemini-2.0-flash-exp:free", "api_key": os.getenv("OPENROUTER_API_KEY")},
       {"model": "huggingface/meta-llama/Llama-3.2-11B-Vision-Instruct", "api_key": os.getenv("HF_API_KEY")},
       {"model": "huggingface/Qwen/Qwen2.5-VL-7B-Instruct", "api_key": os.getenv("HF_API_KEY")},
   ]
,
    "text_analysis": [
        {"model": "gemini/gemini-2.0-flash", "api_key": os.getenv("GEMINI_API_KEY")},
        {"model": "groq/llama-3.3-70b-versatile", "api_key": os.getenv("GROQ_API_KEY")},
        {"model": "groq/qwen/qwen3.6-27b", "api_key": os.getenv("GROQ_API_KEY")},
        {"model": "mistral/mistral-medium-3.5", "api_key": os.getenv("MISTRAL_API_KEY")},
    ],
}

def run_model_chain(task_type: str, messages: list, temperature: float = 0.3):
    """
    Executes completion across candidate models registered for a specific task.
    Automatically fails over if a model throws a 429 quota or 404 error.
    """
    models = MODEL_REGISTRY.get(task_type, [])
    if not models:
        print(f"[Model Manager Error] Task type '{task_type}' not found in registry.")
        return None

    for config in models:
        model_name = config.get("model")
        api_key = config.get("api_key")

        if not api_key:
            continue

        try:
            call_params = {
                "model": model_name,
                "api_key": api_key,
                "messages": messages,
                "temperature": temperature,
            }
            if "api_base" in config:
                call_params["api_base"] = config["api_base"]

            res = completion(**call_params)
            return res.choices[0].message.content

        except Exception as e:
            print(f"[{task_type.upper()} Warning] Model {model_name} failed -> {e}")

    return None