import copy
from llama_handler import query_and_parse_json as query_llama_json
from claude_handler import query_and_parse_json_claude as query_claude_json
from gemini_handler import query_and_parse_json_gemini
from Perplexity_handler import query_and_parse_json_perplexity


def query_all_models(prompt: str) -> dict:
    """Query all models and return responses (always attempts all, on-the-fly config if needed)."""
    responses = {}
    
    # LLaMA
    try:
        responses['llama'] = query_llama_json(prompt)
    except Exception as e:
        responses['llama'] = {"error": f"LLaMA query failed: {str(e)}"}
    
    # Claude
    try:
        responses['claude'] = query_claude_json(prompt)
    except Exception as e:
        responses['claude'] = {"error": f"Claude query failed: {str(e)}"}
    
    # Gemini - standalone call (auto-configures)
    try:
        responses['gemini'] = query_and_parse_json_gemini(prompt)
    except Exception as e:
        responses['gemini'] = {"error": f"Gemini query failed: {str(e)}"}
    
    # Perplexity - standalone call (auto-configures)
    try:
        responses['perplexity'] = query_and_parse_json_perplexity(prompt)
    except Exception as e:
        responses['perplexity'] = {"error": f"Perplexity query failed: {str(e)}"}
    
    # Validate: Check for duplicates
    if len(set(responses.keys())) != len(responses):
        print("Warning: Duplicate keys detected in responses; sanitizing...")
        responses = dict(copy.deepcopy(responses))
    
    return responses