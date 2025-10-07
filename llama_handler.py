import requests
import json
import logging

# Configure logging
logging.basicConfig(
    filename="chatbot.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# 🔑 Your OpenRouter API Key
OPENROUTER_KEY = "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"  # Replace with your key

# Endpoint for chat completions
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

def query_openrouter(prompt: str, model: str = "meta-llama/llama-3-8b-instruct", temperature: float = 0.7) -> str:
    """
    Sends a chat query to OpenRouter LLaMA API.
    """
    headers = {
        "Authorization": f"Bearer {OPENROUTER_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature
    }

    try:
        response = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=60)
        if response.status_code == 200:
            data = response.json()
            # OpenRouter chat responses are in data['choices'][0]['message']['content']
            answer = data["choices"][0]["message"]["content"]
            logging.info(f"OpenRouter query success: {prompt[:50]}...")
            return answer
        else:
            logging.error(f"OpenRouter API error {response.status_code}: {response.text}")
            return f"Error {response.status_code}: {response.text}"
    except Exception as e:
        logging.exception("Exception while querying OpenRouter API")
        return f"Exception: {str(e)}"
