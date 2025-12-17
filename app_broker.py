import ast
import os
import json
import re
import yaml
from llama_handler import query_openrouter

class PatchPlusAgent:
    def __init__(self, root_path=".", config_file="patchplus_config.yaml"):
        self.root_path = os.path.abspath(root_path)
        self.config = self.load_config(config_file)
        self.entrypoints = self.config.get("entrypoints", [])
        if not self.entrypoints:
            raise ValueError("No entrypoints defined in patchplus_config.yaml")
        
        self.exclude_dirs = self.config.get("exclude_dirs", ["__pycache__", ".git", "venv", "tests", "migrations"])
        self.exclude_files = self.config.get("exclude_files", ["test_*.py", "*_test.py"])
        
        self.tree = {"name": "Project Root", "path": self.root_path, "children": []}
        self.file_contents = {}
        self.visited = set()
        self.node_map = {}

    def load_config(self, config_file):
        if not os.path.exists(config_file):
            raise FileNotFoundError(f"Config file not found: {config_file}")
        with open(config_file, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
        print(f"Patch-Plus: Config loaded from {config_file}")
        return config

    def is_excluded(self, path):
        rel = os.path.relpath(path, self.root_path)
        parts = rel.split(os.sep)
        if any(ex in parts for ex in self.exclude_dirs):
            return True
        filename = os.path.basename(path)
        if any(filename.startswith(pattern.replace("*", "")) for pattern in self.exclude_files):
            return True
        return False

    def find_entrypoint_files(self):
        found = []
        for entry in self.entrypoints:
            full_path = os.path.join(self.root_path, entry)
            if os.path.exists(full_path):
                found.append(full_path)
                print(f"✓ Found entrypoint: {entry}")
            else:
                print(f"✗ Entrypoint not found: {entry}")
        if not found:
            raise FileNotFoundError("None of the specified entrypoints exist.")
        return found

    def extract_imports(self, file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            try:
                tree = ast.parse(f.read())
            except SyntaxError:
                return []
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.append(node.module)
                # Handle relative imports like from .views import ...
                elif node.level > 0:
                    # Relative import without module name (e.g., from . import views)
                    imports.append("." * node.level)
        return imports

    def resolve_import_relative(self, imp_name, current_file_dir):
        # Remove any leading dots for relative imports (we don't support relative here yet)
        if imp_name.startswith('.'):
            return None  # Skip relative for now (DVPWA uses absolute-style)

        # Split the import into parts
        parts = imp_name.split('.')
        search_dirs = [current_file_dir]  # Start from current file's dir
        
        # Add parent directories to search path to simulate Python's package search
        parent = current_file_dir
        while parent != os.path.dirname(parent):  # Stop at root
            search_dirs.append(parent)
            parent = os.path.dirname(parent)

        for search_dir in search_dirs:
            current = search_dir
            found = True
            for i, part in enumerate(parts):
                candidate_file = os.path.join(current, part + ".py")
                if os.path.exists(candidate_file) and not self.is_excluded(candidate_file):
                    if i == len(parts) - 1:
                        return candidate_file
                    else:
                        # Continue into subdir if more parts
                        current = os.path.dirname(candidate_file)
                        continue

                candidate_package = os.path.join(current, part)
                candidate_init = os.path.join(candidate_package, "__init__.py")
                if os.path.exists(candidate_init) and not self.is_excluded(candidate_init):
                    current = candidate_package
                    if i == len(parts) - 1:
                        return candidate_init
                    continue

                # If no match, break
                found = False
                break

            if found:
                return candidate_file if 'candidate_file' in locals() else candidate_init

        return None

    def build_tree(self):
        entry_files = self.find_entrypoint_files()

        for entry in entry_files:
            rel_path = os.path.relpath(entry, self.root_path)
            entry_node = {
                "name": os.path.basename(entry),
                "path": rel_path,
                "type": "file",
                "imports": [],
                "children": []
            }
            self.tree["children"].append(entry_node)
            self.node_map[rel_path] = entry_node
            self._process_file(entry, entry_node)

        with open("patchplus_tree.json", "w", encoding="utf-8") as f:
            json.dump(self.tree, f, indent=2)

        total_files = len(self.file_contents)
        print(f"\nPatch-Plus: Hierarchical tree built!")
        print(f"Total files mapped: {total_files}")
        print("Tree saved to patchplus_tree.json")

    def _process_file(self, file_path, current_node):
        if file_path in self.visited:
            return
        self.visited.add(file_path)

        rel_path = os.path.relpath(file_path, self.root_path)
        print(f"Mapping → {rel_path}")

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.file_contents[rel_path] = content

        current_node["imports"] = self.extract_imports(file_path)

        current_dir = os.path.dirname(file_path)
        for imp in current_node["imports"]:
            target_path = self.resolve_import_relative(imp, current_dir)
            if target_path:
                target_rel = os.path.relpath(target_path, self.root_path)
                if target_rel not in self.node_map:
                    target_node = {
                        "name": os.path.basename(target_path),
                        "path": target_rel,
                        "type": "file",
                        "imports": [],
                        "children": []
                    }
                    self.node_map[target_rel] = target_node
                else:
                    target_node = self.node_map[target_rel]

                if target_node not in current_node["children"]:
                    current_node["children"].append(target_node)

                self._process_file(target_path, target_node)

    def categorize_imports_with_llama(self):
        all_imports = set()
        for content in self.file_contents.values():
            try:
                tree = ast.parse(content)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            all_imports.add(alias.name.split('.')[0])
                    elif isinstance(node, ast.ImportFrom):
                        if node.module:
                            all_imports.add(node.module.split('.')[0])
            except:
                continue

        if not all_imports:
            print("No imports found.")
            return

        prompt = f"""
You are a Python expert. Categorize each imported module into exactly one category:

- 'project_internal': Custom code in this project (e.g., sqli, dao, utils, views, routes)
- 'public_stdlib': Built-in Python standard library (e.g., os, sys, json, logging, ast)
- 'public_thirdparty': External pip packages (e.g., aiohttp, jinja2, yaml, requests, trafaret, aiopg)

Modules: {', '.join(sorted(all_imports))}

Respond with ONLY the JSON object. No extra text.

{{
  "categorization": {{
    "module_name": "category"
  }}
}}
"""

        print("Querying Llama for import categorization...")
        response = query_openrouter(prompt, temperature=0.0)

        try:
            start = response.find('{')
            end = response.rfind('}') + 1
            if start == -1 or end <= start:
                raise ValueError("No JSON")
            json_str = response[start:end]
            data = json.loads(json_str)
            categorization = data.get("categorization", {})
        except Exception as e:
            print(f"LLM parsing failed: {e}")
            print("Raw response:", response)
            categorization = {m: "unknown" for m in all_imports}

        result = {
            "total_unique_imports": len(all_imports),
            "categorization": categorization,
            "project_internal": [m for m, c in categorization.items() if c == "project_internal"],
            "public": [m for m, c in categorization.items() if c != "project_internal"]
        }

        with open("patchplus_categorized_imports.json", "w") as f:
            json.dump(result, f, indent=2)

        print("\nCategorization complete!")
        print(f"Project internal modules: {len(result['project_internal'])}")
        print(f"Public/external modules: {len(result['public'])}")

    def analyze_internal_code_with_llama(self):
        internal_files = []
        for rel_path, content in self.file_contents.items():
            if any(keyword in rel_path.lower() for keyword in ['sqli', 'dao', 'utils', 'views', 'routes', 'middlewares']):
                internal_files.append({"path": rel_path, "content": content})

        if not internal_files:
            print("No internal project files found to analyze.")
            return

        print(f"\nAnalyzing {len(internal_files)} internal project files with Llama...")

        results = []
        for file in internal_files:
            path = file["path"]
            content = file["content"][:15000]  # Increased limit

            prompt = f"""
You are a senior Python security auditor for web applications.
Analyze this code for security vulnerabilities, bad practices, and logic bugs.

File: {path}
Code:
{content}

Focus on SQL injection, XSS, CSRF, session issues, weak crypto, hardcoded secrets.

Respond ONLY in JSON:
{{
  "file": "{path}",
  "issues": [
    {{
      "type": "vulnerability|bad_practice|logic_bug",
      "severity": "high|medium|low",
      "description": "clear explanation",
      "line_range": "lines X-Y",
      "suggestion": "how to fix"
    }}
  ],
  "summary": "one-sentence summary"
}}
"""

            print(f"Analyzing {path}...")
            response = query_openrouter(prompt, temperature=0.2)

            try:
                start = response.find('{')
                end = response.rfind('}') + 1
                if start == -1 or end <= start:
                    raise ValueError("No JSON")
                analysis = json.loads(response[start:end])
            except Exception as e:
                analysis = {"file": path, "error": str(e), "raw_response": response[:1000]}

            results.append(analysis)

        with open("patchplus_vuln_analysis.json", "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)

        high = sum(1 for r in results for i in r.get("issues", []) if i.get("severity") == "high")
        print(f"\nAnalysis complete! Found {high} high-severity issues across {len(internal_files)} files.")
        print("Full report saved to patchplus_vuln_analysis.json")

if __name__ == "__main__":
    agent = PatchPlusAgent(".", "patchplus_config.yaml")
    agent.build_tree()
    agent.categorize_imports_with_llama()
    agent.analyze_internal_code_with_llama()