#!/usr/bin/env python3
"""Unit of Work - Transactional change tracking for multiple repositories"""
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
import threading

@dataclass
class Entity:
    id: int
    data: Dict[str, Any] = field(default_factory=dict)
    _deleted: bool = False

class Repository:
    def __init__(self, name: str, data: Optional[Dict[int, Entity]] = None):
        self.name = name
        self._store: Dict[int, Entity] = data or {}
    
    def get(self, entity_id: int) -> Optional[Entity]:
        return self._store.get(entity_id)
    
    def add(self, entity: Entity):
        self._store[entity.id] = entity
    
    def all(self) -> List[Entity]:
        return list(self._store.values())
    
    def remove(self, entity: Entity):
        entity._deleted = True

class UnitOfWork:
    def __init__(self):
        self._repositories: Dict[str, Repository] = {}
        self._new: Dict[str, List[Entity]] = {}
        self._dirty: Dict[str, List[Entity]] = {}
        self._deleted: Dict[str, List[Entity]] = {}
        self._committed = False
        self._lock = threading.Lock()
    
    def register_repository(self, repo: Repository):
        self._repositories[repo.name] = repo
    
    def register_new(self, entity: Entity, repo_name: str):
        self._new.setdefault(repo_name, []).append(entity)
    
    def register_dirty(self, entity: Entity, repo_name: str):
        self._dirty.setdefault(repo_name, []).append(entity)
    
    def register_deleted(self, entity: Entity, repo_name: str):
        self._deleted.setdefault(repo_name, []).append(entity)
    
    def commit(self):
        with self._lock:
            # Apply new
            for repo_name, entities in self._new.items():
                repo = self._repositories.get(repo_name)
                if repo:
                    for e in entities:
                        repo.add(e)
            
            # Apply dirty (already in store, just mark as updated)
            # In real implementation, would flush to DB here
            
            # Apply deleted
            for repo_name, entities in self._deleted.items():
                repo = self._repositories.get(repo_name)
                if repo:
                    for e in entities:
                        if e.id in repo._store:
                            del repo._store[e.id]
            
            self._committed = True
            self._new.clear()
            self._dirty.clear()
            self._deleted.clear()
    
    def rollback(self):
        self._new.clear()
        self._dirty.clear()
        self._deleted.clear()
        self._committed = False
    
    @property
    def is_committed(self):
        return self._committed
    
    def get_change_summary(self) -> Dict[str, int]:
        return {
            "new": sum(len(v) for v in self._new.values()),
            "dirty": sum(len(v) for v in self._dirty.values()),
            "deleted": sum(len(v) for v in self._deleted.values())
        }

if __name__ == "__main__":
    user_repo = Repository("users")
    order_repo = Repository("orders")
    
    uow = UnitOfWork()
    uow.register_repository(user_repo)
    uow.register_repository(order_repo)
    
    # Add user
    user = Entity(1, {"name": "Alice"})
    uow.register_new(user, "users")
    
    # Add order
    order = Entity(100, {"user_id": 1, "amount": 99.99})
    uow.register_new(order, "orders")
    
    print(f"Before commit - changes: {uow.get_change_summary()}")
    print(f"Users in repo: {len(user_repo.all())}")
    
    # Commit
    uow.commit()
    print(f"After commit - changes: {uow.get_change_summary()}")
    print(f"Users in repo: {len(user_repo.all())}")
    print(f"User 1: {user_repo.get(1).data}")
    
    # Modify and delete
    user.data["name"] = "Alice Updated"
    uow.register_dirty(user, "users")
    uow.register_deleted(order, "orders")
    
    print(f"Pre-delete changes: {uow.get_change_summary()}")
    uow.commit()
    print(f"Post-delete orders: {len(order_repo.all())}")
    
    # Rollback test
    new_entity = Entity(2, {"name": "Bob"})
    uow.register_new(new_entity, "users")
    print(f"Before rollback: {uow.get_change_summary()}")
    uow.rollback()
    print(f"After rollback: {uow.get_change_summary()}")
    print(f"Bob in repo: {user_repo.get(2)}")  # Should be None
    
    print("Unit of work ready.")
