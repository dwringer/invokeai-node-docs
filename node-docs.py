#!/usr/bin/env python3
import os
import sys
import ast
import re
from typing import List, Dict, Any, Optional, Tuple
import argparse
import yaml

class NodeInfo:
    """Holds information about a single node definition."""
    def __init__(self, name: str, title: str, description: str, long_description: str,
                 category: str, tags: List[str], version: str, 
                 inputs: List[Dict[str, Any]], output: Dict[str, Any]):
        self.name = name
        self.title = title
        self.description = description
        self.long_description = long_description
        self.category = category
        self.tags = tags
        self.version = version
        self.inputs = inputs
        self.output = output

    def __lt__(self, other):
        """Enable alphabetical sorting by name."""
        return self.title.lower() < other.title.lower()

class FunctionInfo:
    """Holds information about a standalone function."""
    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description

class OutputDefinitionInfo:
    """Holds information about an output definition."""
    def __init__(self, name: str, fields: List[Dict[str, Any]]):
        self.name = name
        self.fields = fields

class DocExtractor:
    """Main class for extracting documentation from Python files."""
    
    def __init__(self, directory: str):
        """Initialize with the directory to scan."""
        self.directory = directory
        self.nodes = []
        self.functions = []
        self.output_defs = {}
        
    def extract_node_metadata(self, yaml_file="node-docs.yaml"):
        """
        Extracts metadata from a YAML file for inclusion in Markdown documentation.

        Args:
            yaml_file (str): The path to the YAML file. Defaults to "node-docs.yaml".

        Returns:
            dict: A dictionary containing the extracted metadata, or an empty
                  dictionary if the file is not found or parsing fails.
        """
        try:
            yaml_file = os.path.join(self.directory, yaml_file)
            with open(yaml_file, 'r') as f:
                data = yaml.safe_load(f)
                if data is None:
                    return {}  # Handle empty YAML file
                metadata = {}
                metadata['intro'] = data.get('intro', '')
                metadata['outro'] = data.get('outro', '')
                metadata['repository_name'] = data.get('repository_name', '')
                metadata['author'] = data.get('author', '')
                metadata['license'] = data.get('license', '')
                metadata['requirements'] = data.get('requirements', '')
                metadata['description'] = data.get('description', '')
                metadata['keywords'] = data.get('keywords', [])
                return metadata
        except FileNotFoundError:
            print(f"Error: File not found: {yaml_file}")
            return {}
        except yaml.YAMLError as e:
            print(f"Error parsing YAML file '{yaml_file}': {e}")
            return {}

    def extract_docs(self) -> None:
        """Extract documentation from all Python files in the directory."""
        for filename in os.listdir(self.directory):
            if filename.endswith('.py'):
                filepath = os.path.join(self.directory, filename)
                try:
                    with open(filepath, 'r', encoding='utf-8') as file:
                        content = file.read()
                    self._process_file(content, filepath)
                except Exception as e:
                    print(f"Error processing {filepath}: {str(e)}", file=sys.stderr)

        # Sort nodes alphabetically
        self.nodes.sort()
    
    def _process_file(self, content: str, filepath: str) -> None:
        """Process a single Python file."""
        try:
            tree = ast.parse(content)
            
            # First pass: gather output definitions
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    self._process_output_definition(node)
            
            # Second pass: process invocations and functions
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    self._process_invocation(node, content)
                elif isinstance(node, ast.FunctionDef):
                    # Only process top-level functions
                    if isinstance(node.parent, ast.Module):
                        self._process_function(node)
        except Exception as e:
            print(f"Error parsing {filepath}: {str(e)}", file=sys.stderr)
    
    def _process_output_definition(self, node: ast.ClassDef) -> None:
        """Process an output definition class."""
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Name) and decorator.func.id == "invocation_output":
                # This is an output definition
                fields = []
                # Process class attributes which are the output fields
                for item in node.body:
                    if isinstance(item, ast.AnnAssign):
                        field_name = item.target.id if isinstance(item.target, ast.Name) else None
                        field_type = self._get_type_annotation(item.annotation)
                        description = ""
                        
                        # Check for comments or docstrings that might describe this field
                        if item.value and isinstance(item.value, ast.Call):
                            for kw in item.value.keywords:
                                if kw.arg == "description" and isinstance(kw.value, ast.Constant):
                                    description = kw.value.value
                        
                        if field_name:
                            fields.append({
                                "name": field_name,
                                "type": field_type,
                                "description": description
                            })
                
                self.output_defs[node.name] = OutputDefinitionInfo(node.name, fields)
                break
    
    def _process_invocation(self, node: ast.ClassDef, content: str) -> None:
        """Process an invocation class."""
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Name) and decorator.func.id == "invocation":
                # Extract invocation details from decorator
                name = title = category = version = ""
                tags = []
                
                if decorator.args:
                    name = self._get_string_value(decorator.args[0])
                
                for keyword in decorator.keywords:
                    if keyword.arg == "title":
                        title = self._get_string_value(keyword.value)
                    elif keyword.arg == "category":
                        category = self._get_string_value(keyword.value)
                    elif keyword.arg == "tags":
                        tags = self._get_list_values(keyword.value)
                    elif keyword.arg == "version":
                        version = self._get_string_value(keyword.value)
                
                # Extract docstring
                node_description = ""
                long_description = ""
                if (node.body and isinstance(node.body[0], ast.Expr) and 
                    isinstance(node.body[0].value, ast.Constant) and 
                    isinstance(node.body[0].value.value, str)):
                    docstring = node.body[0].value.value.strip()
                    if docstring:
                        # Split docstring into first line and rest
                        lines = docstring.split('\n', 1)
                        node_description = lines[0].strip()
                        if len(lines) > 1:
                            long_description = lines[1].strip()
                
                # Extract input fields
                inputs = []
                for item in node.body:
                    if isinstance(item, ast.AnnAssign):
                        field_name = item.target.id if isinstance(item.target, ast.Name) else None
                        field_type = self._get_type_annotation(item.annotation)
                        description = ""
                        default = "None"
                        
                        # Extract field description and default value
                        if item.value and isinstance(item.value, ast.Call):
                            for kw in item.value.keywords:
                                if kw.arg == "description" and isinstance(kw.value, ast.Constant):
                                    description = kw.value.value
                                elif kw.arg == "default":
                                    default = self._get_default_value(kw.value)
                        
                        if field_name:
                            inputs.append({
                                "name": field_name,
                                "type": field_type,
                                "description": description,
                                "default": default
                            })
                
                # Extract output information
                output = {"type": "", "fields": []}
                
                # Try to find invoke method
                invoke_method = None
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and item.name == "invoke":
                        invoke_method = item
                        break
                
                if invoke_method:
                    # Extract return type from invoke method
                    return_type = ""
                    for decorator in invoke_method.decorator_list:
                        if isinstance(decorator, ast.Name) and decorator.id == "returns":
                            return_type = self._extract_return_type_from_decorator(decorator)
                    
                    if not return_type and invoke_method.returns:
                        return_type = self._get_type_annotation(invoke_method.returns)
                    
                    # Find actual return statement to get output class name
                    for item in ast.walk(invoke_method):
                        if isinstance(item, ast.Return) and isinstance(item.value, ast.Call):
                            if isinstance(item.value.func, ast.Name):
                                output_class = item.value.func.id
                                # If we have this output defined, use its information
                                if output_class in self.output_defs:
                                    output = {
                                        "type": output_class,
                                        "fields": self.output_defs[output_class].fields
                                    }
                                else:
                                    output = {"type": output_class, "fields": []}
                            elif isinstance(item.value.func, ast.Attribute):
                                output_class = f"{item.value.func.value.id}.{item.value.func.attr}(...)"
                                output = {"type": output_class, "fields": []}
                
                # Create node info and add to list
                node_info = NodeInfo(
                    name=name,
                    title=title,
                    description=node_description,
                    long_description=long_description,
                    category=category,
                    tags=tags,
                    version=version,
                    inputs=inputs,
                    output=output
                )
                self.nodes.append(node_info)
                break
    
    def _process_function(self, node: ast.FunctionDef) -> None:
        """Process a standalone function."""
        function_name = node.name
        description = ""
        
        # Extract docstring
        if (node.body and isinstance(node.body[0], ast.Expr) and 
            isinstance(node.body[0].value, ast.Constant) and 
            isinstance(node.body[0].value.value, str)):
            docstring = node.body[0].value.value.strip()
            if docstring:
                description = docstring.split('\n', 1)[0].strip()
        
        self.functions.append(FunctionInfo(function_name, description))
    
    def _get_string_value(self, node: ast.AST) -> str:
        """Extract string value from an AST node."""
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        return ""
    
    def _get_list_values(self, node: ast.AST) -> List[str]:
        """Extract list of string values from an AST node."""
        if isinstance(node, ast.List):
            return [self._get_string_value(elt) for elt in node.elts]
        return []
    
    def _get_type_annotation(self, node: ast.AST) -> str:
        """Convert type annotation to string representation."""
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Subscript):
            base = self._get_type_annotation(node.value)
            if isinstance(node.slice, ast.Index):
                # For Python 3.8 compatibility
                if hasattr(node.slice, 'value'):
                    slice_value = node.slice.value
                else:
                    slice_value = node.slice
                if isinstance(slice_value, ast.Tuple):
                    params = [self._get_type_annotation(elt) for elt in slice_value.elts]
                    return f"{base}[{', '.join(params)}]"
                else:
                    return f"{base}[{self._get_type_annotation(slice_value)}]"
            else:
                # For Python 3.9+
                return f"{base}[{self._get_type_annotation(node.slice)}]"
        elif isinstance(node, ast.Attribute):
            value = self._get_type_annotation(node.value)
            return f"{value}.{node.attr}"
        elif isinstance(node, ast.Constant):
            return str(node.value)
        elif isinstance(node, ast.Tuple):
            return f"({', '.join(self._get_type_annotation(elt) for elt in node.elts)})"
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                func_name = node.func.id
                args = [self._get_type_annotation(arg) for arg in node.args]
                return f"{func_name}({', '.join(args)})"
        return "Any"
    
    def _get_default_value(self, node: ast.AST) -> str:
        """Extract default value from an AST node."""
        if isinstance(node, ast.Constant):
            return str(node.value)
        elif isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.List):
            return f"[{', '.join(self._get_default_value(elt) for elt in node.elts)}]"
        elif isinstance(node, ast.Dict):
            keys = [self._get_default_value(k) for k in node.keys]
            values = [self._get_default_value(v) for v in node.values]
            return f"{{{', '.join(f'{k}: {v}' for k, v in zip(keys, values))}}}"
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                func_name = node.func.id
                args = [self._get_default_value(arg) for arg in node.args]
                return f"{func_name}({', '.join(args)})"
        return "None"
    
    def _extract_return_type_from_decorator(self, node: ast.AST) -> str:
        """Extract return type from a decorator."""
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "returns":
            if node.args:
                return self._get_type_annotation(node.args[0])
        return ""
    
    def generate_markdown(self) -> str:
        """Generate markdown documentation from extracted information."""
        md = []

        metadata = self.extract_node_metadata()
        if metadata:
            print("Extracted Metadata:")
            for key, value in metadata.items():
                print(f"- {key}:")
                if isinstance(value, list):
                    for item in value:
                        print(f"  - {item}")
                else:
                    print(f"  {value}")
        # Add module header
        module_name = os.path.basename(self.directory)
        md.append(f"# {module_name}\n")

        if metadata:
            if metadata.get('repository_name'):
                md.append(f"\n**Repository Name:** {metadata['repository_name']}\n")
            if metadata.get('author'):
                md.append(f"\n**Author:** {metadata['author']}\n")
            if metadata.get('license'):
                md.append(f"\n**License:** {metadata['license']}\n")
            if metadata.get('requirements'):
                md.append("\n**Requirements:**\n")
                for req in metadata['requirements']:
                    md.append(f"- {req}\n")

        if metadata:
            if metadata.get('intro'):
                md.append("\n## Introduction\n")
                md.append(metadata['intro'])
                md.append('\n')

        # Add overview section
        md.append("## Overview\n")
        
        if self.nodes:
            md.append("### Nodes\n")
            for node in self.nodes:
                _title = node.title.lower().replace(' ', '-')
                for punctuation in '()\/\\!@#$%^&*()_=+[{]}|;:\'"<>,.?':
                    _title = _title.replace(punctuation, '')
                md.append(f"- [{node.title}](#{_title}) - {node.description}\n")
        
        if self.functions:
            md.append("\n<details>\n")
            md.append("<summary>\n\n### Functions\n\n</summary>\n")
            for func in self.functions:
                md.append(f"\n- `{func.name}` - {func.description}")
            md.append("\n</details>\n")
        
        if self.output_defs:
            md.append("\n<details>\n")
            md.append("<summary>\n\n### Output Definitions\n\n</summary>\n")
            for name, output_def in self.output_defs.items():
                md.append(f"\n- `{name}` - Output definition with {len(output_def.fields)} fields")
            md.append("\n</details>\n")
        
        # Add individual node sections
        if self.nodes:
            md.append("\n## Nodes\n")
            for node in self.nodes:
                md.append(f"### {node.title}\n")
                md.append(f"**ID:** `{node.name}`\n\n")
                md.append(f"**Category:** {node.category}\n\n")
                if node.tags:
                    md.append(f"**Tags:** {', '.join(node.tags)}\n\n")
                if node.version:
                    md.append(f"**Version:** {node.version}\n\n")
                
                md.append(f"**Description:** {node.description}\n")
                
                if node.long_description:
                    md.append(f"\n{node.long_description}\n")
                
                # Add input fields table
                if node.inputs:
                    md.append("\n<details>\n")
                    md.append("<summary>\n\n#### Inputs\n\n</summary>\n\n")
                    md.append("| Name | Type | Description | Default |\n")
                    md.append("| ---- | ---- | ----------- | ------- |\n")
                    for input_field in node.inputs:
                        md.append(f"| `{input_field['name']}` | `{input_field['type']}` | {input_field['description']} | {input_field['default']} |\n")
                    md.append("\n\n</details>\n")
                
                # Add output information
                md.append("\n<details>\n")
                md.append("<summary>\n\n#### Output\n\n</summary>\n\n")
                if node.output["type"]:
                    md.append(f"**Type:** `{node.output['type']}`\n\n")
                    if node.output["fields"]:
                        md.append("| Name | Type | Description |\n")
                        md.append("| ---- | ---- | ----------- |\n")
                        for field in node.output["fields"]:
                            md.append(f"| `{field['name']}` | `{field['type']}` | {field['description']} |\n")
                else:
                    md.append("No output information available.\n")
                md.append("\n\n</details>\n")
                
                md.append("\n---\n")
        
        if metadata:
            if metadata.get('outro'):
                md.append("\n## Footnotes\n")
                md.append(metadata['outro'])
                md.append('\n')
        
        return "".join(md)

