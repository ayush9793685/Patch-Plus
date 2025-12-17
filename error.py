import os
import sys
import re
import json
import traceback
import ast
import copy
import textwrap  
import parso  
import subprocess
from io import StringIO
from contextlib import redirect_stdout
from difflib import SequenceMatcher
from enum import Enum
from typing import Optional, Tuple, Dict, List, Any
from io import StringIO
from contextlib import redirect_stdout
from difflib import SequenceMatcher  
from AST_TREE import ASTGenerator
from logic_checker import LogicChecker  
from model_handler import query_all_models
generator = ASTGenerator()

# No initial config; all handled on-the-fly in query_all_models
print("Models will be queried on-demand; config errors caught per-model.")

# Python-specific imports (conditional)
try:
    from AST_TREE import ASTGenerator
    from logic_checker import LogicChecker
    PYTHON_SPECIFIC = True
except ImportError:
    PYTHON_SPECIFIC = False
    print("Warning: Python-specific modules not available; Python fixes limited.")

# Import test_run.py for testing run_code
try:
    from test_run import run_tests
    TEST_AVAILABLE = True
except ImportError:
    TEST_AVAILABLE = False
    print("Warning: test_run.py not found; skipping tests if requested.")

from model_handler import query_all_models

class Language(Enum):
    PYTHON = "python"
    C = "c"
    CPP = "cpp"
    JAVA = "java"


def detect_language(file_path: str):
    """Detect language from file extension."""
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".py":
        return Language.PYTHON
    elif ext == ".c":
        return Language.C
    elif ext in {".cpp", ".cxx", ".cc"}:
        return Language.CPP
    elif ext == ".java":
        return Language.JAVA
    else:
        raise ValueError(f"Unsupported file extension: {ext}")

def run_code(file_path: str, lang: Language = Language.PYTHON) -> Tuple[bool, str, Optional[int]]:
    """Run the code file for the given language and capture output/error with line info."""
    if not os.path.isfile(file_path):
        return False, f"File not found: {file_path}", None

    if lang == Language.PYTHON:
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
            tb = e.__traceback__
            tb_lines = traceback.format_tb(tb)
            error_msg = str(e)
            line_match = re.search(r'line (\d+)', tb_lines[-1]) if tb_lines else None
            line_num = int(line_match.group(1)) if line_match else 1
            print("Error occurred during execution:")
            print(error_msg)
            return False, error_msg, line_num
    elif lang in {Language.C, Language.CPP}:
        compiler = "gcc" if lang == Language.C else "g++"
        base_name = os.path.splitext(os.path.basename(file_path))[0]
        out_file = f"./temp_{base_name}"
        compile_cmd = [compiler, file_path, "-o", out_file]
        compile_result = subprocess.run(compile_cmd, capture_output=True, text=True, cwd=os.path.dirname(file_path))
        if compile_result.returncode != 0:
            error_output = compile_result.stderr
            line_match = re.search(r':(\d+):(\d+): (error|warning): (.*)', error_output, re.MULTILINE)
            line_num = int(line_match.group(1)) if line_match else 1
            error_msg = line_match.group(4) if line_match else error_output.strip()
            print("Compilation error:")
            print(error_output)
            if os.path.exists(out_file):
                os.remove(out_file)
            return False, error_msg, line_num
        run_result = subprocess.run([out_file], capture_output=True, text=True, cwd=os.path.dirname(file_path))
        os.remove(out_file)
        if run_result.returncode != 0:
            error_output = run_result.stderr
            line_match = re.search(r'line (\d+)', error_output)
            line_num = int(line_match.group(1)) if line_match else 1
            error_msg = error_output.strip()
            print("Runtime error:")
            print(error_output)
            return False, error_msg, line_num
        print("Code ran successfully. No errors.")
        if run_result.stdout.strip():
            print("Output:", run_result.stdout)
        return True, "", None
    elif lang == Language.JAVA:
        base_name = os.path.splitext(os.path.basename(file_path))[0]
        class_file = f"{base_name}.class"
        compile_cmd = ["javac", file_path]
        compile_result = subprocess.run(compile_cmd, capture_output=True, text=True, cwd=os.path.dirname(file_path))
        if compile_result.returncode != 0:
            error_output = compile_result.stderr
            line_match = re.search(r'(\d+): (error): (.*)', error_output, re.MULTILINE)
            line_num = int(line_match.group(1)) if line_match else 1
            error_msg = line_match.group(3) if line_match else error_output.strip()
            print("Compilation error:")
            print(error_output)
            if os.path.exists(class_file):
                os.remove(class_file)
            return False, error_msg, line_num
        run_result = subprocess.run(["java", base_name], capture_output=True, text=True, cwd=os.path.dirname(file_path))
        os.remove(class_file)
        if run_result.returncode != 0:
            error_output = run_result.stderr
            line_match = re.search(r'at .*?(\d+)', error_output)
            line_num = int(line_match.group(1)) if line_match else 1
            error_msg = error_output.strip()
            print("Runtime error:")
            print(error_output)
            return False, error_msg, line_num
        print("Code ran successfully. No errors.")
        if run_result.stdout.strip():
            print("Output:", run_result.stdout)
        return True, "", None
    else:
        return False, f"Unsupported language: {lang.value}", None


