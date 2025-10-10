import os
import sys
import re
import json
import traceback
import ast
import copy  # Added for deepcopy to prevent dict mutation/duplication
from io import StringIO
from contextlib import redirect_stdout
from difflib import SequenceMatcher  # Added for line change calculation (proxy for ∆Lk)
from AST_TREE import ASTGenerator
from logic_checker import LogicChecker  # Import for logical checking after error fixes
from model_handler import query_all_models
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

def call_ast_generator(file_path: str, line_num: int) -> tuple[bool, str]:
    output_path = os.path.join(os.path.dirname(file_path), "ast_output.json")

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
def compute_consensus(responses: dict, problematic_line: str,exclude_model) -> dict:
    responses_copy = copy.deepcopy(responses)
    
    valid_responses = {k: v for k, v in responses_copy.items() if 'error' not in v}

    if exclude_model:
        valid_responses = {k: v for k, v in valid_responses.items() if k != exclude_model}
    """Compute consensus using Patch Selection Equation (multi-objective optimization)."""
    # Deep copy to prevent mutation
    responses_copy = copy.deepcopy(responses)
    
    valid_responses = {k: v for k, v in responses_copy.items() if 'error' not in v}
    if not valid_responses:
        return {"error": "No valid responses", "responses": responses_copy, "original_code": problematic_line}
    
    # Extract candidates: ˆyk = fixed_code, x = problematic_line
    candidates = [(model, resp['fixed_code']) for model, resp in valid_responses.items() if 'fixed_code' in resp and resp['fixed_code'] != problematic_line]
    if not candidates:
        candidates = [( 'no_fix', problematic_line )]  # Fallback
    
    # Compute ∆Lk for each (lines changed proxy)
    delta_L = []
    orig_lines = problematic_line.splitlines()
    for _, fixed_code in candidates:
        fix_lines = fixed_code.splitlines()
        similarity = SequenceMatcher(None, problematic_line, fixed_code).ratio()
        change_proxy = (1 - similarity) * max(len(orig_lines), len(fix_lines))
        delta_L.append(change_proxy)
    
    max_delta_L = max(delta_L) if delta_L else 1
    
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


def auto_fix_indent(temp_file: str, line_num: int, def_block: str | None, consensus_fixed_code: str) -> bool:
    """Auto-shift indentation on problematic line using AST context, test until parses."""
    if not def_block:
        print("No def_block for indent fix; skipping.")
        return False
    
    # Get base indent from def_block (first indented line's spaces)
    lines = def_block.splitlines()
    base_indent = 0
    for line in lines[1:]:  # Skip 'def line'
        if line.strip():
            base_indent = len(line) - len(line.lstrip())
            break
    
    print(f"Base indent from def: {base_indent} spaces")
    
    # Try indent variants (+0, +4, +8, -4)
    variants = [0, 4, 8, -4]
    for shift in variants:
        new_indent = max(0, base_indent + shift)
        indented_fix = ' ' * new_indent + consensus_fixed_code.rstrip() + '\n'
        
        # Test: Replace in temp, parse with ast.parse
        with open(temp_file, 'r') as f:
            full_lines = f.readlines()
        full_lines[line_num - 1] = indented_fix
        test_code = ''.join(full_lines)
        
        try:
            ast.parse(test_code)  # Quick syntax check
            # If parses, apply and return success
            with open(temp_file, 'w') as f:
                f.write(test_code)
            print(f"Auto-fixed indent with {new_indent} spaces (shift +{shift}).")
            return True
        except SyntaxError:
            continue  # Try next shift
    
    print("Auto-indent failed after tries; keeping original.")
    return False



