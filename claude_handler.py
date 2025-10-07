import requests
import json
import logging
import os

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

def query_claude(prompt: str, model: str = "anthropic/claude-3.5-sonnet", temperature: float = 0.7, max_tokens: int = 1000) -> str:
    """
    Sends a chat query to OpenRouter Claude API.
    """
    headers = {
        "Authorization": f"Bearer {OPENROUTER_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://your-app.com",  # Optional: For leaderboard credit
        "X-Title": "PatchPulse"  # Optional: Your app name
    }

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens  # Added: Prevents response truncation
    }

    try:
        response = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=120)
        if response.status_code == 200:
            data = response.json()
            answer = data["choices"][0]["message"]["content"]
            logging.info(f"Claude query success: {prompt[:50]}...")
            return answer
        else:
            logging.error(f"Claude API error {response.status_code}: {response.text}")
            return f"Error {response.status_code}: {response.text}"
    except Exception as e:
        logging.exception("Exception while querying Claude API")
        return f"Exception: {str(e)}"

def query_and_parse_json_claude(prompt: str, model: str = "anthropic/claude-3.5-sonnet", temperature: float = 0.1, max_tokens: int = 500) -> dict:
    """
    Queries Claude and parses the response as JSON for structured fixes.
    Adds instruction for JSON-only output.
    """
    json_prompt = f"{prompt}\n\nRespond with valid JSON only, no additional text."
    response = query_claude(json_prompt, model, temperature, max_tokens)
    try:
        # Strip markdown if present
        cleaned = response.strip().strip('```json').strip('```').strip()
        parsed = json.loads(cleaned)
        logging.info(f"Claude JSON parse success for prompt: {prompt[:50]}...")
        return parsed
    except json.JSONDecodeError as e:
        logging.error(f"Claude JSON parse failed: {e}. Raw response: {response[:200]}...")
        return {"error": "Invalid JSON response", "raw": response}