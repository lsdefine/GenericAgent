#!/usr/bin/env python3
"""Message Queue - Persistent messaging with consumer groups and ACK mechanism"""
import os
import json
import time
import uuid
from typing import Any, Callable, Dict, List, Optional
from collections import defaultdict
from threading import Lock

class Message:
    def __init__(self, body: Any, topic: str, headers: Dict = None):
        self.id = str(uuid.uuid4())[:8]
        self.body = body
        self.topic = topic
        self.headers = headers or {}
        self.timestamp = time.time()
        self.acknowledged = False
        self.delivery_count = 0
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id, "body": self.body, "topic": self.topic,
            "headers": self.headers, "timestamp": self.timestamp,
            "acknowledged": self.acknowledged, "delivery_count": self.delivery_count
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'Message':
        msg = cls(data["body"], data["topic"], data.get("headers"))
        msg.id = data["id"]
        msg.timestamp = data["timestamp"]
        msg.acknowledged = data["acknowledged"]
        msg.delivery_count = data["delivery_count"]
        return msg


class ConsumerGroup:
    """A group of consumers sharing message load"""
    
    def __init__(self, name: str):
        self.name = name
        self.consumers: Dict[str, Callable] = {}  # consumer_id -> handler
        self.offset = 0  # Track processing position
    
    def add_consumer(self, consumer_id: str, handler: Callable):
        self.consumers[consumer_id] = handler
    
    def remove_consumer(self, consumer_id: str):
        self.consumers.pop(consumer_id, None)


class MessageQueue:
    """Persistent message queue with consumer groups and ACK"""
    
    def __init__(self, storage_dir: str = ".mq_store"):
        self.storage_dir = storage_dir
        self.queues: Dict[str, List[Message]] = defaultdict(list)
        self.consumer_groups: Dict[str, Dict[str, ConsumerGroup]] = defaultdict(dict)
        self.unacked: Dict[str, Dict[str, Message]] = defaultdict(dict)  # topic -> msg_id -> msg
        self.max_retries = 3
        self._lock = Lock()
        os.makedirs(storage_dir, exist_ok=True)
    
    def publish(self, topic: str, body: Any, headers: Dict = None) -> Message:
        msg = Message(body, topic, headers)
        with self._lock:
            self.queues[topic].append(msg)
            self._persist_topic(topic)
        return msg
    
    def subscribe(self, topic: str, group_name: str, consumer_id: str, handler: Callable):
        with self._lock:
            if group_name not in self.consumer_groups[topic]:
                self.consumer_groups[topic][group_name] = ConsumerGroup(group_name)
            self.consumer_groups[topic][group_name].add_consumer(consumer_id, handler)
    
    def consume(self, topic: str, group_name: str = "default") -> Optional[Message]:
        with self._lock:
            group = self.consumer_groups.get(topic, {}).get(group_name)
            if not group:
                return None
            
            queue = self.queues.get(topic, [])
            if group.offset >= len(queue):
                return None
            
            msg = queue[group.offset]
            msg.delivery_count += 1
            group.offset += 1
            
            # Track unacked
            self.unacked[topic][msg.id] = msg
            self._persist_topic(topic)
            return msg
    
    def ack(self, topic: str, message_id: str) -> bool:
        with self._lock:
            msg = self.unacked.get(topic, {}).get(message_id)
            if msg:
                msg.acknowledged = True
                del self.unacked[topic][message_id]
                self._persist_topic(topic)
                return True
            return False
    
    def nack(self, topic: str, message_id: str) -> bool:
        """Re-queue unacknowledged message"""
        with self._lock:
            msg = self.unacked.get(topic, {}).get(message_id)
            if msg:
                del self.unacked[topic][message_id]
                if msg.delivery_count < self.max_retries:
                    # Re-insert at current offset - 1
                    group = self.consumer_groups.get(topic, {}).get("default")
                    if group:
                        group.offset -= 1
                    self.queues[topic].insert(group.offset if group else 0, msg)
                return True
            return False
    
    def get_pending(self, topic: str) -> int:
        queue = self.queues.get(topic, [])
        group = self.consumer_groups.get(topic, {}).get("default")
        if group:
            return len(queue) - group.offset
        return len(queue)
    
    def get_stats(self) -> Dict:
        stats = {"topics": {}}
        for topic, queue in self.queues.items():
            pending = self.get_pending(topic)
            stats["topics"][topic] = {
                "total": len(queue),
                "pending": pending,
                "unacked": len(self.unacked.get(topic, {})),
                "groups": len(self.consumer_groups.get(topic, {}))
            }
        return stats
    
    def _persist_topic(self, topic: str):
        path = os.path.join(self.storage_dir, f"{topic}.json")
        data = [m.to_dict() for m in self.queues.get(topic, [])]
        with open(path, 'w') as f:
            json.dump(data, f)
    
    def load_topic(self, topic: str):
        path = os.path.join(self.storage_dir, f"{topic}.json")
        if os.path.exists(path):
            with open(path, 'r') as f:
                data = json.load(f)
            self.queues[topic] = [Message.from_dict(d) for d in data]
    
    def cleanup(self):
        import shutil
        if os.path.exists(self.storage_dir):
            shutil.rmtree(self.storage_dir)


if __name__ == "__main__":
    mq = MessageQueue()
    
    received = []
    def handler(msg):
        received.append(msg.body)
        print(f"Received: {msg.body}")
    
    # Subscribe
    mq.subscribe("orders", "group1", "c1", handler)
    mq.subscribe("orders", "group1", "c2", handler)
    
    # Publish
    m1 = mq.publish("orders", {"item": "laptop", "qty": 1})
    m2 = mq.publish("orders", {"item": "phone", "qty": 2})
    m3 = mq.publish("orders", {"item": "tablet", "qty": 1})
    print(f"Published 3 messages to 'orders'")
    
    # Consume
    print("\nConsuming:")
    while True:
        msg = mq.consume("orders", "group1")
        if not msg:
            break
        handler(msg)
        mq.ack("orders", msg.id)
    
    print(f"\nStats: {mq.get_stats()}")
    print(f"Total received: {len(received)}")
    
    # Test persistence
    mq.publish("orders", {"item": "persistence_test"})
    mq.cleanup()
    print("Message queue ready.")
