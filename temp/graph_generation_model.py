#!/usr/bin/env python3
"""Graph Generation Model: 图生成模型"""
import math, random, logging
logging.basicConfig(level=logging.INFO)

class GraphGenerator:
    def __init__(self, max_nodes=20, edge_prob=0.3):
        self.max_nodes = max_nodes
        self.edge_prob = edge_prob

    def generate_erdos_renyi(self, n):
        """Erdos-Renyi随机图"""
        adj = [[0]*n for _ in range(n)]
        for i in range(n):
            for j in range(i+1, n):
                if random.random() < self.edge_prob:
                    adj[i][j] = adj[j][i] = 1
        return adj

    def generate_preferential_attachment(self, n, m=2):
        """Barabasi-Albert优先连接模型"""
        adj = [[0]*n for _ in range(n)]
        degrees = [0]*n
        # Initial clique
        for i in range(min(m, n)):
            for j in range(i+1, min(m, n)):
                adj[i][j] = adj[j][i] = 1
                degrees[i] += 1; degrees[j] += 1
        for i in range(m, n):
            targets = []
            total_deg = sum(degrees[:i]) or 1
            while len(targets) < min(m, i):
                j = random.randint(0, i-1)
                if degrees[j] / total_deg > random.random() and j not in targets:
                    targets.append(j)
                    adj[i][j] = adj[j][i] = 1
                    degrees[i] += 1; degrees[j] += 1
        return adj

if __name__ == "__main__":
    print("=== Graph Generation Demo ===")
    gg = GraphGenerator(max_nodes=10)
    er = gg.generate_erdos_renyi(5)
    print(f"ER graph edges: {sum(sum(r) for r in er)//2}")
    pa = gg.generate_preferential_attachment(8, m=2)
    print(f"PA graph edges: {sum(sum(r) for r in pa)//2}")
