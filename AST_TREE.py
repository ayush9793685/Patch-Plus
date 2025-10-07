import os
import sys
import json
import ast
import argparse
from typing import Optional, Dict, List

class ASTGenerator:
    def __init__(self):
        self.language = None
        self.parser = None 
        self.lines = None

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
        LANGUAGE_PARSERS = {
            'python': ('ast', ast.parse),
            'javascript': ('esprima', None),
            'java': ('javalang', None),
            'c': ('pycparser', None),
            'cpp': ('pycparser', None),
            'xml': ('xml.etree.ElementTree', None)
        }
        if language not in LANGUAGE_PARSERS:
            return False
        
        module_name, parser_func = LANGUAGE_PARSERS[language]
        
        if language == 'python':
            self.parser = parser_func
            return True
            
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
        
        if self.language == 'python':
            if hasattr(node, '_fields'):
                for field in node._fields:
                    value = getattr(node, field)
                    if isinstance(value, list):
                        result[field] = [self.node_to_dict(item) for item in value]
                    else:
                        result[field] = self.node_to_dict(value)
            elif hasattr(node, 'type') and hasattr(node, 'children'):
                result['type'] = node.type
                result['children'] = [self.node_to_dict(child) for child in node.children if child]
                result['start_pos'] = node.start_pos
                result['end_pos'] = node.end_pos if hasattr(node, 'end_pos') else None
        
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

    def find_node_at_line(self, tree, target_line: int) -> Optional[Dict]:
        """Find the AST node at the specified line number."""
        def visit(node, target_line: int) -> Optional[Dict]:
            if hasattr(node, 'lineno') and node.lineno <= target_line <= (getattr(node, 'end_lineno', node.lineno)):
                node_dict = self.node_to_dict(node)
                node_dict['line_range'] = (node.lineno, getattr(node, 'end_lineno', node.lineno))
                return node_dict
            elif hasattr(node, 'start_pos') and node.start_pos[0] <= target_line <= (node.end_pos[0] if hasattr(node, 'end_pos') else target_line):
                node_dict = self.node_to_dict(node)
                node_dict['line_range'] = (node.start_pos[0], node.end_pos[0] if hasattr(node, 'end_pos') else node.start_pos[0])
                return node_dict
            for child in getattr(node, 'children', ast.iter_child_nodes(node)):
                found = visit(child, target_line)
                if found:
                    return found
            return None
        return visit(tree, target_line)

    def get_code_context(self, file_path: str, line_num: int) -> tuple[str, str | None]:
        """Get the problematic line and enclosing def statement."""
        try:
            with open(file_path, 'r', encoding='utf-8') as file:
                self.lines = file.read().splitlines()
        except Exception as e:
            print(f"Error reading file: {str(e)}")
            return "Error reading file", None

        if not self.lines or line_num < 1 or line_num > len(self.lines):
            return "Invalid line number.", None

        problematic_line = self.lines[line_num - 1].strip()
        current_def = None
        def_start = None
        def_block = []
        current_indent = None

        for i in range(line_num - 1, -1, -1):
            line = self.lines[i].strip()
            if line.startswith('def '):
                current_def = line
                def_start = i + 1
                current_indent = len(self.lines[i]) - len(self.lines[i].lstrip())
                def_block = [self.lines[i]]
                break

        if def_start:
            for i in range(def_start, line_num):
                line_indent = len(self.lines[i]) - len(self.lines[i].lstrip())
                if line_indent > current_indent:
                    def_block.append(self.lines[i])
            full_def = '\n'.join(def_block)
        else:
            full_def = None

        return problematic_line, full_def

    def generate_ast(self, file_path: str, output_path: str, error_line: int) -> bool:
        """Generate AST for the given file and analyze the error line."""
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
            with open(file_path, 'r', encoding='utf-8') as file:
                content = file.read()
                self.lines = content.splitlines()

            errors = []
            tree = None
            if self.language == 'python':
                try:
                    tree = self.parser(content)
                except SyntaxError as e:
                    print(f"SyntaxError from ast: {str(e)} at line {e.lineno}")
                    try:
                        import parso
                        grammar = parso.load_grammar()
                        tree = grammar.parse(content)
                        errors = list(grammar.iter_errors(tree))
                        for error in errors:
                            print(f"Parso error: {error.message} at position {error.start_pos}")
                    except ImportError:
                        print("parso not installed. Install with 'pip install parso' to enable partial parsing.")
                        return False
            else:
                if self.language == 'javascript':
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

            ast_dict = self.node_to_dict(tree)
            ast_dict['errors'] = [{'message': e.message, 'start_pos': e.start_pos} for e in errors] if errors else []

            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(ast_dict, f, indent=2)
            
            print(f"AST (partial if errors) successfully generated and saved to '{output_path}'.")

            # Analyze error line
            problematic_line, full_def = self.get_code_context(file_path, error_line)
            print(f"Problematic line: {problematic_line}")
            if full_def:
                print(f"Enclosing def: \n{full_def}")

            if tree:
                node = self.find_node_at_line(tree, error_line)
                if node:
                    print(f"AST Node at line {error_line}:")
                    print(f"Node Type: {node['type']}")
                    print(f"Line Range: {node['line_range']}")
                    if 'value' in node:
                        print(f"Node Value: {node['value']}")
                    elif 'name' in node:
                        print(f"Node Name: {node['name']}")

            if errors:
                print("Additional syntax errors detected:")
                for error in errors:
                    print(f"Error: {error['message']} at position {error['start_pos']}")

            return True

        except Exception as e:
            print(f"Error generating AST: {str(e)}")
            return False

def main():
    parser = argparse.ArgumentParser(description="Generate AST and analyze error line.")
    parser.add_argument('file_path', help="Path to the source file")
    parser.add_argument('error_line', type=int, help="Line number of the error")
    parser.add_argument('output_path', help="Path to save the AST JSON file")
    
    args = parser.parse_args()
    
    generator = ASTGenerator()
    success = generator.generate_ast(args.file_path, args.output_path, args.error_line)
    
    if not success:
        sys.exit(1)

if __name__ == "__main__":
    main()