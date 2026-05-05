"""R219: Feature Flags Management System - Dynamic Toggle + A/B Testing + User Segmentation + Gradual Rollout.
Demonstrates feature flag management.
"""
import time, hashlib
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum

class FlagType(Enum):
    BOOLEAN = "boolean"
    PERCENTAGE = "percentage"
    AB_TEST = "ab_test"
    SEGMENT = "segment"

class FlagStatus(Enum):
    ENABLED = "enabled"
    DISABLED = "disabled"
    SCHEDULED = "scheduled"
    ARCHIVED = "archived"

@dataclass
class FeatureFlag:
    key: str
    name: str
    flag_type: FlagType
    status: FlagStatus = FlagStatus.DISABLED
    default_value: bool = False
    rollout_percentage: float = 0.0
    segments: Dict[str, Any] = field(default_factory=dict)
    ab_variants: Dict[str, float] = field(default_factory=dict)  # variant -> weight
    scheduled_start: float = None
    scheduled_end: float = None
    description: str = ""

class FeatureFlagManager:
    """Manages feature flags with dynamic toggles, A/B testing, and user segmentation."""
    
    def __init__(self):
        self.flags: Dict[str, FeatureFlag] = {}
        self.evaluation_log: List[Dict] = []
    
    def create_flag(self, flag: FeatureFlag):
        self.flags[flag.key] = flag
    
    def enable_flag(self, key: str):
        if key in self.flags:
            self.flags[key].status = FlagStatus.ENABLED
    
    def disable_flag(self, key: str):
        if key in self.flags:
            self.flags[key].status = FlagStatus.DISABLED
    
    def set_rollout(self, key: str, percentage: float):
        if key in self.flags:
            self.flags[key].rollout_percentage = max(0.0, min(100.0, percentage))
    
    def evaluate(self, key: str, user_context: Dict = None) -> Any:
        """Evaluate flag for a user."""
        if key not in self.flags:
            return None
        
        flag = self.flags[key]
        result = False
        reason = ""
        
        # Check status
        if flag.status == FlagStatus.DISABLED:
            result = flag.default_value
            reason = "disabled"
        elif flag.status == FlagStatus.ARCHIVED:
            result = flag.default_value
            reason = "archived"
        elif flag.status == FlagStatus.SCHEDULED:
            now = time.time()
            if flag.scheduled_start and now < flag.scheduled_start:
                result = flag.default_value
                reason = "not_started"
            elif flag.scheduled_end and now > flag.scheduled_end:
                result = flag.default_value
                reason = "expired"
            else:
                result = self._evaluate_by_type(flag, user_context)
                reason = "scheduled_active"
        else:  # ENABLED
            result = self._evaluate_by_type(flag, user_context)
            reason = "enabled"
        
        # Log evaluation
        self.evaluation_log.append({
            "flag": key,
            "user_id": user_context.get("user_id") if user_context else None,
            "result": result,
            "reason": reason,
            "timestamp": time.time()
        })
        
        return result
    
    def _evaluate_by_type(self, flag: FeatureFlag, user_context: Dict) -> Any:
        """Evaluate flag based on its type."""
        if flag.flag_type == FlagType.BOOLEAN:
            return True
        
        elif flag.flag_type == FlagType.PERCENTAGE:
            # Use user_id for consistent hashing
            user_id = user_context.get("user_id", "anonymous")
            hash_val = int(hashlib.md5(f"{flag.key}:{user_id}".encode()).hexdigest(), 16) % 100
            return hash_val < flag.rollout_percentage
        
        elif flag.flag_type == FlagType.AB_TEST:
            user_id = user_context.get("user_id", "anonymous")
            hash_val = int(hashlib.md5(f"{flag.key}:{user_id}".encode()).hexdigest(), 16)
            total_weight = sum(flag.ab_variants.values())
            cumulative = 0
            for variant, weight in flag.ab_variants.items():
                cumulative += weight
                if (hash_val % total_weight) < cumulative:
                    return variant
            return list(flag.ab_variants.keys())[0]
        
        elif flag.flag_type == FlagType.SEGMENT:
            if not user_context:
                return False
            # Check if user matches any segment
            for segment_name, condition in flag.segments.items():
                if self._matches_segment(user_context, condition):
                    return True
            return False
        
        return False
    
    def _matches_segment(self, user_context: Dict, condition: Dict) -> bool:
        """Check if user context matches segment condition."""
        for key, value in condition.items():
            if key not in user_context:
                return False
            if isinstance(value, dict):
                # Support operators like {"gt": 18}
                if "gt" in value and user_context[key] <= value["gt"]:
                    return False
                if "lt" in value and user_context[key] >= value["lt"]:
                    return False
                if "in" in value and user_context[key] not in value["in"]:
                    return False
            elif user_context[key] != value:
                return False
        return True
    
    def get_flag_status(self) -> Dict:
        return {
            key: {
                "name": flag.name,
                "type": flag.flag_type.value,
                "status": flag.status.value,
                "rollout": flag.rollout_percentage,
                "segments": list(flag.segments.keys())
            }
            for key, flag in self.flags.items()
        }
    
    def get_stats(self) -> Dict:
        total_evaluations = len(self.evaluation_log)
        enabled_count = sum(1 for f in self.flags.values() if f.status == FlagStatus.ENABLED)
        return {
            "total_flags": len(self.flags),
            "enabled_flags": enabled_count,
            "total_evaluations": total_evaluations
        }