def parse_error(error_output: str, line_num: int) -> tuple[str | None, str | None]:
    """Parse the error output to extract error type and message."""
    # Use provided line_num for accuracy
    error_type_match = re.search(r'^(.*?Error):', error_output, re.MULTILINE)
    error_type = error_type_match.group(1) if error_type_match else "Exception"
    return error_type, error_output.strip()

def call_ast_generator(file_path: str, line_num: int) -> tuple[bool, str, str | None]:
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
            
            # Directly use get_code_context for reliable extraction
            problematic_line, def_block = generator.get_code_context(file_path, line_num)
            print(f"\nProblematic line: {problematic_line}")
            if def_block:
                print(f"\nEnclosing def: \n{def_block}")
            
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

def compute_consensus(responses: dict, problematic_line: str, exclude_model=None) -> dict:
    """Compute consensus using Patch Selection Equation (multi-objective optimization)."""
    # Deep copy to prevent mutation
    responses_copy = copy.deepcopy(responses)
    
    valid_responses = {k: v for k, v in responses_copy.items() if 'error' not in v}
    if exclude_model:
        valid_responses = {k: v for k, v in valid_responses.items() if k != exclude_model}
    if not valid_responses:
        return {"error": "No valid responses", "responses": responses_copy, "original_code": problematic_line}
    
    # Extract candidates: ˆyk = fixed_code, x = problematic_line
    candidates = [(model, resp['fixed_code']) for model, resp in valid_responses.items() if 'fixed_code' in resp and resp['fixed_code'] != problematic_line]
    if not candidates:
        candidates = [('no_fix', problematic_line)]  # Fallback
    
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
        if max_delta_L == 0:
            # All changes are zero (identical fixes); no change penalty
            normalized_change = 1.0
        else:
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

def create_structure(original_file: str, structure_path: str = 'structure.json'):
    """Call code_structure.py to create the nested JSON structure."""
    cmd = ['python', 'code_structure.py', original_file, '--output', structure_path]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error creating structure: {result.stderr}")
        sys.exit(1)
    print(f"Structure created: {structure_path}")

def save_structure(structure: list, structure_path: str):
    """Save the nested structure to JSON (inlined from code_structure.py)."""
    with open(structure_path, 'w', encoding='utf-8') as f:
        json.dump(structure, f, indent=2, default=str)
    print(f"Updated structure saved to: {structure_path}")

def apply_fix_via_structure(structure_path: str, line_num: int, consensus_fixed_code: str, temp_file: str, target_indent: int = None):
    """Load structure, replace line, save updated structure, rebuild and write to temp_file."""
    # Load structure
    with open(structure_path, 'r') as f:
        structure = json.load(f)
    
    # Replace
    structure = replace_line_in_structure(structure, line_num, consensus_fixed_code, target_indent)
    
    # FIXED: Save the updated structure back to JSON
    save_structure(structure, structure_path)
    
    # Rebuild and save
    code = rebuild_code_from_structure(structure)
    with open(temp_file, 'w') as f:
        f.write(code)
    print(f"Applied structure fix to line {line_num} in {temp_file}")

# Note: For brevity, inlining replace_line_in_structure and rebuild_code_from_structure here
# (copy from code_structure.py; in production, import them)

def replace_line_in_structure(structure: list, line_num: int, fixed_text: str, target_indent: int = None) -> list:
    def recurse(nodes):
        for node in nodes:
            if node['line_num'] == line_num:
                dedented = fixed_text.lstrip()
                if target_indent is not None:
                    node['indent'] = target_indent
                    node['text'] = ' ' * target_indent + dedented.rstrip('\n')
                else:
                    node['text'] = fixed_text.rstrip('\n')
                return True
            if recurse(node.get('children', [])):
                return True
        return False
    recurse(structure)
    return structure

def rebuild_code_from_structure(structure: list) -> str:
    lines = []
    def flatten(nodes):
        for node in nodes:
            lines.append(node['text'] + '\n')
            flatten(node.get('children', []))
    flatten(structure)
    return ''.join(lines).rstrip('\n')

