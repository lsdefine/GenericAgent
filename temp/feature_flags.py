#!/usr/bin/env python3
"""Feature Flags - Feature toggle system with targeting, rollout, and A/B testing"""
import time
import random
from typing import Dict, Any, Optional, List, Callable

class FeatureFlag:
    def __init__(self, key: str, enabled: bool = False, description: str = ""):
        self.key = key
        self.enabled = enabled
        self.description = description
        self.rollout_percentage = 100.0 if enabled else 0.0
        self.targeting_rules: List[Dict] = []
        self.created_at = time.time()
        self.variants: Dict[str, float] = {}
    
    def set_rollout(self, percentage: float):
        self.rollout_percentage = max(0.0, min(100.0, percentage))
    
    def add_variant(self, name: str, weight: float):
        self.variants[name] = weight
    
    def evaluate(self, context: Optional[Dict] = None) -> bool:
        for rule in self.targeting_rules:
            if self._match_rule(rule, context):
                return rule.get("value", True)
        if self.variants:
            return self._select_variant(context)
        return random.uniform(0, 100) < self.rollout_percentage
    
    def _match_rule(self, rule: Dict, context: Optional[Dict]) -> bool:
        conditions = rule.get("conditions", [])
        for cond in conditions:
            attr = cond.get("attribute")
            operator = cond.get("operator")
            value = cond.get("value")
            ctx_val = (context or {}).get(attr)
            if operator == "eq" and ctx_val != value:
                return False
            elif operator == "contains" and value not in (ctx_val or []):
                return False
            elif operator == "gte" and (ctx_val is None or ctx_val < value):
                return False
        return True
    
    def _select_variant(self, context: Optional[Dict]) -> bool:
        seed = hash(str(context)) % 1000 if context else random.randint(0, 999)
        threshold = 0
        total = sum(self.variants.values())
        pos = (seed / 1000) * total
        for variant, weight in self.variants.items():
            threshold += weight
            if pos <= threshold:
                return True
        return False

class FeatureFlagManager:
    def __init__(self):
        self.flags: Dict[str, FeatureFlag] = {}
    
    def register(self, flag: FeatureFlag):
        self.flags[flag.key] = flag
    
    def is_enabled(self, key: str, context: Optional[Dict] = None) -> bool:
        flag = self.flags.get(key)
        if not flag:
            return False
        return flag.evaluate(context)
    
    def get_flag(self, key: str) -> Optional[FeatureFlag]:
        return self.flags.get(key)
    
    def list_flags(self) -> Dict[str, dict]:
        return {k: {"enabled": f.enabled, "rollout": f.rollout_percentage,
                     "variants": f.variants, "rules": len(f.targeting_rules)}
                for k, f in self.flags.items()}
    
    def add_targeting_rule(self, key: str, conditions: List[Dict], value: bool = True):
        flag = self.flags.get(key)
        if flag:
            flag.targeting_rules.append({"conditions": conditions, "value": value})


if __name__ == "__main__":
    mgr = FeatureFlagManager()
    
    dark_mode = FeatureFlag("dark_mode", enabled=True)
    mgr.register(dark_mode)
    print(f"dark_mode: {mgr.is_enabled('dark_mode')}")
    
    new_ui = FeatureFlag("new_ui", enabled=False)
    new_ui.set_rollout(50)
    mgr.register(new_ui)
    enabled_count = sum(1 for _ in range(100) if mgr.is_enabled("new_ui"))
    print(f"new_ui rollout ~50%: {enabled_count}/100 enabled")
    
    beta = FeatureFlag("beta_feature", enabled=False)
    beta.add_variant("control", 80)
    beta.add_variant("treatment", 20)
    mgr.register(beta)
    
    mgr.add_targeting_rule("beta_feature", [{"attribute": "user_id", "eq": "vip123"}], value=True)
    print(f"beta for vip: {mgr.is_enabled('beta_feature', {'user_id': 'vip123'})}")
    print(f"beta for regular: {mgr.is_enabled('beta_feature', {'user_id': 'user456'})}")
    
    print(f"All flags: {mgr.list_flags()}")
    print("Feature flags ready.")
