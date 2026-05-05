#!/usr/bin/env python3
"""Graph Prompt Learning"""
import math, random, logging
logging.basicConfig(level=logging.INFO)

class GraphPromptLearning:
    def __init__(self, dim=32, n_prompts=4):
        self.dim = dim
        self.prompts = [[random.gauss(0,0.1) for _ in range(dim)] for _ in range(n_prompts)]

    def prompt_graph(self, graph_repr, task_id=0):
        prompt = self.prompts[task_id % len(self.prompts)]
        return [g+p for g,p in zip(graph_repr, prompt)]

    def update_prompts(self, task_grads, lr=0.01):
        for i in range(len(self.prompts)):
            for j in range(self.dim):
                if i < len(task_grads) and j < len(task_grads[i]):
                    self.prompts[i][j] -= lr * task_grads[i][j]

if __name__ == "__main__":
    gpl = GraphPromptLearning()
    repr_ = [random.gauss(0,1) for _ in range(32)]
    prompted = gpl.prompt_graph(repr_, task_id=0)
    grads = [[random.gauss(0,0.01) for _ in range(32)] for _ in range(4)]
    gpl.update_prompts(grads)
    logging.info(f"Graph prompt: {len(gpl.prompts)} prompts, updated")
