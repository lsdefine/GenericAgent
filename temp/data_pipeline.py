#!/usr/bin/env python3
"""Data Pipeline - ETL pipeline with data validation and transformation chain"""
from typing import Callable, Any, List, Dict, Optional
from datetime import datetime
from enum import Enum

class ValidationRule:
    def __init__(self, field: str, validator: Callable[[Any], bool], error_msg: str = ""):
        self.field = field
        self.validator = validator
        self.error_msg = error_msg or f"Validation failed for {field}"
    
    def validate(self, record: Dict) -> Optional[str]:
        if self.field in record:
            if not self.validator(record[self.field]):
                return self.error_msg
        return None


class Transformation:
    def __init__(self, func: Callable[[Dict], Dict], name: str = ""):
        self.func = func
        self.name = name or func.__name__
    
    def apply(self, record: Dict) -> Dict:
        return self.func(record)


class Pipeline:
    """ETL Pipeline with validation and transformation chain"""
    
    def __init__(self, name: str = "pipeline"):
        self.name = name
        self.extractors: List[Callable] = []
        self.validators: List[ValidationRule] = []
        self.transformations: List[Transformation] = []
        self.sinks: List[Callable] = []
        self.stats = {"extracted": 0, "valid": 0, "invalid": 0, "transformed": 0, "loaded": 0}
        self.errors: List[Dict] = []
    
    def add_extractor(self, func: Callable) -> "Pipeline":
        self.extractors.append(func)
        return self
    
    def add_validator(self, rule: ValidationRule) -> "Pipeline":
        self.validators.append(rule)
        return self
    
    def add_transformation(self, func: Callable) -> "Pipeline":
        self.transformations.append(Transformation(func))
        return self
    
    def add_sink(self, func: Callable) -> "Pipeline":
        self.sinks.append(func)
        return self
    
    def extract(self) -> List[Dict]:
        records = []
        for ext in self.extractors:
            result = ext()
            if isinstance(result, list):
                records.extend(result)
            else:
                records.append(result)
        self.stats["extracted"] = len(records)
        return records
    
    def validate(self, records: List[Dict]) -> List[Dict]:
        valid = []
        for rec in records:
            errs = [r.validate(rec) for r in self.validators]
            errs = [e for e in errs if e is not None]
            if not errs:
                valid.append(rec)
                self.stats["valid"] += 1
            else:
                self.stats["invalid"] += 1
                self.errors.append({"record": rec, "errors": errs})
        return valid
    
    def transform(self, records: List[Dict]) -> List[Dict]:
        result = []
        for rec in records:
            transformed = rec.copy()
            for t in self.transformations:
                transformed = t.apply(transformed)
            result.append(transformed)
            self.stats["transformed"] += 1
        return result
    
    def load(self, records: List[Dict]) -> List[Any]:
        outputs = []
        for rec in records:
            for sink in self.sinks:
                output = sink(rec)
                outputs.append(output)
            self.stats["loaded"] += 1
        return outputs
    
    def run(self) -> Dict:
        records = self.extract()
        records = self.validate(records)
        records = self.transform(records)
        self.load(records)
        return {
            "pipeline": self.name,
            "stats": self.stats,
            "errors": self.errors[:10]
        }
    
    def get_stats(self) -> Dict:
        return self.stats.copy()


if __name__ == "__main__":
    # Extractors
    def get_users():
        return [
            {"name": "alice", "age": 30, "email": "alice@test.com"},
            {"name": "bob", "age": -1, "email": "invalid"},
            {"name": "charlie", "age": 25, "email": "charlie@test.com"},
        ]
    
    # Validators
    def is_positive(v): return v > 0
    def is_email(v): return "@" in v
    
    # Transformations
    def upper_name(rec):
        rec["name"] = rec["name"].upper()
        return rec
    
    def add_timestamp(rec):
        rec["processed_at"] = str(datetime.now())[:19]
        return rec
    
    # Sink
    loaded = []
    def store(rec):
        loaded.append(rec)
        return True
    
    # Build and run
    p = Pipeline("user_etl")
    p.add_extractor(get_users)
    p.add_validator(ValidationRule("age", is_positive, "age must be positive"))
    p.add_validator(ValidationRule("email", is_email, "invalid email"))
    p.add_transformation(upper_name)
    p.add_transformation(add_timestamp)
    p.add_sink(store)
    
    result = p.run()
    print(f"Stats: {result['stats']}")
    print(f"Errors: {len(result['errors'])}")
    print(f"Loaded records: {len(loaded)}")
    for r in loaded:
        print(f"  {r['name']}: {r['email']}")
    
    print("Data pipeline ready.")
