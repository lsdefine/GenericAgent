#!/usr/bin/env python3
"""
Knowledge Graph Builder for GenericAgent
知识图谱构建: 从日志/任务/记忆中提取实体和关系
支持: 实体抽取、关系发现、图谱查询、可视化导出(GraphML)
"""

import os
import re
import json
import time
import logging
from datetime import datetime
from typing import Dict, List, Set, Tuple, Optional
from collections import defaultdict

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

class KnowledgeGraph:
    def __init__(self):
        self.entities: Dict[str, Dict] = {}
        self.relations: List[Dict] = []
        self._entity_type_pattern = {
            'file': r'[\w\./-]+\.(py|json|md|txt|sh|yaml|yml)',
            'module': r'[\w_]+_engine|[\w_]+_sop|[\w_]+_hub',
            'task': r'\[R\d{3}\]',
            'tool': r'(git|python3|curl|wget|docker|npm)\b',
            'status': r'(SUCCESS|FAILED|PENDING|RUNNING|COMPLETED)',
        }
    
    def extract_entities(self, text: str) -> Set[str]:
        entities = set()
        for entity_type, pattern in self._entity_type_pattern.items():
            matches = re.findall(pattern, text, re.IGNORECASE)
            for m in matches:
                entities.add(m)
                if m not in self.entities:
                    self.entities[m] = {'type': entity_type, 'mentions': 0, 'last_seen': None}
                self.entities[m]['mentions'] += 1
                self.entities[m]['last_seen'] = datetime.now().isoformat()
        return entities
    
    def extract_relations(self, text: str) -> List[Tuple[str, str, str]]:
        relations = []
        patterns = [
            (r'(\S+)\s+(?:uses|calls|imports|depends on)\s+(\S+)', 'depends_on'),
            (r'(\S+)\s+(?:triggers|creates|generates)\s+(\S+)', 'triggers'),
            (r'(\S+)\s+(?:sends to|notifies)\s+(\S+)', 'sends_to'),
        ]
        for pattern, rel_type in patterns:
            for m in re.finditer(pattern, text, re.IGNORECASE):
                src, tgt = m.group(1), m.group(2)
                if src in self.entities and tgt in self.entities:
                    relations.append((src, tgt, rel_type))
                    self.relations.append({'source': src, 'target': tgt, 'type': rel_type})
        return relations
    
    def ingest_file(self, filepath: str):
        if not os.path.exists(filepath):
            logger.warning(f"File not found: {filepath}")
            return
        
        with open(filepath, 'r', errors='ignore') as f:
            content = f.read()
        
        entities = self.extract_entities(content)
        relations = self.extract_relations(content)
        logger.info(f"Ingested {filepath}: {len(entities)} entities, {len(relations)} relations")
    
    def ingest_directory(self, dirpath: str, extensions: List[str] = None):
        if extensions is None:
            extensions = ['.py', '.md', '.json', '.txt', '.yaml']
        
        count = 0
        for root, _, files in os.walk(dirpath):
            for f in files:
                if any(f.endswith(ext) for ext in extensions):
                    self.ingest_file(os.path.join(root, f))
                    count += 1
        logger.info(f"Ingested {count} files from {dirpath}")
    
    def query_entity(self, name: str) -> Optional[Dict]:
        return self.entities.get(name)
    
    def query_relations(self, entity: str, direction: str = 'both') -> List[Dict]:
        results = []
        for r in self.relations:
            if direction in ('both', 'out') and r['source'] == entity:
                results.append(r)
            if direction in ('both', 'in') and r['target'] == entity:
                results.append(r)
        return results
    
    def get_neighbors(self, entity: str, depth: int = 1) -> Set[str]:
        neighbors = {entity}
        for _ in range(depth):
            new_neighbors = set()
            for n in neighbors:
                for r in self.relations:
                    if r['source'] == n:
                        new_neighbors.add(r['target'])
                    if r['target'] == n:
                        new_neighbors.add(r['source'])
            neighbors.update(new_neighbors)
        return neighbors
    
    def export_graphml(self, path: str = "knowledge_graph.graphml"):
        nodes = []
        for eid, edata in self.entities.items():
            nodes.append({'id': eid, 'type': edata['type'], 'mentions': edata['mentions']})
        
        data = {'nodes': nodes, 'edges': self.relations}
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)
        logger.info(f"Graph exported to {path}")
        return data
    
    def get_stats(self) -> Dict:
        type_counts = defaultdict(int)
        for e in self.entities.values():
            type_counts[e['type']] += 1
        
        return {
            'total_entities': len(self.entities),
            'total_relations': len(self.relations),
            'entity_types': dict(type_counts),
            'top_entities': sorted(self.entities.items(), key=lambda x: x[1]['mentions'], reverse=True)[:10]
        }

if __name__ == '__main__':
    kg = KnowledgeGraph()
    
    print("=== Building Knowledge Graph ===")
    
    # Scan current directory
    kg.ingest_directory(".", extensions=['.py', '.md', '.json', '.txt'])
    
    print("\n=== Stats ===")
    stats = kg.get_stats()
    print(f"Entities: {stats['total_entities']}")
    print(f"Relations: {stats['total_relations']}")
    print(f"Types: {stats['entity_types']}")
    
    print("\n=== Top Entities ===")
    for name, data in stats['top_entities']:
        print(f"  {name}: {data['mentions']} mentions ({data['type']})")
    
    print("\n=== Exporting ===")
    data = kg.export_graphml("knowledge_graph.json")
    print(f"Exported {len(data['nodes'])} nodes, {len(data['edges'])} edges")
