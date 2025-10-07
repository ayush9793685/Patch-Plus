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
OPENROUTER_KEY = ""  # Replace with your key

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
        response = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=120)
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

def query_and_parse_json(prompt: str, model: str = "meta-llama/llama-3-8b-instruct", temperature: float = 0.1) -> dict:
    """
    Queries LLaMA and parses the response as JSON for structured fixes.
    Adds instruction for JSON-only output.
    """
    json_prompt = f"{prompt}\n\nRespond with valid JSON only, no additional text."
    response = query_openrouter(json_prompt, model, temperature)
    try:
        # Strip markdown if present
        cleaned = response.strip().strip('```json').strip('```').strip()
        parsed = json.loads(cleaned)
        logging.info(f"JSON parse success for prompt: {prompt[:50]}...")
        return parsed
    except json.JSONDecodeError as e:
        logging.error(f"JSON parse failed: {e}. Raw response: {response[:200]}...")
        return {"error": "Invalid JSON response", "raw": response}