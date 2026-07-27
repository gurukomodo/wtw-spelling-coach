import os
import time
from litellm import completion

# Central Registry for all models across the application
MODEL_REGISTRY = {
    "vision": [
        # --- Primary / Fast Tier ---
        {"model": "gemini/gemini-3.5-flash", "api_key": os.getenv("GEMINI_API_KEY")},
        {"model": "gemini/gemini-3.1-flash-lite", "api_key": os.getenv("GEMINI_API_KEY")},
        {"model": "gemini/gemini-2.5-flash", "api_key": os.getenv("GEMINI_API_KEY")},
        {"model": "gemini/gemini-2.5-pro", "api_key": os.getenv("GEMINI_API_KEY")},        
        {"model": "gemini/gemini-2.0-flash", "api_key": os.getenv("GEMINI_API_KEY")},
        {"model": "groq/qwen/qwen3.6-27b", "api_key": os.getenv("GROQ_API_KEY")},
        {"model": "mistral/pixtral-12b-2409", "api_key": os.getenv("MISTRAL_API_KEY")},
        {"model": "mistral/mistral-medium-3.5", "api_key": os.getenv("MISTRAL_API_KEY")},
        {
            "model": "openai/Qwen/Qwen2.5-VL-72B-Instruct",
            "api_key": os.getenv("OVH_API_KEY"),
            "api_base": "https://oai.endpoints.kepler.ai.cloud.ovh.net/v1",
        },
        {"model": "openrouter/qwen/qwen-2.5-vl-72b-instruct:free", "api_key": os.getenv("OPENROUTER_API_KEY")},
        {"model": "openrouter/google/gemini-2.0-flash-exp:free", "api_key": os.getenv("OPENROUTER_API_KEY")},
        {"model": "huggingface/meta-llama/Llama-3.2-11B-Vision-Instruct", "api_key": os.getenv("HF_API_KEY")},
        {"model": "huggingface/Qwen/Qwen2.5-VL-7B-Instruct", "api_key": os.getenv("HF_API_KEY")},

        # --- Secondary Fallbacks (NVIDIA & GitHub) ---
        {
            "model": "nvidia_nim/meta/llama-3.2-11b-vision-instruct",
            "api_key": os.getenv("NVIDIA_API_KEY"),
        },
        {
            "model": "openai/gpt-4o-mini",
            "api_key": os.getenv("GITHUB_TOKEN"),
            "api_base": "https://models.inference.ai.azure.com",
        },
        {
            "model": "openai/gpt-4o",
            "api_key": os.getenv("GITHUB_TOKEN"),
            "api_base": "https://models.inference.ai.azure.com",
        },
    ],
    "text": [
        # --- Primary / Fast Tier ---
        {"model": "gemini/gemini-3.5-flash", "api_key": os.getenv("GEMINI_API_KEY")},
        {"model": "gemini/gemini-3.1-flash-lite", "api_key": os.getenv("GEMINI_API_KEY")},
        {"model": "gemini/gemini-2.5-flash", "api_key": os.getenv("GEMINI_API_KEY")},
        {"model": "gemini/gemini-2.5-pro", "api_key": os.getenv("GEMINI_API_KEY")},
        {"model": "groq/llama-3.3-70b-versatile", "api_key": os.getenv("GROQ_API_KEY")},
        {"model": "groq/llama-3.1-8b-instant", "api_key": os.getenv("GROQ_API_KEY")},
        {"model": "groq/qwen/qwen3.6-27b", "api_key": os.getenv("GROQ_API_KEY")},
        {"model": "mistral/mistral-medium-3.5", "api_key": os.getenv("MISTRAL_API_KEY")},

        # --- Secondary Fallbacks (NVIDIA & GitHub) ---
        {
            "model": "nvidia_nim/nvidia/nemotron-3-super-120b-a12b",
            "api_key": os.getenv("NVIDIA_API_KEY"),
        },        
        {
            "model": "nvidia_nim/nvidia/nemotron-3-nano-30b-a3b",
            "api_key": os.getenv("NVIDIA_API_KEY"),
        },
        {
            "model": "nvidia_nim/meta/llama-3.3-70b-instruct",
            "api_key": os.getenv("NVIDIA_API_KEY"),
        },
        {
            "model": "openai/gpt-4.1",
            "api_key": os.getenv("GITHUB_TOKEN"),
            "api_base": "https://models.inference.ai.azure.com",
        },
        {
            "model": "openai/gpt-4.1-mini",
            "api_key": os.getenv("GITHUB_TOKEN"),
            "api_base": "https://models.inference.ai.azure.com",
        },
        {
            "model": "openai/gpt-4o-mini",
            "api_key": os.getenv("GITHUB_TOKEN"),
            "api_base": "https://models.inference.ai.azure.com",
        },
        {
            "model": "openai/meta-llama-3.1-8b-instruct",
            "api_key": os.getenv("GITHUB_TOKEN"),
            "api_base": "https://models.inference.ai.azure.com",
        },
    ],
}


