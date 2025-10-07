import os
import sys
import re
import json
import traceback
import copy  # Added for deepcopy to prevent dict mutation/duplication
from io import StringIO
from contextlib import redirect_stdout
from difflib import SequenceMatcher  # Added for line change calculation (proxy for ∆Lk)
from AST_TREE import ASTGenerator
from llama_handler import query_and_parse_json as query_llama_json
from claude_handler import query_and_parse_json_claude as query_claude_json
from gemini_handler import query_and_parse_json_gemini
from Perplexity_handler import query_and_parse_json_perplexity  # Standalone call

generator = ASTGenerator()

# No initial config; all handled on-the-fly in query_all_models
print("Models will be queried on-demand; config errors caught per-model.")

def run_code(file_path: str) -> tuple[bool, str, int | None]:
    """Run the Python file and capture output/error with line info."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            code = f.read()
        compile(code, file_path, 'exec')  # Check syntax first
        exec(code)  # Run if syntax OK
        print("Code ran successfully. No errors.")
        return True, "", None
    except SyntaxError as e:
        error_msg = str(e)
        line_num = e.lineno
        print("Error occurred during execution:")
        print(f"  File \"{file_path}\", line {line_num}")
        print(f"    {e.text.strip() if e.text else ''}")
        print(error_msg)
        return False, error_msg, line_num
    except Exception as e:
        tb = e.__traceback__  # Fixed: Use e.__traceback__ (preferred over sys.exc_info())
        tb_lines = traceback.format_tb(tb)
        error_msg = str(e)
        # Extract line from traceback
        line_match = re.search(r'line (\d+)', tb_lines[-1]) if tb_lines else None
        line_num = int(line_match.group(1)) if line_match else 1
        print("Error occurred during execution:")
        print(error_msg)
        return False, error_msg, line_num

def parse_error(error_output: str, line_num: int) -> tuple[str | None, str | None]:
    """Parse the error output to extract error type and message."""
    # Use provided line_num for accuracy
    error_type_match = re.search(r'^(.*?Error):', error_output, re.MULTILINE)
    error_type = error_type_match.group(1) if error_type_match else "Exception"
    return error_type, error_output.strip()

def call_ast_generator(file_path: str, line_num: int, output_path: str) -> tuple[bool, str, str | None]:
    """Call ASTGenerator directly and capture its printed output for context."""
    try:
        # Capture stdout from generate_ast
        output_capture = StringIO()
        with redirect_stdout(output_capture):
            success = generator.generate_ast(file_path, output_path, line_num)
        
        captured_output = output_capture.getvalue()
        if success:
            print("AST generation and error analysis successful.")
            print(captured_output)  # Re-print for user
            
            # Parse captured output
            lines = captured_output.splitlines()
            problematic_line = next((line.split(':', 1)[1].strip() for line in lines if line.startswith("Problematic line: ")), "Not found")
            def_lines = [line for line in lines if "Enclosing def:" in line or (line.strip().startswith("    ") and any("def" in l for l in lines))]
            def_block = "\n".join(def_lines).replace("Enclosing def: \n", "") if def_lines else None
            return True, problematic_line, def_block
        else:
            print("Error in AST generation.")
            print(captured_output)
            return False, "AST generation failed", None
    except Exception as e:
        print(f"Error calling ASTGenerator: {str(e)}")
        return False, "AST generation failed", None

def build_fix_prompt(error_type: str, error_msg: str, line_num: int, problematic_line: str, def_block: str | None, file_path: str) -> str:
    """Build structured prompt for multi-LLM fix."""
    with open(file_path, 'r', encoding='utf-8') as f:
        full_code = f.read()
    
    enclosing = f"Enclosing Function: {def_block}" if def_block else "Enclosing Function: None (top-level)"
    
    return f"""You are an expert Python code fixer in a DevSecOps tool. Analyze the following code snippet with an error and generate a minimal patch.

Code Snippet (full file content):
{full_code}

Error Details:
- Type: {error_type}
- Message: {error_msg}
- Location: Line {line_num}

AST Context:
- Problematic Line: {problematic_line}
{enclosing}

Task:
- Identify the issue based on the error and context.
- Propose a fix: Apply the smallest change to resolve the error without altering intended behavior.
- Ensure: No new vulnerabilities; compatible with Python 3.x; minimal impact.

