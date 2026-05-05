#!/usr/bin/env python3
"""State Machine - Generic FSM with conditional transitions and state persistence"""
import json
import os
from typing import Callable, Dict, Any, Optional, List
from datetime import datetime

class Transition:
    """Represents a state transition with optional guard and action"""
    def __init__(self, from_state: str, to_state: str, event: str,
                 guard: Callable[[Dict], bool] = None,
                 action: Callable[[Dict], None] = None):
        self.from_state = from_state
        self.to_state = to_state
        self.event = event
        self.guard = guard
        self.action = action
    
    def can_execute(self, context: Dict) -> bool:
        if self.guard:
            return self.guard(context)
        return True
    
    def execute_action(self, context: Dict):
        if self.action:
            self.action(context)


class StateMachine:
    """Finite State Machine with persistence support"""
    
    def __init__(self, initial_state: str, name: str = "fsm"):
        self.name = name
        self.current_state = initial_state
        self.transitions: Dict[str, List[Transition]] = {}  # event -> transitions
        self.context: Dict[str, Any] = {}
        self.state_history: List[Dict] = [{"state": initial_state, "time": datetime.now().isoformat()}]
        self._on_enter: Dict[str, Callable] = {}
        self._on_exit: Dict[str, Callable] = {}
    
    def add_transition(self, from_state: str, to_state: str, event: str,
                       guard: Callable = None, action: Callable = None):
        t = Transition(from_state, to_state, event, guard, action)
        if event not in self.transitions:
            self.transitions[event] = []
        self.transitions[event].append(t)
    
    def on_enter(self, state: str, callback: Callable):
        self._on_enter[state] = callback
    
    def on_exit(self, state: str, callback: Callable):
        self._on_exit[state] = callback
    
    def trigger(self, event: str) -> bool:
        trans_list = self.transitions.get(event, [])
        for t in trans_list:
            if t.from_state == self.current_state and t.can_execute(self.context):
                # Execute exit callback
                if self.current_state in self._on_exit:
                    self._on_exit[self.current_state](self.context)
                
                # Execute transition action
                t.execute_action(self.context)
                
                old_state = self.current_state
                self.current_state = t.to_state
                
                # Record history
                self.state_history.append({
                    "from": old_state,
                    "to": self.current_state,
                    "event": event,
                    "time": datetime.now().isoformat()
                })
                
                # Execute enter callback
                if self.current_state in self._on_enter:
                    self._on_enter[self.current_state](self.context)
                
                return True
        return False
    
    def can_trigger(self, event: str) -> bool:
        trans_list = self.transitions.get(event, [])
        return any(t.from_state == self.current_state and t.can_execute(self.context) for t in trans_list)
    
    def get_available_events(self) -> List[str]:
        return [e for e in self.transitions if self.can_trigger(e)]
    
    def save_state(self, filepath: str):
        data = {
            "current_state": self.current_state,
            "context": self.context,
            "state_history": self.state_history[-100:]  # Keep last 100
        }
        with open(filepath, 'w') as f:
            json.dump(data, f)
    
    def load_state(self, filepath: str):
        if os.path.exists(filepath):
            with open(filepath, 'r') as f:
                data = json.load(f)
            self.current_state = data["current_state"]
            self.context = data.get("context", {})
            self.state_history = data.get("state_history", [])
            return True
        return False
    
    def get_stats(self) -> Dict:
        return {
            "name": self.name,
            "current_state": self.current_state,
            "total_transitions": len(self.state_history) - 1,
            "available_events": self.get_available_events()
        }


if __name__ == "__main__":
    # Example: Order processing FSM
    fsm = StateMachine("pending", name="order_fsm")
    fsm.context["order_id"] = "ORD-001"
    
    # Define transitions
    fsm.add_transition("pending", "confirmed", "confirm")
    fsm.add_transition("confirmed", "shipped", "ship",
                       guard=lambda ctx: ctx.get("paid", False))
    fsm.add_transition("confirmed", "cancelled", "cancel")
    fsm.add_transition("shipped", "delivered", "deliver")
    fsm.add_transition("pending", "cancelled", "cancel")
    
    # Callbacks
    fsm.on_enter("confirmed", lambda ctx: print(f"  -> Order {ctx['order_id']} confirmed"))
    fsm.on_enter("shipped", lambda ctx: print(f"  -> Order {ctx['order_id']} shipped"))
    fsm.on_enter("delivered", lambda ctx: print(f"  -> Order {ctx['order_id']} delivered"))
    fsm.on_exit("pending", lambda ctx: print(f"  <- Leaving pending state"))
    
    print(f"Initial state: {fsm.current_state}")
    print(f"Available events: {fsm.get_available_events()}")
    
    # Trigger confirm
    print("\nTrigger 'confirm':", fsm.trigger("confirm"))
    print(f"State: {fsm.current_state}")
    
    # Try ship without payment (should fail)
    print("\nTrigger 'ship' (unpaid):", fsm.trigger("ship"))
    print(f"State: {fsm.current_state}")
    
    # Pay and ship
    fsm.context["paid"] = True
    print("\nTrigger 'ship' (paid):", fsm.trigger("ship"))
    print(f"State: {fsm.current_state}")
    
    # Deliver
    print("\nTrigger 'deliver':", fsm.trigger("deliver"))
    print(f"State: {fsm.current_state}")
    
    # Save/load
    fsm.save_state("fsm_state.json")
    print(f"\nSaved state to fsm_state.json")
    
    # Create new FSM and load
    fsm2 = StateMachine("pending")
    fsm2.load_state("fsm_state.json")
    print(f"Loaded state: {fsm2.current_state}")
    print(f"Stats: {fsm2.get_stats()}")
    
    # Cleanup
    os.remove("fsm_state.json")
    print("State machine ready.")
