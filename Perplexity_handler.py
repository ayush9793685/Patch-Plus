from openai import OpenAI
import logging
import json
import os

# Configure logging
logging.basicConfig(filename='chatbot.log', level=logging.INFO, 
                    format='%(asctime)s - %(levelname)s - %(message)s')

# Predefined Perplexity API Key (hardcoded for convenience; consider env var in production)
PERPLEXITY_API_KEY = ""#api key

# Module-level client (defined once on import)
_perplexity_client = None

def configure_perplexity():
    """Internal config - called on first use if not set."""
    global _perplexity_client
    if _perplexity_client is not None:
        return _perplexity_client  # Already configured
    
    try:
        _perplexity_client = OpenAI(api_key=PERPLEXITY_API_KEY, base_url="https://api.perplexity.ai")
        logging.info("Perplexity API configured successfully")
        return _perplexity_client
    except Exception as e:
        logging.error(f"Failed to configure Perplexity API: {str(e)}")
        raise

def query_perplexity(query):
    """Standalone query - auto-configures client if needed."""
    try:
        client = configure_perplexity()
        response = client.chat.completions.create(
            model="sonar",  # Valid Perplexity model
            messages=[
                {"role": "system", "content": "You are a helpful assistant that integrates web search results for accurate, concise answers."},
                {"role": "user", "content": query}
            ]
        )
        logging.info(f"Perplexity query successful for: {query[:50]}...")
        return response.choices[0].message.content
    except Exception as e:
        logging.error(f"Perplexity query failed: {str(e)}")
        return f"Error querying Perplexity: {str(e)}"

def query_and_parse_json_perplexity(prompt: str, temperature: float = 0.1) -> dict:
    """
    Standalone JSON query - auto-configures client if needed.
    """
    json_prompt = f"{prompt}\n\nRespond with valid JSON only, no additional text."
    # Note: Perplexity doesn't directly support temperature; simulate via prompt if needed
    response = query_perplexity(json_prompt)
    try:
        # Strip markdown if present
        cleaned = response.strip().strip('```json').strip('```').strip()
        parsed = json.loads(cleaned)
        logging.info(f"Perplexity JSON parse success for prompt: {prompt[:50]}...")
        return parsed
    except json.JSONDecodeError as e:
        logging.error(f"Perplexity JSON parse failed: {e}. Raw response: {response[:200]}...")
        return {"error": "Invalid JSON response", "raw": response}