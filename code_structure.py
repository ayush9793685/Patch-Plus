# code_structure.py
import os
import json
import argparse
import re
from typing import List, Dict, Any, Union

def split_single_line_to_logical_lines(text: str) -> List[str]:
    """
    Split a single-line code (with spaces for indents) into logical lines based on statements.
    Detects indents (multiples of 4 spaces), colons (:), and common statement ends.
    """
    # Replace multiple spaces with indent markers, then split on logical boundaries
    # Simple heuristic: split after :, =, ), ], }, and ensure indent prefixes
    parts = re.split(r'(\s{4,}|\s*:|\s*=\s*|\s*\)\s*|\s*\]\s*|\s*\}\s*)', text)
    lines = []
    current_line = ''
    current_indent = 0
    
    for part in parts:
        if re.match(r'^\s{4,}$', part):  # Indent block
            current_indent = len(part)
            if current_line.strip():
                lines.append(' ' * current_indent + current_line.strip())
                current_line = ''
        elif ':' in part or '=' in part or ')' in part or ']' in part or '}' in part:
            # Likely end of statement
            current_line += part
            if current_line.strip():
                lines.append(' ' * current_indent + current_line.strip())
                current_line = ''
        else:
            current_line += part
    
    if current_line.strip():
        lines.append(' ' * current_indent + current_line.strip())
    
    # Clean up and add \n
    formatted_lines = [line.rstrip() + '\n' for line in lines if line.strip()]
    return formatted_lines

def parse_to_structure(lines: List[str]) -> List[Dict[str, Any]]:
    """
    Parse lines into a nested structure based on indentation.
    Builds a tree where each node is a line, children are subsequent higher-indented lines (block bodies/siblings handled correctly).
    Uses stack to track parent nodes.
    Handles single-line input by splitting first.
    """
    if len(lines) == 1 and '\n' not in lines[0]:  # Single line without \n
        lines = split_single_line_to_logical_lines(lines[0])
    
    root = []
    stack: List[Dict[str, Any]] = []
    for line_num, line in enumerate(lines, 1):
        stripped = line.rstrip('\n').strip()
        if not stripped:  # Skip empty lines
            continue
        indent = len(line) - len(line.lstrip())
        
        # Pop stack until find parent with strictly less indent
        while stack and stack[-1]['indent'] >= indent:
            stack.pop()
        
        # Create node
        node: Dict[str, Any] = {
            'line_num': line_num,
            'indent': indent,
            'text': line.rstrip('\n'),  # Preserve without trailing \n
            'level': len(stack),  # Depth based on stack size
            'children': []
        }
        
        # Append to current parent (root or stack[-1])
        if stack:
            stack[-1]['children'].append(node)
        else:
            root.append(node)
        
        # Push current node to stack
        stack.append(node)
    
    return root

def save_structure(structure: List[Dict[str, Any]], json_path: str):
    """Save the nested structure to JSON."""
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(structure, f, indent=2, default=str)

def load_structure(json_path: str) -> List[Dict[str, Any]]:
    """Load the nested structure from JSON."""
    with open(json_path, 'r', encoding='utf-8') as f:
        return json.load(f)

def replace_line_in_structure(structure: List[Dict[str, Any]], line_num: int, fixed_text: str, target_indent: int = None) -> List[Dict[str, Any]]:
    """
    Recursively find and replace the node with matching line_num.
    Optionally adjust indent (for auto-fix).
    Returns updated structure.
    """
    def recurse(nodes: List[Dict[str, Any]]) -> bool:
        for node in nodes:
            if node['line_num'] == line_num:
                # Replace text (dedent first, then re-indent if specified)
                dedented = fixed_text.lstrip()
                if target_indent is not None:
                    node['indent'] = target_indent
                    node['text'] = ' ' * target_indent + dedented.rstrip('\n')
                else:
                    node['text'] = fixed_text.rstrip('\n')  # Use as-is, no trailing \n
                return True
            if recurse(node.get('children', [])):
                return True
        return False

    recurse(structure)
    return structure

def rebuild_code_from_structure(structure: List[Dict[str, Any]]) -> str:
    """Flatten the nested structure back to code lines, ensuring \n after each."""
    lines = []

    def flatten(nodes: List[Dict[str, Any]]):
        for node in nodes:
            lines.append(node['text'] + '\n')
            flatten(node.get('children', []))

    flatten(structure)
    return ''.join(lines).rstrip('\n')  # Remove trailing \n if any

def main():
    parser = argparse.ArgumentParser(description="Parse code to nested structure JSON.")
    parser.add_argument('file_path', help="Path to the source code file")
    parser.add_argument('--output', default='structure.json', help="Path to save structure JSON")
    parser.add_argument('--replace', nargs=3, metavar=('line_num', 'fixed_text', 'output_code'), help="Replace line and rebuild code")
    
    args = parser.parse_args()
    
    with open(args.file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Handle if read as single line
    if not '\n' in content:
        lines = [content]
    else:
        lines = content.splitlines(keepends=True)
    
    structure = parse_to_structure(lines)
    save_structure(structure, args.output)
    print(f"Structure saved to {args.output}")
    
    if args.replace:
        line_num = int(args.replace[0])
        fixed_text = args.replace[1]
        output_code = args.replace[2]
        structure = load_structure(args.output)
        structure = replace_line_in_structure(structure, line_num, fixed_text)
        save_structure(structure, args.output)  # Optional: re-save
        code = rebuild_code_from_structure(structure)
        with open(output_code, 'w', encoding='utf-8') as f:
            f.write(code)
        print(f"Replaced line {line_num} and saved rebuilt code to {output_code}")

if __name__ == "__main__":
    main()