def setup_ast_parent_links(node: ast.AST, parent: Optional[ast.AST] = None) -> None:
    """Add parent links to all nodes in the AST. (for document extraction)"""
    node.parent = parent
    for child in ast.iter_child_nodes(node):
        setup_ast_parent_links(child, node)

# Monkey patch ast.parse to add parent links
original_parse = ast.parse

def parse_with_parent_links(*args, **kwargs):
    tree = original_parse(*args, **kwargs)
    setup_ast_parent_links(tree)
    return tree

ast.parse = parse_with_parent_links

def make_docs():
    """Main entry point for the node-docs script."""
    parser = argparse.ArgumentParser(description="Extract documentation from Python files and generate markdown.")
    parser.add_argument("directory", help="Directory containing Python files to process")
    parser.add_argument("-o", "--output", help="Output markdown file (default: <directory_name>.md)")
    args = parser.parse_args()
    args_directory = args.directory
    while args_directory[-1] in ['"', "'", "\\", "/"]:
        args_directory = args_directory[:-1]
    
    if not os.path.isdir(args_directory):
        print(f"Error: '{args.directory}' is not a directory", file=sys.stderr)
        sys.exit(1)
    
    # Determine output file name
    if args.output:
        output_file = args.output
    else:
        dir_name = os.path.basename(args_directory)
        output_file = f"{dir_name}.md"
    
    # Extract documentation
    extractor = DocExtractor(args_directory)
    extractor.extract_docs()
    
    # Generate markdown
    markdown = extractor.generate_markdown()
    
    # Write output file
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(markdown)
    
    print(f"Documentation generated: {output_file}")

if __name__ == "__main__":
    make_docs()
