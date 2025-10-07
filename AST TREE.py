import os
import sys
import json
import ast
import argparse
from typing import Optional, Dict
import importlib.util

# Language-specific modules and parsers
LANGUAGE_PARSERS = {
    'python': ('ast', ast.parse),
    'javascript': ('esprima', None),  # Will be set dynamically
    'java': ('javalang', None),      # Will be set dynamically
    'c': ('pycparser', None),        # Will be set dynamically
    'cpp': ('pycparser', None),      # Will be set dynamically
    'xml': ('xml.etree.ElementTree', None)  # Will be set dynamically
}

class ASTGenerator:
    def __init__(self):
        self.language = None
        self.parser = None

    def detect_language(self, file_path: str) -> str:
        """Detect the programming language based on file extension."""
        extension = os.path.splitext(file_path)[1].lower()
        if extension == '.py':
            return 'python'
        elif extension in ('.js', '.jsx'):
            return 'javascript'
        elif extension == '.java':
            return 'java'
        elif extension == '.c':
            return 'c'
        elif extension == '.cpp':
            return 'cpp'
        elif extension == '.xml':
            return 'xml'
        return ''

    def load_parser(self, language: str) -> bool:
        """Load the appropriate parser for the detected language."""
        if language not in LANGUAGE_PARSERS:
            return False
        
        module_name, parser_func = LANGUAGE_PARSERS[language]
        
        if language == 'python':
            self.parser = parser_func
            return True
            
        # Dynamic import for other languages
        try:
            if language == 'javascript':
                import esprima
                self.parser = esprima.parse
            elif language == 'java':
                import javalang
                self.parser = javalang.parse.parse
            elif language in ('c', 'cpp'):
                from pycparser import parse_file
                self.parser = parse_file
            elif language == 'xml':
                import xml.etree.ElementTree as ET
                self.parser = ET.parse
            return True
        except ImportError:
            print(f"Error: Required module '{module_name}' not installed.")
            return False

    def node_to_dict(self, node) -> Dict:
        """Convert an AST node to a dictionary for JSON serialization."""
        if isinstance(node, (str, int, float, bool, type(None))):
            return node
        
        result = {'type': type(node).__name__}
        
        if hasattr(node, '__dict__'):
            for key, value in node.__dict__.items():
                if isinstance(value, list):
                    result[key] = [self.node_to_dict(item) for item in value]
                elif isinstance(value, (str, int, float, bool, type(None))):
                    result[key] = value
                else:
                    result[key] = self.node_to_dict(value)
        
        # Special handling for specific language nodes
        if self.language == 'python' and hasattr(node, '_fields'):
            for field in node._fields:
                value = getattr(node, field)
                if isinstance(value, list):
                    result[field] = [self.node_to_dict(item) for item in value]
                else:
                    result[field] = self.node_to_dict(value)
                    
        elif self.language == 'javascript' and hasattr(node, 'type'):
            result.update({k: self.node_to_dict(v) for k, v in node.__dict__.items()})
            
        elif self.language == 'java' and hasattr(node, 'attrs'):
            for attr in node.attrs:
                value = getattr(node, attr)
                result[attr] = [self.node_to_dict(item) for item in value] if isinstance(value, list) else self.node_to_dict(value)
                
        elif self.language in ('c', 'cpp') and hasattr(node, 'children'):
            result['children'] = [self.node_to_dict(child) for child in node.children()]
            
        elif self.language == 'xml' and hasattr(node, 'tag'):
            result['tag'] = node.tag
            result['attrib'] = node.attrib
            result['children'] = [self.node_to_dict(child) for child in node]
            
        return result

    def generate_ast(self, file_path: str, output_path: str) -> bool:
        """Generate AST for the given file and save it to the output path."""
        if not os.path.exists(file_path):
            print(f"Error: File '{file_path}' does not exist.")
            return False

        self.language = self.detect_language(file_path)
        if not self.language:
            print(f"Error: Unsupported file type for '{file_path}'.")
            return False

        if not self.load_parser(self.language):
            print(f"Error: Could not load parser for language '{self.language}'.")
            return False

        try:
            # Read file content for most languages
            with open(file_path, 'r', encoding='utf-8') as file:
                content = file.read()

            # Generate AST based on language
            if self.language == 'python':
                tree = self.parser(content)
            elif self.language == 'javascript':
                tree = self.parser(content)
            elif self.language == 'java':
                tree = self.parser(content)
            elif self.language in ('c', 'cpp'):
                tree = self.parser(file_path)
            elif self.language == 'xml':
                tree = self.parser(file_path)
            else:
                print(f"Error: No parser available for language '{self.language}'.")
                return False

            # Convert AST to dictionary
            ast_dict = self.node_to_dict(tree)

            # Ensure output directory exists
            os.makedirs(os.path.dirname(output_path), exist_ok=True)

            # Save AST to JSON file
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(ast_dict, f, indent=2)
            
            print(f"AST successfully generated and saved to '{output_path}'.")
            return True

        except Exception as e:
            print(f"Error generating AST: {str(e)}")
            return False

def main():

    input_file="C:/Users/ayush/Downloads/buggy_python_code.py"
    output_file="C:/Users/ayush/OneDrive/Documents/Project Integrated chatbot/codes"
    generator = ASTGenerator()
    success = generator.generate_ast(input_file,output_file)
    
    if not success:
        sys.exit(1)

if __name__ == "__main__":
    main()