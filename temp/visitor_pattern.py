#!/usr/bin/env python3
"""Visitor Pattern - Separates algorithms from object structure for AST/JSON processing"""
from typing import Dict, Any, List, Union
from abc import ABC, abstractmethod

class Visitor(ABC):
    @abstractmethod
    def visit_string(self, node: "StringNode"):
        pass
    
    @abstractmethod
    def visit_number(self, node: "NumberNode"):
        pass
    
    @abstractmethod
    def visit_object(self, node: "ObjectNode"):
        pass
    
    @abstractmethod
    def visit_array(self, node: "ArrayNode"):
        pass

class ASTNode(ABC):
    @abstractmethod
    def accept(self, visitor: Visitor):
        pass

class StringNode(ASTNode):
    def __init__(self, value: str):
        self.value = value
    
    def accept(self, visitor: Visitor):
        return visitor.visit_string(self)

class NumberNode(ASTNode):
    def __init__(self, value: Union[int, float]):
        self.value = value
    
    def accept(self, visitor: Visitor):
        return visitor.visit_number(self)

class ObjectNode(ASTNode):
    def __init__(self, properties: Dict[str, ASTNode]):
        self.properties = properties
    
    def accept(self, visitor: Visitor):
        return visitor.visit_object(self)

class ArrayNode(ASTNode):
    def __init__(self, elements: List[ASTNode]):
        self.elements = elements
    
    def accept(self, visitor: Visitor):
        return visitor.visit_array(self)

class JSONSerializer(Visitor):
    def __init__(self):
        self.indent_level = 0
    
    def _indent(self) -> str:
        return "  " * self.indent_level
    
    def visit_string(self, node: StringNode):
        return f'"{node.value}"'
    
    def visit_number(self, node: NumberNode):
        return str(node.value)
    
    def visit_object(self, node: ObjectNode):
        if not node.properties:
            return "{}"
        self.indent_level += 1
        items = []
        for key, val_node in node.properties.items():
            val_str = val_node.accept(self)
            items.append(f'{self._indent()}"{key}": {val_str}')
        self.indent_level -= 1
        return "{\n" + ",\n".join(items) + f"\n{self._indent()}}}"
    
    def visit_array(self, node: ArrayNode):
        if not node.elements:
            return "[]"
        self.indent_level += 1
        items = []
        for elem in node.elements:
            val_str = elem.accept(self)
            items.append(f"{self._indent()}{val_str}")
        self.indent_level -= 1
        return "[\n" + ",\n".join(items) + f"\n{self._indent()}]"

class TypeCounter(Visitor):
    def __init__(self):
        self.counts = {"string": 0, "number": 0, "object": 0, "array": 0}
    
    def visit_string(self, node: StringNode):
        self.counts["string"] += 1
    
    def visit_number(self, node: NumberNode):
        self.counts["number"] += 1
    
    def visit_object(self, node: ObjectNode):
        self.counts["object"] += 1
        for val in node.properties.values():
            val.accept(self)
    
    def visit_array(self, node: ArrayNode):
        self.counts["array"] += 1
        for elem in node.elements:
            elem.accept(self)

def build_ast(data: Any) -> ASTNode:
    if isinstance(data, str):
        return StringNode(data)
    elif isinstance(data, (int, float)):
        return NumberNode(data)
    elif isinstance(data, dict):
        return ObjectNode({k: build_ast(v) for k, v in data.items()})
    elif isinstance(data, list):
        return ArrayNode([build_ast(e) for e in data])
    else:
        return StringNode(str(data))

if __name__ == "__main__":
    data = {
        "name": "Alice",
        "age": 30,
        "skills": ["Python", "Go"],
        "address": {"city": "Beijing"}
    }
    
    ast = build_ast(data)
    
    # Serialize
    serializer = JSONSerializer()
    json_output = ast.accept(serializer)
    print("Serialized JSON:")
    print(json_output)
    
    # Count types
    counter = TypeCounter()
    ast.accept(counter)
    print(f"\nType counts: {counter.counts}")
    
    # Simple list
    list_ast = build_ast([1, "two", {"three": 3}])
    list_counter = TypeCounter()
    list_ast.accept(list_counter)
    print(f"List type counts: {list_counter.counts}")
    
    print("\nVisitor pattern ready.")
