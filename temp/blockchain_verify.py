#!/usr/bin/env python3
"""
Blockchain Verification Layer for GenericAgent
区块链验证层: 数据完整性验证、Merkle树、简易共识、链上存证
支持: 哈希链、Merkle证明、时间戳服务、不可变日志
"""

import os
import json
import hashlib
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field, asdict

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

@dataclass
class Block:
    index: int
    timestamp: str
    data: Dict
    previous_hash: str
    hash: str = ""
    nonce: int = 0
    merkle_root: str = ""
    
    def compute_hash(self) -> str:
        content = json.dumps({
            'index': self.index, 'timestamp': self.timestamp,
            'data': self.data, 'previous_hash': self.previous_hash,
            'nonce': self.nonce
        }, sort_keys=True).encode()
        return hashlib.sha256(content).hexdigest()
    
    def to_dict(self) -> Dict:
        return asdict(self)


class MerkleTree:
    def __init__(self, data_list: List[str]):
        self.leaves = [self._hash(d) for d in data_list]
        self.tree = self._build_tree(self.leaves)
    
    @staticmethod
    def _hash(data: str) -> str:
        return hashlib.sha256(data.encode()).hexdigest()
    
    def _build_tree(self, leaves: List[str]) -> List[str]:
        tree = leaves[:]
        while len(tree) > 1:
            if len(tree) % 2 != 0:
                tree.append(tree[-1])
            next_level = []
            for i in range(0, len(tree), 2):
                combined = tree[i] + tree[i+1]
                next_level.append(self._hash(combined))
            tree = next_level
        return tree
    
    @property
    def root(self) -> str:
        return self.tree[-1] if self.tree else self._hash("")
    
    def get_proof(self, index: int) -> List[Tuple[str, str]]:
        """Get Merkle proof for leaf at index"""
        proof = []
        idx = index
        current_level = self.leaves[:]
        
        while len(current_level) > 1:
            if len(current_level) % 2 != 0:
                current_level.append(current_level[-1])
            
            if idx % 2 == 0:
                sibling_idx = idx + 1
                direction = 'right'
            else:
                sibling_idx = idx - 1
                direction = 'left'
            
            if sibling_idx < len(current_level):
                proof.append((current_level[sibling_idx], direction))
            
            next_level = []
            for i in range(0, len(current_level), 2):
                combined = current_level[i] + current_level[i+1]
                next_level.append(self._hash(combined))
            
            current_level = next_level
            idx = idx // 2
        
        return proof
    
    @staticmethod
    def verify_proof(leaf_hash: str, proof: List[Tuple[str, str]], root: str) -> bool:
        current = leaf_hash
        for sibling_hash, direction in proof:
            if direction == 'right':
                current = hashlib.sha256((current + sibling_hash).encode()).hexdigest()
            else:
                current = hashlib.sha256((sibling_hash + current).encode()).hexdigest()
        return current == root


