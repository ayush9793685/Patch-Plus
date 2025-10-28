import os
import sys
import re
import json
import traceback
import ast
import copy
import subprocess
from io import StringIO
from contextlib import redirect_stdout
from difflib import SequenceMatcher
from enum import Enum
from typing import Optional, Tuple, Dict, List, Any

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

def detect_language(file_path: str) -> Language:
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

# [Other functions unchanged: parse_error, get_code_context, call_ast_generator, build_fix_prompt, compute_consensus, etc.]

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
    create_structure(abs_original_file, structure_path, lang)

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
            error_type, error_msg = parse_error(error_output, line_num, lang)
            if not error_type:
                print("Could not parse error details.")
                break

            print(f"\nError Type: {error_type}")
            print(f"Error Message: {error_msg}")
            print(f"Line Number: {line_num}")

            context_success, problematic_line, enclosing = call_ast_generator(temp_file, line_num, lang)
            if context_success:
                prompt = build_fix_prompt(error_type, error_msg, line_num, problematic_line, enclosing, temp_file, lang)
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
                    
                    apply_fix_via_structure(structure_path, line_num, consensus_fixed_code, temp_file, target_indent, lang)
                    
                    if lang == Language.PYTHON and any(keyword in error_msg.lower() for keyword in ['indent', 'expected an indented block', 'return outside function']):
                        auto_fix_indent(temp_file, line_num, enclosing, consensus_fixed_code, lang)

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
            logic_result = perform_logic_check(temp_file, lang)
            
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