def run_model_chain(
    task_type: str, 
    messages: list, 
    temperature: float = 0.3, 
    return_metadata: bool = False
):
    """
    Executes completion across candidate models registered for a specific task.
    Includes step-by-step debug logging to trace missing keys, execution time, 
    specific error reasons, and the winning provider.
    """
    models = MODEL_REGISTRY.get(task_type, [])
    if not models:
        print(f"\n❌ [MODEL MANAGER ERROR] Task type '{task_type}' not found in registry. Valid keys: {list(MODEL_REGISTRY.keys())}")
        return None

    print(f"\n🚀 [MODEL MANAGER] Starting chain for task: '{task_type.upper()}' ({len(models)} models queued)")

    attempts = []

    for index, config in enumerate(models, start=1):
        model_name = config.get("model")
        api_key = config.get("api_key")
        api_base = config.get("api_base")

        # Skip models whose API keys aren't set in .env
        if not api_key:
            print(f"  ⏭️  [{index}/{len(models)}] Skipping '{model_name}': Missing API key in environment.")
            attempts.append({"model": model_name, "status": "SKIPPED", "reason": "Missing API Key"})
            continue

        endpoint_label = f" ({api_base})" if api_base else ""
        print(f"  ⏳ [{index}/{len(models)}] Trying '{model_name}'{endpoint_label}...", end="", flush=True)

        start_time = time.time()
        try:
            call_params = {
                "model": model_name,
                "api_key": api_key,
                "messages": messages,
                "temperature": temperature,
            }
            if api_base:
                call_params["api_base"] = api_base

            res = completion(**call_params)
            elapsed = round(time.time() - start_time, 2)

            content = res.choices[0].message.content
            print(f" ✅ SUCCESS ({elapsed}s)")
            print(f"🎯 [MODEL MANAGER] Response generated by: '{model_name}'\n")

            if return_metadata:
                return {
                    "content": content,
                    "winning_model": model_name,
                    "elapsed_seconds": elapsed,
                    "attempts": attempts,
                }
            return content

        except Exception as e:
            elapsed = round(time.time() - start_time, 2)
            error_msg = str(e)

            # Categorize common API failures cleanly
            if "429" in error_msg:
                reason = "Rate Limit Exceeded (429)"
            elif "404" in error_msg:
                reason = "Model Not Found / Invalid Name (404)"
            elif "401" in error_msg or "403" in error_msg:
                reason = "Authentication Failure (401/403)"
            else:
                reason = error_msg.split("\n")[0][:70]  # Truncate raw exception to 70 chars

            print(f" ❌ FAILED ({elapsed}s) -> Reason: {reason}")
            attempts.append({"model": model_name, "status": "FAILED", "duration": elapsed, "reason": reason})

    print(f"🚨 [MODEL MANAGER FATAL] All models failed for task '{task_type}'.\n")
    return None