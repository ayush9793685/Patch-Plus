import google.generativeai as genai
import logging
import json
import os

# Configure logging
logging.basicConfig(filename='chatbot.log', level=logging.INFO, 
                    format='%(asctime)s - %(levelname)s - %(message)s')

# Predefined Gemini API Key (hardcoded for convenience; consider env var in production)
GEMINI_API_KEY = ""#api key

# Module-level model (defined once on import)
_gemini_model = None

def configure_gemini():
    """Internal config - called on first use if not set."""
    global _gemini_model
    if _gemini_model is not None:
        return _gemini_model  # Already configured
    
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        _gemini_model = genai.GenerativeModel('gemini-2.5-pro')  # Updated to Gemini 2.5 Pro (stable as of October 2025)
        logging.info("Gemini API configured successfully")
        return _gemini_model
    except Exception as e:
        logging.error(f"Failed to configure Gemini API: {str(e)}")
        raise

def query_gemini(query):
    """Standalone query - auto-configures model if needed."""
    try:
        model = configure_gemini()
        response = model.generate_content(query)
        logging.info(f"Gemini query successful for: {query[:50]}...")
        return response.text
    except Exception as e:
        logging.error(f"Gemini query failed: {str(e)}")
        return f"Error querying Gemini: {str(e)}"

def query_and_parse_json_gemini(prompt: str, temperature: float = 0.1) -> dict:
    """
    Standalone JSON query - auto-configures model if needed.
    """
    json_prompt = f"{prompt}\n\nRespond with valid JSON only, no additional text."
    response = query_gemini(json_prompt)
    try:
        # Strip markdown if present
        cleaned = response.strip().strip('```json').strip('```').strip()
        parsed = json.loads(cleaned)
        logging.info(f"Gemini JSON parse success for prompt: {prompt[:50]}...")
        return parsed
    except json.JSONDecodeError as e:
        logging.error(f"Gemini JSON parse failed: {e}. Raw response: {response[:200]}...")
        return {"error": "Invalid JSON response", "raw": response}