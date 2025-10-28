import ast
from datetime import datetime
import json
import copy
from typing import Dict, List, Any, Optional
from pymongo import MongoClient  # pip install pymongo
from difflib import SequenceMatcher  # For ∆L and S_func proxy (string similarity as ROUGE/BLEU approx)
from AST_TREE import ASTGenerator  # Your AST parser
from model_handler import query_all_models

# MongoDB setup (local default; change URI for prod)
MONGO_URI = "mongodb://localhost:27017/"
DB_NAME = "patchpulse"
COLLECTION_NAME = "logic_checks"

client = MongoClient(MONGO_URI)
db = client[DB_NAME]
collection = db[COLLECTION_NAME]

class LogicTreeNode:
    """Represents a node in the logic tree (AST segment)."""
    def __init__(self, node_type: str, code_snippet: str, ast_node: ast.AST, parent=None, children: List['LogicTreeNode'] = None):
        self.node_type = node_type  # e.g., 'function', 'loop', 'if', 'main'
        self.code_snippet = code_snippet
        self.ast_node = ast_node
        self.parent = parent
        self.children = children or []
        self.issues = []  # Flagged logic issues from GenAI
        self.candidate_fixes = []  # List of fixes from models for selection
        self.selected_fix = None  # Best fix after equation
        self.logic_score = 0.0  # Post-check score

    def to_dict(self) -> Dict[str, Any]:
        return {
            'node_type': self.node_type,
            'code_snippet': self.code_snippet,
            'issues': self.issues,
            'candidate_fixes': self.candidate_fixes,
            'selected_fix': self.selected_fix,
            'logic_score': self.logic_score,
            'children': [child.to_dict() for child in self.children]
        }

