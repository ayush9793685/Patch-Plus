import os
import sys
import subprocess
import re
import json

def run_code(file_path: str) -> tuple[bool, str]:
    """Run the Python file using subprocess and capture output/error."""
    try:
        result = subprocess.run([sys.executable, file_path], capture_output=True, text=True)
        if result.returncode == 0:
            print("Code ran successfully. No errors.")
            print("Output:\n", result.stdout)
            return True, ""
        else:
            error_output = result.stderr
            print("Error occurred during execution:")
            print(error_output)
            return False, error_output
    except Exception as e:
        print(f"Error running file: {str(e)}")
        return False, str(e)

def parse_error(error_output: str) -> tuple[str | None, int | None, str | None]:
    """Parse the error output to extract error type, line number, and message."""
    syntax_pattern = r'File ".*?", line (\d+).*?(SyntaxError: .*)'
    runtime_pattern = r'Traceback \(most recent call last\):.*?File ".*?", line (\d+), in (.*)\n\s+(.*)'

    syntax_match = re.search(syntax_pattern, error_output, re.DOTALL)
    if syntax_match:
        line_num = int(syntax_match.group(1))
        error_msg = syntax_match.group(2)
        return "SyntaxError", line_num, error_msg

    runtime_match = re.search(runtime_pattern, error_output, re.DOTALL | re.MULTILINE)
    if runtime_match:
        line_num = int(runtime_match.group(1))
        context = runtime_match.group(2)
        error_line = runtime_match.group(3).strip()
        error_type = error_output.splitlines()[-1]
        return error_type, line_num, f"In {context}: {error_line}"

    return None, None, None

def call_ast_generator(file_path: str, line_num: int, output_path: str) -> tuple[bool, str, str | None]:
    """Call ast_generator.py to generate AST and locate the error."""
    try:
        result = subprocess.run(
            [sys.executable, "AST_TREE.py", file_path, str(line_num), output_path],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            print("AST generation and error analysis successful.")
            print(result.stdout)
            # Extract problematic line and def block from output
            lines = result.stdout.splitlines()
            problematic_line = next((line for line in lines if line.startswith("Problematic line: ")), "Problematic line: Not found")
            def_block = "\n".join(line for line in lines if line.startswith("Enclosing def: ") or (line.startswith("    ") and "Enclosing def: " in lines))
            return True, problematic_line, def_block if def_block else None
        else:
            print("Error in AST generation:")
            print(result.stderr)
            return False, "AST generation failed", None
    except Exception as e:
        print(f"Error calling ast_generator.py: {str(e)}")
        return False, "AST generation failed", None

def main():
    if len(sys.argv) < 2:
        print("Usage: python error_runner.py <path_to_python_file>")
        sys.exit(1)

    file_path = sys.argv[1]
    if not os.path.isfile(file_path) or not file_path.endswith('.py'):
        print(f"Error: '{file_path}' is not a valid Python file.")
        sys.exit(1)

    output_path = os.path.join(os.path.dirname(file_path), "ast_output.json")
    
    success, error_output = run_code(file_path)
    if success:
        sys.exit(0)

    error_type, line_num, error_msg = parse_error(error_output)
    if not error_type or not line_num:
        print("Could not parse error details.")
        sys.exit(1)

    print(f"\nError Type: {error_type}")
    print(f"Error Message: {error_msg}")
    print(f"Line Number: {line_num}")

    success, problematic_line, def_block = call_ast_generator(file_path, line_num, output_path)
    if success:
        print(f"\n{problematic_line}")
        if def_block:
            print(f"\n{def_block}")
    else:
        print("Failed to analyze error with AST.")

if __name__ == "__main__":
    main()