def main():
    if len(sys.argv) < 2:
        print("Usage: python error.py <path_to_source_file> [--test]")
        sys.exit(1)

    # Check for --test flag
    run_tests_flag = "--test" in sys.argv
    if run_tests_flag:
        if not TEST_AVAILABLE:
            print("Error: test_run.py not found. Cannot run tests.")
            sys.exit(1)
        print("Running tests from test_run.py...")
        test_results = run_tests()
        print("\nTest Results:")
        for result in test_results:
            print(result)
        if any("FAIL" in result or "EXCEPTION" in result for result in test_results):
            print("Some tests failed. Aborting main execution.")
            sys.exit(1)
        print("All tests passed. Proceeding with main execution.")

    original_file = sys.argv[1] if not run_tests_flag else sys.argv[2]
    if not os.path.isfile(original_file):
        print(f"Error: '{original_file}' is not a valid file.")
        sys.exit(1)

    lang = detect_language(original_file)
    print(f"Detected language: {lang.value}")

    abs_original_file = os.path.abspath(original_file)
    print(f"Absolute path: {abs_original_file}")

    structure_path = os.path.join(os.path.dirname(abs_original_file), 'structure.json')
    create_structure(abs_original_file, structure_path)

    ext = '.' + lang.value if lang != Language.PYTHON else '.py'
    temp_file = os.path.join(os.path.dirname(abs_original_file), "temp_fixed" + ext)
    fixed_file = os.path.join(os.path.dirname(abs_original_file), "fixed_" + os.path.basename(original_file))
    max_iterations = 20
    iteration = 0
    has_issues = True
    error_history = []

    # Initial temp from structure
    with open(structure_path, 'r') as f:
        structure = json.load(f)
    initial_code = rebuild_code_from_structure(structure)
    with open(temp_file, 'w') as f:
        f.write(initial_code)
    print(f"Initial temp file created at: {temp_file}")

    print(f"path: {temp_file}")
    while has_issues and iteration < max_iterations:
        iteration += 1
        print(f"\nIteration {iteration}: Checking {temp_file}")

        success, error_output, line_num = run_code(temp_file, lang)
        if not success:
            error_type, error_msg = parse_error(error_output, line_num)
            if not error_type:
                print("Could not parse error details.")
                break

            print(f"\nError Type: {error_type}")
            print(f"Error Message: {error_msg}")
            print(f"Line Number: {line_num}")

            context_success, problematic_line, enclosing = call_ast_generator(temp_file, line_num)
            if context_success:
                prompt = build_fix_prompt(error_type, error_msg, line_num, problematic_line, enclosing, temp_file)
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
                consensus = compute_consensus(responses, problematic_line, exclude_model)
                
                print("\nMulti-LLM Consensus for Error Fix (JSON):")
                print(json.dumps(consensus, indent=2))
                
                if "consensus_fixed_code" in consensus:
                    consensus_fixed_code = consensus['consensus_fixed_code']
                    target_indent = None
                    if lang == Language.PYTHON and enclosing:
                        if problematic_line.strip().startswith('def '):
                            target_indent = 0
                            print("Detected def header fix; forcing top-level indent (0).")
                        else:
                            first_line = enclosing.splitlines()[0]
                            base = len(first_line) - len(first_line.lstrip())
                            target_indent = base + 4
                            print(f"Body line fix; target indent: {target_indent} (base {base} +4).")
                    
                    apply_fix_via_structure(structure_path, line_num, consensus_fixed_code, temp_file, target_indent)
                    
                    if lang == Language.PYTHON and any(keyword in error_msg.lower() for keyword in ['indent', 'expected an indented block', 'return outside function']):
                        auto_fix_indent(temp_file, line_num, enclosing, consensus_fixed_code)

                    error_key = f"{error_msg} | {problematic_line}"
                    error_history.append((error_key, line_num, problematic_line, consensus.get('best_model', 'unknown')))
                    if len(error_history) > 2:
                        error_history = error_history[-2:]
                else:
                    print("No fix generated; breaking loop.")
                    break
            else:
                print("Failed to analyze error with context.")
                break
        else:
            print("\nNo runtime errors; starting logical check...")
            logic_result = LogicChecker.full_logic_check(temp_file)
            
            print("\nLogic Check Results (JSON):")
            print(json.dumps(logic_result, indent=2))
            
            has_logic_issues = len(logic_result.get('flagged_nodes', [])) > 0 or len(logic_result.get('re_check_issues', [])) > 0
            if has_logic_issues:
                fixed_code = logic_result.get('fixed_code', '')
                if fixed_code:
                    with open(temp_file, 'w') as f:
                        f.write(fixed_code)
                    print(f"Applied logic fixes to {temp_file}")
                else:
                    print("No fixed_code from logic check; skipping.")
            else:
                has_issues = False
                print("No logic issues found; final code ready.")

    with open(temp_file, 'r') as f:
        final_code = f.read()
    with open(fixed_file, 'w') as f:
        f.write(final_code)
    print(f"\nFinal fixed code saved to: {fixed_file}")
    
    os.remove(temp_file)

if __name__ == "__main__":
    main()