class Blockchain:
    def __init__(self, difficulty: int = 2, chain_file: str = ".blockchain.json"):
        self.difficulty = difficulty
        self.chain_file = chain_file
        self.chain: List[Block] = []
        self.pending_transactions: List[Dict] = []
        self._load_chain()
        if not self.chain:
            self._create_genesis_block()
    
    def _load_chain(self):
        if os.path.exists(self.chain_file):
            with open(self.chain_file) as f:
                data = json.load(f)
            self.chain = [Block(**b) for b in data]
    
    def _save_chain(self):
        with open(self.chain_file, 'w') as f:
            json.dump([b.to_dict() for b in self.chain], f, indent=2)
    
    def _create_genesis_block(self):
        genesis = Block(
            index=0, timestamp=datetime.now().isoformat(),
            data={'message': 'Genesis Block'}, previous_hash='0' * 64
        )
        genesis.hash = genesis.compute_hash()
        genesis.merkle_root = MerkleTree(['genesis']).root
        self.chain.append(genesis)
        self._save_chain()
    
    def get_latest_block(self) -> Block:
        return self.chain[-1]
    
    def add_transaction(self, sender: str, receiver: str, amount: float, memo: str = "") -> Dict:
        tx = {
            'sender': sender, 'receiver': receiver, 'amount': amount,
            'memo': memo, 'timestamp': datetime.now().isoformat()
        }
        self.pending_transactions.append(tx)
        return tx
    
    def mine_block(self) -> Block:
        if not self.pending_transactions:
            return None
        
        latest = self.get_latest_block()
        tx_hashes = [json.dumps(t, sort_keys=True) for t in self.pending_transactions]
        merkle = MerkleTree(tx_hashes)
        
        new_block = Block(
            index=len(self.chain),
            timestamp=datetime.now().isoformat(),
            data={'transactions': self.pending_transactions[:]},
            previous_hash=latest.hash,
            merkle_root=merkle.root
        )
        
        # Simple PoW
        nonce = 0
        target = '0' * self.difficulty
        while True:
            new_block.nonce = nonce
            new_block.hash = new_block.compute_hash()
            if new_block.hash[:self.difficulty] == target:
                break
            nonce += 1
        
        self.chain.append(new_block)
        self.pending_transactions.clear()
        self._save_chain()
        return new_block
    
    def verify_chain(self) -> bool:
        for i in range(1, len(self.chain)):
            current = self.chain[i]
            previous = self.chain[i-1]
            
            if current.previous_hash != previous.hash:
                return False
            
            if current.compute_hash() != current.hash:
                return False
        
        return True
    
    def get_balance(self, address: str) -> float:
        balance = 0.0
        for block in self.chain:
            for tx in block.data.get('transactions', []):
                if tx['sender'] == address:
                    balance -= tx['amount']
                if tx['receiver'] == address:
                    balance += tx['amount']
        return balance
    
    def get_chain_info(self) -> Dict:
        return {
            'length': len(self.chain),
            'pending_transactions': len(self.pending_transactions),
            'difficulty': self.difficulty,
            'latest_hash': self.get_latest_block().hash[:16] + '...',
            'valid': self.verify_chain()
        }


class ImmutableLogger:
    def __init__(self, log_file: str = ".immutable_log.jsonl"):
        self.log_file = log_file
        self.last_hash = "0" * 64
        self._load_last_hash()
    
    def _load_last_hash(self):
        if os.path.exists(self.log_file):
            with open(self.log_file) as f:
                lines = f.readlines()
            if lines:
                last = json.loads(lines[-1])
                self.last_hash = last.get('hash', self.last_hash)
    
    def log(self, event: str, data: Dict = None) -> Dict:
        entry = {
            'timestamp': datetime.now().isoformat(),
            'event': event, 'data': data or {},
            'previous_hash': self.last_hash
        }
        content = json.dumps(entry, sort_keys=True).encode()
        entry['hash'] = hashlib.sha256(content).hexdigest()
        self.last_hash = entry['hash']
        
        with open(self.log_file, 'a') as f:
            f.write(json.dumps(entry) + '\n')
        return entry
    
    def verify_log(self) -> bool:
        if not os.path.exists(self.log_file):
            return True
        
        prev_hash = "0" * 64
        with open(self.log_file) as f:
            for line in f:
                entry = json.loads(line.strip())
                if entry.get('previous_hash') != prev_hash:
                    return False
                
                test_entry = {
                    'timestamp': entry['timestamp'],
                    'event': entry['event'], 'data': entry['data'],
                    'previous_hash': entry['previous_hash']
                }
                test_hash = hashlib.sha256(json.dumps(test_entry, sort_keys=True).encode()).hexdigest()
                if test_hash != entry['hash']:
                    return False
                
                prev_hash = entry['hash']
        return True


if __name__ == '__main__':
    # Blockchain demo
    bc = Blockchain(difficulty=2)
    print("=== Blockchain Info ===")
    print(json.dumps(bc.get_chain_info(), indent=2))
    
    bc.add_transaction("alice", "bob", 10.0, "Payment")
    bc.add_transaction("bob", "charlie", 5.0, "Refund")
    block = bc.mine_block()
    print(f"\nMined block #{block.index}, hash: {block.hash[:20]}...")
    
    bc.add_transaction("charlie", "alice", 3.0, "Service fee")
    bc.mine_block()
    
    print(f"\nChain valid: {bc.verify_chain()}")
    print(f"Alice balance: {bc.get_balance('alice')}")
    print(f"Bob balance: {bc.get_balance('bob')}")
    
    # Immutable Logger demo
    print("\n=== Immutable Logger ===")
    logger = ImmutableLogger()
    logger.log("user_login", {"user": "admin", "ip": "192.168.1.1"})
    logger.log("file_access", {"file": "secret.doc", "action": "read"})
    logger.log("config_change", {"key": "timeout", "old": 30, "new": 60})
    print(f"Log verified: {logger.verify_log()}")
