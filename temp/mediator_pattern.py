#!/usr/bin/env python3
"""Mediator Pattern - Decoupled communication between components via central mediator"""
from typing import Dict, Callable, Any, List
from abc import ABC, abstractmethod

class Colleague(ABC):
    def __init__(self, mediator: "Mediator"):
        self.mediator = mediator
        self.mediator.register(self)
        self.received_messages: List[str] = []

class Mediator(ABC):
    @abstractmethod
    def register(self, colleague: Colleague):
        pass
    
    @abstractmethod
    def send(self, message: str, sender: Colleague):
        pass

class ChatMediator(Mediator):
    def __init__(self):
        self.colleagues: List[Colleague] = []
        self.message_log: List[Dict[str, str]] = []
    
    def register(self, colleague: Colleague):
        if colleague not in self.colleagues:
            self.colleagues.append(colleague)
    
    def send(self, message: str, sender: Colleague):
        self.message_log.append({"sender": sender.name, "message": message})
        for colleague in self.colleagues:
            if colleague != sender:
                colleague.receive(message, sender)
    
    def get_log(self):
        return self.message_log

class User(Colleague):
    def __init__(self, mediator: Mediator, name: str):
        super().__init__(mediator)
        self.name = name
    
    def send_message(self, message: str):
        self.mediator.send(message, self)
    
    def receive(self, message: str, sender: Colleague):
        self.received_messages.append(f"{sender.name}: {message}")

class NotificationMediator(Mediator):
    def __init__(self):
        self.handlers: Dict[str, List[Callable]] = {}
        self.colleagues: List[Colleague] = []
    
    def register(self, colleague: Colleague):
        if colleague not in self.colleagues:
            self.colleagues.append(colleague)
    
    def send(self, message: str, sender: Colleague):
        self.publish("default", message, sender)
    
    def subscribe(self, event: str, handler: Callable):
        self.handlers.setdefault(event, []).append(handler)
    
    def publish(self, event: str, data: Any = None, sender: Colleague = None):
        for handler in self.handlers.get(event, []):
            handler(data, sender)

class Subscriber(Colleague):
    def __init__(self, mediator: NotificationMediator, name: str):
        super().__init__(mediator)
        self.name = name
        self.notifications: List[str] = []
    
    def handle_notification(self, data: Any, sender: Colleague):
        sender_name = sender.name if sender else "system"
        self.notifications.append(f"[{self.name}] {sender_name}: {data}")

if __name__ == "__main__":
    # Chat mediator
    chat = ChatMediator()
    alice = User(chat, "Alice")
    bob = User(chat, "Bob")
    charlie = User(chat, "Charlie")
    
    alice.send_message("Hello everyone!")
    bob.send_message("Hi Alice!")
    
    print(f"Alice received: {alice.received_messages}")
    print(f"Bob received: {bob.received_messages}")
    print(f"Charlie received: {charlie.received_messages}")
    print(f"Chat log: {chat.get_log()}")
    
    # Notification mediator
    notif = NotificationMediator()
    subscriber1 = Subscriber(notif, "Sub1")
    subscriber2 = Subscriber(notif, "Sub2")
    
    notif.subscribe("order_created", subscriber1.handle_notification)
    notif.subscribe("order_created", subscriber2.handle_notification)
    notif.subscribe("payment_received", subscriber1.handle_notification)
    
    notif.publish("order_created", "Order #12345")
    notif.publish("payment_received", "$99.99")
    
    print(f"Sub1 notifications: {subscriber1.notifications}")
    print(f"Sub2 notifications: {subscriber2.notifications}")
    print("Mediator pattern ready.")