def main():
    if len(sys.argv) < 2:
        print("Usage: python error_runner.py <path_to_python_file>")
        sys.exit(1)

    original_file = sys.argv[1]
    if not os.path.isfile(original_file) or not original_file.endswith('.py'):
        print(f"Error: '{original_file}' is not a valid Python file.")
        sys.exit(1)

    # Fixed: Use absolute path for temp_file
    temp_file = os.path.join(os.path.abspath(os.path.dirname(original_file)), "temp_fixed.py")
    fixed_file = "fixed_" + os.path.basename(original_file)
    max_iterations = 20  # Increased for longer loops
    iteration = 0
    has_issues = True  # Start assuming issues
    error_history = []  # Track last 2 errors for repetition detection

    # Copy original to temp for looping
    with open(original_file, 'r') as f:
        code = f.read()
    with open(temp_file, 'w') as f:
        f.write(code)

    logic_checker = LogicChecker()
    print("path:", os.path.abspath(temp_file))
    while has_issues and iteration < max_iterations:
        iteration += 1
        print(f"\nIteration {iteration}: Checking {temp_file}")

        # Run and fix errors
        success, error_output, line_num = run_code(temp_file)
        if not success:
            error_type, error_msg = parse_error(error_output, line_num)
            if not error_type:
                print("Could not parse error details.")
                break

            print(f"\nError Type: {error_type}")
            print(f"Error Message: {error_msg}")
            print(f"Line Number: {line_num}")

            ast_success, problematic_line, def_block = call_ast_generator(temp_file, line_num)
            if ast_success:
                print(f"\nProblematic line: {problematic_line}")
                if def_block:
                    print(f"\nEnclosing def: \n{def_block}")
                
                # Build and query all models for error fix
                prompt = build_fix_prompt(error_type, error_msg, line_num, problematic_line, def_block, temp_file)
                print("\nQuerying multi-LLM for error fix...")
                responses = query_all_models(prompt)
                exclude_model = None
                if len(error_history) >= 1:
                    curr_key = f"{error_msg} | {problematic_line}"
                    for hist_key, _, _, hist_model in error_history:
                        if SequenceMatcher(None, curr_key, hist_key).ratio() > 0.9:
                            exclude_model = hist_model
                            print(f"Repeating error detected; excluding model: {exclude_model}")
                            break
                consensus = compute_consensus(responses, problematic_line,exclude_model)
                
                print("\nMulti-LLM Consensus for Error Fix (JSON):")
                print(json.dumps(consensus, indent=2))
                
                # Apply the best patch to the problematic line
                if "consensus_fixed_code" in consensus:
                    with open(temp_file, 'r') as f:
                        lines = f.readlines()
                    # Assume problematic_line is on line_num; replace it
                    lines[line_num - 1] = consensus['consensus_fixed_code'] + '\n'
                    with open(temp_file, 'w') as f:
                        f.write(''.join(lines))
                    print(f"Applied error fix to {temp_file}")
                    
                    # New: Auto-fix indentation if IndentationError
                    if 'indent' in error_msg.lower() or 'return outside function' in error_msg.lower():
                        if auto_fix_indent(temp_file, line_num, def_block, consensus['consensus_fixed_code']):
                            print("Indentation auto-fixed.")

                    # Add to history for repetition check
                    error_key = f"{error_msg} | {problematic_line}"
                    error_history.append((error_key, line_num, problematic_line, consensus.get('best_model', 'unknown')))
                    if len(error_history) > 2:
                        error_history = error_history[-2:]  # Keep last 2
                else:
                    print("No fix generated; breaking loop.")
                    break
            else:
                print("Failed to analyze error with AST.")
                break
        else:
            # No errors; move to logic check
            print("\nNo runtime errors; starting logical check...")
            logic_result = logic_checker.full_logic_check(temp_file)
            
            print("\nLogic Check Results (JSON):")
            print(json.dumps(logic_result, indent=2))
            
            # Check if logic issues remain (re_check_issues not empty or flagged_nodes > 0)
            has_logic_issues = len(logic_result.get('flagged_nodes', [])) > 0 or len(logic_result.get('re_check_issues', [])) > 0
            if has_logic_issues:
                # Apply logic fixes
                fixed_code = logic_result.get('fixed_code', temp_file)
                with open(temp_file, 'w') as f:
                    f.write(fixed_code)
                print(f"Applied logic fixes to {temp_file}")
            else:
                has_issues = False  # No more issues; exit loop
                print("No logic issues found; final code ready.")

    # Save final fixed code
    with open(temp_file, 'r') as f:
        final_code = f.read()
    with open(fixed_file, 'w') as f:
        f.write(final_code)
    print(f"\nFinal fixed code saved to: {fixed_file}")
    
    # Clean up temp
    os.remove(temp_file)


if __name__ == "__main__":
    main()

