import requests
from config import OPENROUTER_API_KEY, MODELS

def ask_llm(messages: list, temperature: float = 0.7) -> str:
    for model in MODELS:
        try:
            r = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://dapoai.local",
                    "X-Title": "dapoAI",
                },
                json={"model": model, "messages": messages, "temperature": temperature},
                timeout=30,
            )
            r.raise_for_status() # Raise exception for non-2xx status codes
            return r.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            # Maybe print the exception or just fallback to the next model
            continue
    return "⚠️ Semua model lagi sibuk, coba lagi sebentar."
