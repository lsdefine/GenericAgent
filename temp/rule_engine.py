#!/usr/bin/env python3
"""Rule Engine - Condition/Action DSL with priority-based execution"""
from typing import Callable, Any, Dict, List, Optional
from enum import Enum
from dataclasses import dataclass, field

class Priority(Enum):
    LOW = 0
    MEDIUM = 1
    HIGH = 2
    CRITICAL = 3

class Rule:
    """Defines a single rule with condition, action, and priority"""
    
    def __init__(self, name: str, condition: Callable[[Dict], bool], 
                 action: Callable[[Dict], Any], priority: Priority = Priority.MEDIUM,
                 description: str = ""):
        self.name = name
        self.condition = condition
        self.action = action
        self.priority = priority
        self.description = description
    
    def evaluate(self, context: Dict) -> bool:
        try:
            return self.condition(context)
        except Exception:
            return False
    
    def execute(self, context: Dict) -> Any:
        return self.action(context)


class RuleEngine:
    """Manages and executes a set of rules based on priority"""
    
    def __init__(self, stop_on_first: bool = False):
        self.rules: List[Rule] = []
        self.stop_on_first = stop_on_first  # Stop after first matching rule
        self.execution_log: List[Dict] = []
    
    def add_rule(self, rule: Rule):
        self.rules.append(rule)
        # Keep sorted by priority (highest first)
        self.rules.sort(key=lambda r: r.priority.value, reverse=True)
    
    def add_rules(self, rules: List[Rule]):
        for rule in rules:
            self.add_rule(rule)
    
    def execute(self, context: Dict) -> List[Dict]:
        """Execute all matching rules and return results"""
        results = []
        
        for rule in self.rules:
            if rule.evaluate(context):
                try:
                    result = rule.execute(context)
                    log_entry = {
                        "rule": rule.name,
                        "priority": rule.priority.name,
                        "result": result,
                        "status": "success"
                    }
                    results.append(log_entry)
                    self.execution_log.append(log_entry)
                    
                    if self.stop_on_first:
                        break
                except Exception as e:
                    log_entry = {
                        "rule": rule.name,
                        "priority": rule.priority.name,
                        "result": None,
                        "status": "error",
                        "error": str(e)
                    }
                    results.append(log_entry)
                    self.execution_log.append(log_entry)
        
        return results
    
    def clear_log(self):
        self.execution_log = []


# DSL Helper Functions
def condition_field_equals(field: str, value: Any) -> Callable[[Dict], bool]:
    return lambda ctx: ctx.get(field) == value

def condition_field_greater(field: str, threshold: Any) -> Callable[[Dict], bool]:
    return lambda ctx: ctx.get(field, 0) > threshold

def condition_field_in(field: str, values: list) -> Callable[[Dict], bool]:
    return lambda ctx: ctx.get(field) in values

def action_set_value(field: str, value: Any) -> Callable[[Dict], Any]:
    def _action(ctx):
        ctx[field] = value
        return f"Set {field}={value}"
    return _action

def action_increment(field: str, amount: int = 1) -> Callable[[Dict], Any]:
    def _action(ctx):
        ctx[field] = ctx.get(field, 0) + amount
        return f"Incremented {field} by {amount}"
    return _action

def action_append_log(msg: str) -> Callable[[Dict], Any]:
    def _action(ctx):
        ctx.setdefault("__log", []).append(msg)
        return f"Logged: {msg}"
    return _action


if __name__ == "__main__":
    engine = RuleEngine()
    
    # Rule 1: VIP discount
    engine.add_rule(Rule(
        name="vip_discount",
        condition=condition_field_equals("user_type", "vip"),
        action=action_set_value("discount", 0.2),
        priority=Priority.HIGH,
        description="Apply 20% discount for VIP users"
    ))
    
    # Rule 2: High value bonus
    engine.add_rule(Rule(
        name="high_value_bonus",
        condition=condition_field_greater("cart_total", 1000),
        action=action_increment("bonus_points", 50),
        priority=Priority.MEDIUM,
        description="Bonus points for orders over 1000"
    ))
    
    # Rule 3: Category specific promotion
    engine.add_rule(Rule(
        name="electronics_promo",
        condition=condition_field_in("category", ["electronics", "gadgets"]),
        action=action_append_log("Applied electronics promotion"),
        priority=Priority.LOW
    ))
    
    # Rule 4: Critical fraud check
    engine.add_rule(Rule(
        name="fraud_check",
        condition=condition_field_greater("risk_score", 80),
        action=lambda ctx: "BLOCKED",
        priority=Priority.CRITICAL,
        description="Block high-risk transactions"
    ))
    
    # Test 1: VIP user with high value
    ctx1 = {"user_type": "vip", "cart_total": 1200, "category": "electronics", "risk_score": 10}
    res1 = engine.execute(ctx1)
    print("Test 1 (VIP, High Value):")
    for r in res1:
        print(f"  [{r['priority']}] {r['rule']}: {r['result']}")
    print(f"Context: {ctx1}")
    
    # Test 2: High risk
    engine.clear_log()
    ctx2 = {"user_type": "normal", "cart_total": 50, "risk_score": 90}
    res2 = engine.execute(ctx2)
    print("\nTest 2 (High Risk):")
    for r in res2:
        print(f"  [{r['priority']}] {r['rule']}: {r['result']}")
    
    # Test 3: stop_on_first
    engine2 = RuleEngine(stop_on_first=True)
    engine2.add_rule(Rule("always_true_1", lambda ctx: True, action_set_value("a", 1), Priority.LOW))
    engine2.add_rule(Rule("always_true_2", lambda ctx: True, action_set_value("b", 2), Priority.HIGH))
    
    ctx3 = {}
    res3 = engine2.execute(ctx3)
    print("\nTest 3 (stop_on_first):")
    for r in res3:
        print(f"  [{r['priority']}] {r['rule']}: {r['result']}")
    print(f"Context: {ctx3}")
    
    print("\nRule engine ready.")
