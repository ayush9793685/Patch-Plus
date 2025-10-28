

import sys
import os
from enum import Enum

# Assuming run_code is in error.py; adjust path if needed
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from error import run_code, Language  # Import the function and enum

# Sample test files (good and bad examples for each language)
TEST_FILES = {
    Language.PYTHON: [
        ("good.py", 'print("Hello, World!")'),
        ("bad_syntax.py", 'print("Hello"  # Missing )'),
        ("bad_runtime.py", 'x = 1 / 0'),
    ],
    Language.C: [
        ("hello.c", '#include <stdio.h>\nint main() { printf("Hello, C!\\n"); return 0; }'),
        ("bad_c.c", '#include <stdio.h>\nint main() { printf("Hello"; return 0; }'),  # Syntax error: missing )
    ],
    Language.CPP: [
        ("hello.cpp", '#include <iostream>\nint main() { std::cout << "Hello, C++!" << std::endl; return 0; }'),
        ("bad_cpp.cpp", '#include <iostream>\nint main() { std::cout << "Hello"; return 0; }'),  # Syntax error: missing << std::endl;
    ],
    Language.JAVA: [
        ("Hello.java", 'public class Hello {\n  public static void main(String[] args) {\n    System.out.println("Hello, Java!");\n  }\n}'),
        ("BadJava.java", 'public class BadJava {\n  public static void main(String[] args) {\n    int x = 1 / 0;\n  }\n}'),  # Runtime: ArithmeticException
    ],
}

def create_test_file(filename: str, content: str):
    """Helper to create a test file if it doesn't exist."""
    if not os.path.exists(filename):
        with open(filename, 'w') as f:
            f.write(content)
        print(f"Created test file: {filename}")

def cleanup_files(filename: str, lang: Language):
    """Clean up test files and any generated artifacts (e.g., executables, .class)."""
    # Remove source
    if os.path.exists(filename):
        os.remove(filename)
    # Remove compiled outputs
    base_name = os.path.splitext(filename)[0]
    if lang in {Language.C, Language.CPP}:
        out_file = f"temp_{base_name}"  # Matches run_code's temp naming
        if os.path.exists(out_file):
            os.remove(out_file)
    elif lang == Language.JAVA:
        class_file = f"{base_name}.class"
        if os.path.exists(class_file):
            os.remove(class_file)

def run_tests():
    """Run tests for each language and file."""
    print("=== Testing run_code function ===\n")
    
    all_results = []
    for lang in TEST_FILES:
        print(f"\n--- Testing {lang.value.upper()} ---")
        lang_results = []
        for filename, content in TEST_FILES[lang]:
            create_test_file(filename, content)
            try:
                success, error_msg, line_num = run_code(filename, lang)
                status = "PASS" if success else "FAIL"
                msg_preview = error_msg[:50] + "..." if error_msg else ""
                result = f"{status} | {filename} | Line: {line_num or 'N/A'} | Msg: {msg_preview}"
                print(result)
                lang_results.append(result)
            except Exception as e:
                error_result = f"EXCEPTION | {filename} | Error: {str(e)}"
                print(error_result)
                lang_results.append(error_result)
            finally:
                cleanup_files(filename, lang)
        
        all_results.extend(lang_results)
        print(f"\n{lang.value.upper()} Summary: {sum(1 for r in lang_results if 'PASS' in r)} passes, {len(lang_results) - sum(1 for r in lang_results if 'PASS' in r)} fails/exceptions")
    
    print("\n=== All Tests Complete ===")
    return all_results

if __name__ == "__main__":
    run_tests()
    print("\nFull Results:")
    for result in run_tests():  # Re-run for printing (or cache if needed)
        print(result)