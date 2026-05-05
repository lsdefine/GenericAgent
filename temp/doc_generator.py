#!/usr/bin/env python3
"""Documentation Generator - Auto-generate Markdown/HTML docs from code comments and signatures"""
import os
import ast
import inspect
from typing import Dict, List, Optional
from datetime import datetime

class DocGenerator:
    """Generate documentation from Python source code"""
    
    def __init__(self):
        self.modules = {}
    
    def analyze_module(self, filepath: str) -> Dict:
        """Analyze a Python file and extract docstrings, classes, functions"""
        with open(filepath, 'r') as f:
            source = f.read()
        
        tree = ast.parse(source)
        info = {"filepath": filepath, "classes": [], "functions": [], "module_doc": ""}
        
        # Module docstring
        if ast.get_docstring(tree):
            info["module_doc"] = ast.get_docstring(tree)
        
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef):
                cls_info = {
                    "name": node.name,
                    "docstring": ast.get_docstring(node) or "",
                    "methods": []
                }
                for item in node.body:
                    if isinstance(item, ast.FunctionDef):
                        args = [a.arg for a in item.args.args]
                        cls_info["methods"].append({
                            "name": item.name,
                            "args": args,
                            "docstring": ast.get_docstring(item) or ""
                        })
                info["classes"].append(cls_info)
            
            elif isinstance(node, ast.FunctionDef):
                args = [a.arg for a in node.args.args]
                info["functions"].append({
                    "name": node.name,
                    "args": args,
                    "docstring": ast.get_docstring(node) or ""
                })
        
        self.modules[filepath] = info
        return info
    
    def generate_markdown(self, output_dir: str = "docs") -> str:
        """Generate Markdown documentation for all analyzed modules"""
        os.makedirs(output_dir, exist_ok=True)
        
        lines = ["# Generated Documentation", f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", ""]
        
        for filepath, info in self.modules.items():
            module_name = os.path.splitext(os.path.basename(filepath))[0]
            lines.append(f"## Module: {module_name}")
            lines.append(f"Path: `{filepath}`")
            if info["module_doc"]:
                lines.append(f"\n{info['module_doc']}")
            lines.append("")
            
            for cls in info["classes"]:
                lines.append(f"### Class: {cls['name']}")
                if cls["docstring"]:
                    lines.append(f"{cls['docstring']}")
                lines.append("")
                
                for method in cls["methods"]:
                    args_str = ", ".join(method["args"])
                    lines.append(f"#### `{method['name']}({args_str})`")
                    if method["docstring"]:
                        lines.append(f"{method['docstring']}")
                    lines.append("")
            
            for func in info["functions"]:
                args_str = ", ".join(func["args"])
                lines.append(f"### Function: `{func['name']}({args_str})`")
                if func["docstring"]:
                    lines.append(f"{func['docstring']}")
                lines.append("")
        
        md_content = "\n".join(lines)
        filename = os.path.join(output_dir, f"docs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md")
        with open(filename, 'w') as f:
            f.write(md_content)
        return filename
    
    def generate_html(self, output_dir: str = "docs") -> str:
        """Generate simple HTML documentation"""
        os.makedirs(output_dir, exist_ok=True)
        
        html_parts = []
        for filepath, info in self.modules.items():
            module_name = os.path.splitext(os.path.basename(filepath))[0]
            html_parts.append(f"<h2>Module: {module_name}</h2>")
            if info["module_doc"]:
                html_parts.append(f"<p>{info['module_doc']}</p>")
            
            for cls in info["classes"]:
                html_parts.append(f"<h3>Class: {cls['name']}</h3>")
                for method in cls["methods"]:
                    args_str = ", ".join(method["args"])
                    html_parts.append(f"<p><code>{method['name']}({args_str})</code></p>")
                    if method["docstring"]:
                        html_parts.append(f"<blockquote>{method['docstring']}</blockquote>")
            
            for func in info["functions"]:
                args_str = ", ".join(func["args"])
                html_parts.append(f"<p><code>{func['name']}({args_str})</code></p>")
                if func["docstring"]:
                    html_parts.append(f"<blockquote>{func['docstring']}</blockquote>")
        
        html = f"""<!DOCTYPE html>
<html>
<head><title>Generated Docs</title></head>
<body>
<h1>Documentation</h1>
<p>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
{"\n".join(html_parts)}
</body>
</html>"""
        
        filename = os.path.join(output_dir, f"docs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html")
        with open(filename, 'w') as f:
            f.write(html)
        return filename


if __name__ == "__main__":
    gen = DocGenerator()
    
    # Analyze self
    gen.analyze_module("doc_generator.py")
    
    md_file = gen.generate_markdown()
    print(f"Markdown docs: {md_file}")
    
    html_file = gen.generate_html()
    print(f"HTML docs: {html_file}")
    
    # Verify
    print(f"\nAnalyzed {len(gen.modules)} modules")
    for name, info in gen.modules.items():
        print(f"  {name}: {len(info['classes'])} classes, {len(info['functions'])} functions")
    
    # Cleanup
    for f in os.listdir("docs"):
        os.remove(os.path.join("docs", f))
    os.rmdir("docs")
    print("Doc generator ready.")