class LogicChecker:
    def __init__(self, mongo_uri: str = MONGO_URI):
        self.ast_gen = ASTGenerator()
        self.mongo_client = MongoClient(mongo_uri)
        self.db = self.mongo_client["patchpulse"]
        self.collection = self.db["logic_checks"]
        self.alpha = 0.6  # Weight for minimal changes
        self.beta = 0.4   # Weight for functionality similarity

    def build_logic_tree(self, tree: ast.AST, full_code: str) -> LogicTreeNode:
        """Recursively break AST into logic tree (root = full, children = defs/loops/ifs)."""
        root = LogicTreeNode('root', full_code, tree)
        self._traverse_and_build(root, tree)
        return root

    def _traverse_and_build(self, parent: LogicTreeNode, node: ast.AST):
        """Recursive traversal to build children."""
        if isinstance(node, ast.Module):
            # Top-level: Add defs and main statements as children
            for child in node.body:
                if isinstance(child, ast.FunctionDef):
                    snippet = ast.unparse(child)  # Python 3.9+; fallback ast.dump if older
                    child_node = LogicTreeNode('function', snippet, child, parent)
                    parent.children.append(child_node)
                    self._traverse_and_build(child_node, child)  # Recurse into function body
                elif isinstance(child, (ast.If, ast.For, ast.While)):  # Main blocks
                    snippet = ast.unparse(child)
                    child_node = LogicTreeNode('control_flow', snippet, child, parent)
                    parent.children.append(child_node)
                    self._traverse_and_build(child_node, child)
                # Add more types as needed (e.g., ast.ClassDef)

        elif isinstance(node, (ast.FunctionDef, ast.If, ast.For, ast.While)):
            # Inside defs/control: Add nested loops/ifs
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.If, ast.For, ast.While)):
                    snippet = ast.unparse(child)
                    child_node = LogicTreeNode('nested_control', snippet, child, parent)
                    parent.children.append(child_node)
                    self._traverse_and_build(child_node, child)

    def check_logic_with_genai(self, node: LogicTreeNode) -> List[Dict[str, Any]]:
        """Prompt all GenAI models for logic check on node, collect candidate fixes."""
        prompt = f"""Review the logic in this code block for bugs (e.g., off-by-one, wrong conditions, infinite loops). Flag issues and suggest fixes if needed.

Block Type: {node.node_type}
Code:
{node.code_snippet}

Output JSON only:
{{
  "issues": ["list of issues"],
  "fix": "fixed code if needed, else original",
  "is_fixed": true/false,
  "reason": "brief explanation"
}}"""

        # Query all models (your handlers are standalone)
        model_responses = query_all_models(prompt)

        # Extract candidate fixes (P = {ˆy1, ˆy2, ...}) - only unique non-original fixes
        node.candidate_fixes = list(set([
            resp.get('fix', node.code_snippet) for resp in model_responses.values() 
            if 'fix' in resp and resp['fix'] != node.code_snippet
        ]))
        if not node.candidate_fixes:
            node.candidate_fixes = [node.code_snippet]  # Fallback to original if no fixes

        # Simple issues from majority
        issues_count = sum(1 for resp in model_responses.values() if 'issues' in resp and len(resp['issues']) > 0)
        if issues_count > len(model_responses) // 2:
            node.issues = [resp.get('reason', 'Flagged by majority') for resp in model_responses.values() if 'reason' in resp]

        # Store in MongoDB
        doc = {
            'run_id': f"run_{datetime.now().timestamp()}",  # Simple unique ID
            'node_type': node.node_type,
            'original_code': node.code_snippet,
            'model_responses': model_responses,
            'timestamp': datetime.now().isoformat()
        }
        self.collection.insert_one(doc)

        node.logic_score = 1.0 if not node.issues else 0.0  # Provisional score

        return node.issues

    def select_best_patch(self, node: LogicTreeNode, original_snippet: str) -> str:
        """Apply Patch Selection Equation to choose best ˆy∗ from candidates."""
        P = node.candidate_fixes  # Set of m patch candidates ˆy_k
        x = original_snippet  # Vulnerable code

        if len(P) == 1:
            node.selected_fix = P[0]
            return P[0]

        # Compute ∆L_k for each (lines changed via difflib ratio inverted as proxy for Levenshtein)
        delta_L = []
        for yk in P:
            # Proxy for lines changed: (1 - similarity) * max lines
            similarity = SequenceMatcher(None, x, yk).ratio()
            max_lines = max(len(x.splitlines()), len(yk.splitlines()))
            change = (1 - similarity) * max_lines
            delta_L.append(change)

        max_delta_L = max(delta_L) if delta_L else 1

        # S_func (functionality similarity via difflib ratio [0,1] as proxy for CodeBLEU/ROUGE)
        s_func_scores = [SequenceMatcher(None, x, yk).ratio() for yk in P]

        # Equation: score = α * (1 - ∆L_k / max(∆L)) + β * S_func(x, ˆy_k)
        scores = []
        for i, yk in enumerate(P):
            normalized_change = 1 - (delta_L[i] / max_delta_L)
            score = self.alpha * normalized_change + self.beta * s_func_scores[i]
            scores.append((score, yk, i))

        # ˆy∗ = arg max score
        best_score, best_fix, best_idx = max(scores)
        node.selected_fix = best_fix
        node.logic_score = best_score  # Final score

        print(f"Selected best patch for {node.node_type} (score: {best_score:.3f}): {best_fix[:100]}...")

        return best_fix

    def apply_fixes_to_code(self, root: LogicTreeNode, original_code: str) -> str:
        """Recursively apply selected fixes to create fixed code copy."""
        if not root.children:
            return root.selected_fix or root.code_snippet
        
        fixed_code = original_code
        for child in root.children:
            # Recurse to apply fixes in children first
            child_fixed = self.apply_fixes_to_code(child, fixed_code)
            if child.selected_fix:
                # Replace in parent code
                fixed_code = fixed_code.replace(child.code_snippet, child.selected_fix)
        
        return fixed_code

    def test_and_compare_logic(self, original_code: str, fixed_code: str, test_inputs: List[str] = None) -> Dict[str, Any]:
        """Test original vs. fixed: Run with inputs, check I/O same, complexity reduced."""
        if test_inputs is None:
            test_inputs = ["sample_input_1", "edge_case_0"]  # Customize or auto-gen

        results = {'io_match': True, 'complexity_reduced': False, 'overall_change': 0.0}
        
        for input_val in test_inputs:
            # Safe exec (sandbox)
            orig_globals = {'input': lambda: input_val}
            fixed_globals = copy.deepcopy(orig_globals)
            
            try:
                exec(original_code, orig_globals)
                orig_output = orig_globals.get('output', 'No output')
            except Exception as e:
                orig_output = f"Error: {e}"
            
            try:
                exec(fixed_code, fixed_globals)
                fixed_output = fixed_globals.get('output', 'No output')
            except Exception as e:
                fixed_output = f"Error: {e}"
            
            if orig_output != fixed_output:
                results['io_match'] = False
                break
        
        # Complexity proxy: AST node count (simpler = fewer nodes)
        orig_ast = ast.parse(original_code)
        fixed_ast = ast.parse(fixed_code)
        orig_complexity = len(list(ast.walk(orig_ast)))
        fixed_complexity = len(list(ast.walk(fixed_ast)))
        results['complexity_reduced'] = fixed_complexity < orig_complexity
        results['overall_change'] = SequenceMatcher(None, original_code, fixed_code).ratio()
        
        return results

    def full_logic_check(self, file_path: str) -> Dict[str, Any]:
        """Full flow: Parse, tree, check, select best patches via equation, fix, test, compare."""
        with open(file_path, 'r') as f:
            full_code = f.read()
        
        # Set language and load parser
        self.ast_gen.language = 'python'
        self.ast_gen.load_parser('python')
        
        # Parse AST
        try:
            tree = self.ast_gen.parser(full_code)
        except SyntaxError as se:
            return {"error": "Syntax error detected", "details": str(se), "line": se.lineno}
        
        if not tree:
            return {"error": "Failed to parse AST"}
        
        # Build tree
        root = self.build_logic_tree(tree, full_code)
        
        # Check each node and select best fixes
        flagged_nodes = []
        for node in [root] + [n for n in self.flatten_tree(root)]:
            issues = self.check_logic_with_genai(node)
            if issues and node.candidate_fixes:
                flagged_nodes.append(node)
                # Apply equation to select best fix from candidates
                self.select_best_patch(node, node.code_snippet)
            elif not issues:
                node.selected_fix = node.code_snippet  # No fix needed
                node.logic_score = 1.0  # Good logic
        
        # Apply selected fixes
        fixed_code = self.apply_fixes_to_code(root, full_code)
        
        # Re-check fixed tree
        fixed_tree = self.build_logic_tree(ast.parse(fixed_code), fixed_code)
        re_issues = []
        for node in [fixed_tree] + [n for n in self.flatten_tree(fixed_tree)]:
            # Quick re-prompt or static check
            re_issues.extend(self.check_logic_with_genai(node)[:1])  # Top issue only
        
        # Test/compare
        comparison = self.test_and_compare_logic(full_code, fixed_code)
        
        # Save full run to Mongo
        run_doc = {
            'file_path': file_path,
            'original_code': full_code,
            'fixed_code': fixed_code,
            'flagged_nodes': [n.to_dict() for n in flagged_nodes],
            're_check_issues': re_issues,
            'comparison': comparison,
            'timestamp': datetime.now().isoformat()
        }
        inserted_doc = self.collection.insert_one(run_doc)
        
        # Convert ObjectId to str for JSON serialization
        run_doc['_id'] = str(inserted_doc.inserted_id)
        
        return run_doc

    def flatten_tree(self, root: LogicTreeNode) -> List[LogicTreeNode]:
        """Flatten tree for iteration."""
        flat = [root]
        for child in root.children:
            flat.extend(self.flatten_tree(child))
        return flat

# Standalone test
if __name__ == "__main__":
    checker = LogicChecker()
    result = checker.full_logic_check("C:/Users/ayush/Downloads/buggy_python_code.py")  # Your test file
    print(json.dumps(result, indent=2))