Output Format (JSON only):
{{
  "original_code": "{problematic_line}",
  "fixed_code": "Your fixed line here",
  "explanation": "Brief reason (1-2 sentences)",
  "impact": "Minimal",
  "confidence": 0.95  // Float 0-1
}}"""

def query_all_models(prompt: str) -> dict:
    """Query all models and return responses (always attempts all, on-the-fly config if needed)."""
    responses = {}
    
    # LLaMA
    try:
        from llama_handler import query_and_parse_json as query_llama_json
        responses['llama'] = query_llama_json(prompt)
    except Exception as e:
        responses['llama'] = {"error": f"LLaMA query failed: {str(e)}"}
    
    # Claude
    try:
        from claude_handler import query_and_parse_json_claude as query_claude_json
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

def compute_consensus(responses: dict, problematic_line: str) -> dict:
    """Compute consensus using Patch Selection Equation (multi-objective optimization)."""
    # Deep copy to prevent mutation
    responses_copy = copy.deepcopy(responses)
    
    valid_responses = {k: v for k, v in responses_copy.items() if 'error' not in v and 'fixed_code' in v}
    if not valid_responses:
        return {"error": "No valid patch candidates", "responses": responses_copy, "original_code": problematic_line}
    
    # Extract candidates: ˆyk = fixed_code, x = problematic_line
    candidates = [(model, resp['fixed_code']) for model, resp in valid_responses.items()]
    
    # Compute ∆Lk for each (number of lines changed, using difflib ratio inverted for "change")
    delta_L = []
    for _, fixed_code in candidates:
        # Split lines for comparison
        orig_lines = problematic_line.splitlines()
        fix_lines = fixed_code.splitlines()
        # Use SequenceMatcher ratio (1 - similarity = change proxy); multiply by len for "lines changed"
        similarity = SequenceMatcher(None, problematic_line, fixed_code).ratio()
        change_proxy = (1 - similarity) * max(len(orig_lines), len(fix_lines))  # Normalized change
        delta_L.append(change_proxy)
    
    if not delta_L:
        return {"error": "No valid deltas", "responses": responses_copy, "original_code": problematic_line}
    
    max_delta_L = max(delta_L)
    
    # Compute S_func (functionality similarity proxy via difflib ratio [0,1])
    s_func_scores = [SequenceMatcher(None, problematic_line, fixed_code).ratio() for _, fixed_code in candidates]
    
    # Equation: arg max [ α * (1 - ∆Lk / max(∆L)) + β * S_func ]
    alpha = 0.6
    beta = 0.4
    scores = []
    for i, (model, fixed_code) in enumerate(candidates):
        normalized_change = 1 - (delta_L[i] / max_delta_L)
        score = alpha * normalized_change + beta * s_func_scores[i]
        scores.append((score, fixed_code, model))
    
    # Select best patch ˆy∗ = arg max score
    best_score, consensus_fix, best_model = max(scores)
    
    # Build consensus output
    consensus = {
        "original_code": problematic_line,
        "consensus_fixed_code": consensus_fix,
        "best_model": best_model,
        "selection_score": round(best_score, 3),
        "alpha_beta_weights": {"alpha": alpha, "beta": beta},
        "deltas_L": delta_L,
        "max_delta_L": round(max_delta_L, 3),
        "s_func_scores": [round(s, 3) for s in s_func_scores],
        "individual_responses": responses_copy
    }
    
    return consensus

def main():
    if len(sys.argv) < 2:
        print("Usage: python error_runner.py <path_to_python_file>")
        sys.exit(1)

    file_path = sys.argv[1]
    if not os.path.isfile(file_path) or not file_path.endswith('.py'):
        print(f"Error: '{file_path}' is not a valid Python file.")
        sys.exit(1)

    output_path = os.path.join(os.path.dirname(file_path), "ast_output.json")
    
    success, error_output, line_num = run_code(file_path)
    if success:
        sys.exit(0)

    error_type, error_msg = parse_error(error_output, line_num)
    if not error_type:
        print("Could not parse error details.")
        sys.exit(1)

    print(f"\nError Type: {error_type}")
    print(f"Error Message: {error_msg}")
    print(f"Line Number: {line_num}")

    ast_success, problematic_line, def_block = call_ast_generator(file_path, line_num, output_path)
    if ast_success:
        print(f"\nProblematic line: {problematic_line}")
        if def_block:
            print(f"\nEnclosing def: \n{def_block}")
        
        # Build and query all models
        prompt = build_fix_prompt(error_type, error_msg, line_num, problematic_line, def_block, file_path)
        print("\nQuerying multi-LLM for consensus fix...")
        responses = query_all_models(prompt)
        consensus = compute_consensus(responses, problematic_line)  # Pass problematic_line
        
        print("\nMulti-LLM Consensus (JSON):")
        print(json.dumps(consensus, indent=2))
        
        # Save
        fix_path = os.path.join(os.path.dirname(file_path), "multi_fix_output.json")
        with open(fix_path, 'w') as f:
            json.dump(consensus, f, indent=2)
        print(f"\nConsensus fix saved to: {fix_path}")
        
        # Apply preview (safe now)
        if "error" not in consensus:
            print(f"\nRecommended Patch: Replace '{consensus['original_code']}' with '{consensus['consensus_fixed_code']}'")
    else:
        print("Failed to analyze error with AST.")

if __name__ == "__main__":
    main()