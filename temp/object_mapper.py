#!/usr/bin/env python3
"""Object Mapper - Lightweight ORM-like mapping with validation and relationships"""
from typing import Dict, Any, List, Optional, Type
from datetime import datetime
import json

class Field:
    def __init__(self, field_type: type, required: bool = False, default: Any = None, alias: str = None):
        self.field_type = field_type
        self.required = required
        self.default = default
        self.alias = alias
        self._name = None

class Relation:
    def __init__(self, model_cls, type: str = "belongs_to", foreign_key: str = None):
        self.model_cls = model_cls
        self.type = type
        self.foreign_key = foreign_key

class ModelMeta(type):
    def __new__(mcs, name, bases, namespace):
        cls = super().__new__(mcs, name, bases, namespace)
        cls._fields = {}
        cls._relations = {}
        for attr_name, attr_val in namespace.items():
            if isinstance(attr_val, Field):
                attr_val._name = attr_name
                if not attr_val.alias:
                    attr_val.alias = attr_name
                cls._fields[attr_name] = attr_val
            elif isinstance(attr_val, Relation):
                cls._relations[attr_name] = attr_val
        return cls

class Model(metaclass=ModelMeta):
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Model":
        instance = cls()
        for field_name, field in cls._fields.items():
            raw = data.get(field.alias, data.get(field_name))
            if raw is None:
                if field.required:
                    raise ValueError(f"Missing required field: {field_name}")
                raw = field.default
            else:
                raw = cls._coerce(raw, field.field_type)
            setattr(instance, field_name, raw)
        for rel_name, rel in cls._relations.items():
            if rel.type == "belongs_to" and rel.foreign_key in data:
                rel_instance = rel.model_cls.from_dict(data)
                setattr(instance, rel_name, rel_instance)
            elif rel.type == "has_many" and rel.foreign_key in data:
                items = data[rel.foreign_key]
                setattr(instance, rel_name, [rel.model_cls.from_dict(d) for d in items] if isinstance(items, list) else [])
        return instance
    
    def to_dict(self, include_relations: bool = True) -> Dict[str, Any]:
        result = {}
        for field_name, field in self._fields.items():
            val = getattr(self, field_name, field.default)
            result[field.alias] = self._serialize(val)
        if include_relations:
            for rel_name, rel in self._relations.items():
                rel_val = getattr(self, rel_name, None)
                if rel_val is not None:
                    if rel.type == "belongs_to":
                        result[rel_name] = rel_val.to_dict() if hasattr(rel_val, "to_dict") else rel_val
                    elif rel.type == "has_many":
                        result[rel_name] = [i.to_dict() if hasattr(i, "to_dict") else i for i in (rel_val or [])]
        return result
    
    @staticmethod
    def _coerce(value: Any, target_type: type) -> Any:
        if isinstance(value, target_type):
            return value
        try:
            return target_type(value)
        except (ValueError, TypeError):
            return value
    
    @staticmethod
    def _serialize(value: Any) -> Any:
        if isinstance(value, datetime):
            return value.isoformat()
        return value
    
    def validate(self) -> List[str]:
        errors = []
        for field_name, field in self._fields.items():
            val = getattr(self, field_name, None)
            if field.required and (val is None or (isinstance(val, str) and not val.strip())):
                errors.append(f"{field_name} is required")
        return errors

class User(Model):
    id = Field(int, required=True)
    name = Field(str, required=True, alias="user_name")
    email = Field(str, alias="email_address")
    age = Field(int, default=0)

class Post(Model):
    id = Field(int, required=True)
    title = Field(str, required=True)
    author_id = Field(int)
    author = Relation(User, "belongs_to", "author_id")

class Blog(Model):
    id = Field(int, required=True)
    posts = Relation(Post, "has_many", "post_list")

if __name__ == "__main__":
    user_data = {"id": 1, "user_name": "alice", "email_address": "a@b.com"}
    user = User.from_dict(user_data)
    print(f"User: name={user.name}, email={user.email}")
    print(f"to_dict: {user.to_dict()}")
    
    try:
        User.from_dict({"email_address": "x@y.com"})
    except ValueError as e:
        print(f"Validation: {e}")
    
    post_data = {"id": 10, "title": "Hello", "author_id": 1, "user_name": "alice", "email_address": "a@b.com"}
    post = Post.from_dict(post_data)
    print(f"Post author: {post.author.name}")
    
    blog = Blog.from_dict({"id": 100, "post_list": [{"id": 1, "title": "First"}, {"id": 2, "title": "Second"}]})
    print(f"Blog: {[p.title for p in blog.posts]}")
    print("Object mapper ready.")
