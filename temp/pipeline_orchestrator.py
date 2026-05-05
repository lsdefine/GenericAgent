#!/usr/bin/env python3
"""ML Pipeline Orchestrator"""
import logging, json, time, os
logging.basicConfig(level=logging.INFO)

class PipelineNode:
    def __init__(self, name, func, inputs=None):
        self.name = name
        self.func = func
        self.inputs = inputs or []
        self.output = None

    def execute(self, data_store):
        kwargs = {k: data_store.get(k) for k in self.inputs}
        logging.info(f"Executing node: {self.name}")
        self.output = self.func(**kwargs)
        return self.output

class PipelineOrchestrator:
    def __init__(self, name="default"):
        self.name = name
        self.nodes = {}
        self.dependencies = {}
        self.data_store = {}

    def add_step(self, name, func, inputs=None, outputs=None):
        node = PipelineNode(name, func, inputs)
        self.nodes[name] = node
        if outputs:
            for o in outputs:
                self.data_store[o] = None
                self.dependencies[o] = name
        return self

    def validate(self):
        for name, node in self.nodes.items():
            for inp in node.inputs:
                if inp not in self.data_store:
                    logging.warning(f"Input '{inp}' for node '{name}' has no upstream producer")
        return True

    def execute_order(self):
        """Simple topological sort"""
        order = []
        visited = set()
        def visit(node_name):
            if node_name in visited:
                return
            visited.add(node_name)
            node = self.nodes[node_name]
            for inp in node.inputs:
                if inp in self.dependencies:
                    visit(self.dependencies[inp])
            order.append(node_name)
        for name in self.nodes:
            visit(name)
        return order

    def run(self, initial_data=None):
        self.data_store.update(initial_data or {})
        self.validate()
        order = self.execute_order()
        results = {}
        for name in order:
            node = self.nodes[name]
            result = node.execute(self.data_store)
            if result:
                for key, val in result.items():
                    self.data_store[key] = val
            results[name] = node.output
        return results

    def save(self, path=None):
        path = path or f"{self.name}_pipeline.json"
        config = {
            "name": self.name,
            "nodes": {n: {"inputs": nd.inputs} for n, nd in self.nodes.items()}
        }
        with open(path, 'w') as f:
            json.dump(config, f, indent=2)
        return path

    @classmethod
    def load(cls, path):
        with open(path) as f:
            config = json.load(f)
        p = cls(config["name"])
        for name, cfg in config["nodes"].items():
            p.add_step(name, lambda **k: {}, inputs=cfg["inputs"])
        return p

if __name__ == "__main__":
    def preprocess(**k):
        return {"data": "processed"}
    def train(**k):
        return {"model": "trained_model", "metrics": {"acc": 0.95}}
    def evaluate(**k):
        return {"report": "evaluation_report"}

    pipe = PipelineOrchestrator("example")
    pipe.add_step("preprocess", preprocess, outputs=["data"])
    pipe.add_step("train", train, inputs=["data"], outputs=["model", "metrics"])
    pipe.add_step("evaluate", evaluate, inputs=["model"], outputs=["report"])

    results = pipe.run()
    logging.info(f"Pipeline results: {results}")