def run_feature_flag_demo():
    print("=== R219 Feature Flags Management System ===")
    
    manager = FeatureFlagManager()
    
    # Create flags
    manager.create_flag(FeatureFlag(
        key="dark_mode",
        name="Dark Mode",
        flag_type=FlagType.BOOLEAN,
        description="Enable dark mode UI"
    ))
    
    manager.create_flag(FeatureFlag(
        key="new_checkout",
        name="New Checkout Flow",
        flag_type=FlagType.PERCENTAGE,
        rollout_percentage=50.0,
        description="Gradual rollout of new checkout"
    ))
    
    manager.create_flag(FeatureFlag(
        key="homepage_layout",
        name="Homepage A/B Test",
        flag_type=FlagType.AB_TEST,
        ab_variants={"control": 50, "variant_a": 25, "variant_b": 25},
        description="A/B test for homepage layout"
    ))
    
    manager.create_flag(FeatureFlag(
        key="premium_features",
        name="Premium Features",
        flag_type=FlagType.SEGMENT,
        segments={
            "premium_users": {"plan": "premium"},
            "enterprise": {"plan": "enterprise"},
            "beta_testers": {"is_beta": True}
        },
        description="Features for premium users"
    ))
    
    # Enable flags
    manager.enable_flag("dark_mode")
    manager.enable_flag("new_checkout")
    manager.enable_flag("homepage_layout")
    manager.enable_flag("premium_features")
    
    # Test evaluations
    user1 = {"user_id": "user_001", "plan": "premium", "is_beta": False}
    user2 = {"user_id": "user_002", "plan": "free", "is_beta": True}
    user3 = {"user_id": "user_003", "plan": "enterprise"}
    
    print(f"1. Dark mode for user1: {manager.evaluate('dark_mode', user1)}")
    print(f"2. New checkout for user1: {manager.evaluate('new_checkout', user1)}")
    print(f"3. Homepage layout for user2: {manager.evaluate('homepage_layout', user2)}")
    print(f"4. Premium features for user1: {manager.evaluate('premium_features', user1)}")
    print(f"   Premium features for user2: {manager.evaluate('premium_features', user2)}")
    print(f"   Premium features for user3: {manager.evaluate('premium_features', user3)}")
    
    # Stats
    stats = manager.get_stats()
    print(f"5. Stats: {stats}")
    
    print("\nR219 Feature Flags Management System ready.")

run_feature_flag_demo()
