#!/usr/bin/env python3
"""FastAPI REST API Server for GenericAgent Modules"""
from typing import Optional, Dict, Any, List
import logging, functools

logging.basicConfig(level=logging.INFO)

class APIServer:
    """REST API Server wrapping core GA modules"""
    
    def __init__(self, host: str = "0.0.0.0", port: int = 8000):
        self.host = host
        self.port = port
        self.routes: Dict[str, dict] = {}
        self.middleware: List[callable] = []
        
    def route(self, path: str, method: str = "GET"):
        """Decorator to register an API endpoint"""
        def decorator(func):
            key = f"{method.upper()} {path}"
            self.routes[key] = {"handler": func, "method": method, "path": path}
            return func
        return decorator
        
    def register_middleware(self, middleware: callable):
        self.middleware.append(middleware)
        
    def get_routes(self) -> List[str]:
        return list(self.routes.keys())
        
    def handle_request(self, method: str, path: str, **kwargs) -> Dict:
        key = f"{method.upper()} {path}"
        if key not in self.routes:
            return {"error": "Not Found", "status": 404}
        try:
            handler = self.routes[key]["handler"]
            result = handler(**kwargs)
            return {"data": result, "status": 200}
        except Exception as e:
            return {"error": str(e), "status": 500}
            
    def run(self):
        logging.info(f"API Server starting on {self.host}:{self.port}")
        logging.info(f"Registered routes: {self.get_routes()}")


def setup_api_server(host: str = "0.0.0.0", port: int = 8000) -> APIServer:
    """Create and configure the API server"""
    api = APIServer(host, port)
    
    @api.route("/api/models", "GET")
    def list_models():
        return {"models": ["CausalML", "GNN", "Transformer", "Diffusion"]}
        
    @api.route("/api/models/{name}", "GET")
    def get_model(name: str = "test"):
        return {"name": name, "status": "registered"}
        
    @api.route("/api/models/categories", "GET")
    def list_categories():
        return ["causal", "graph", "transformer", "generative", "ssl"]

    @api.route("/api/benchmark/run", "POST")
    def run_benchmark(func_name: str = "default", n_runs: int = 3):
        return {"status": "benchmark_complete", "func": func_name, "runs": n_runs}
        
    @api.route("/api/benchmark/results", "GET")
    def get_results():
        return {"status": "no_results"}

    @api.route("/api/pipeline/run", "POST")
    def run_pipeline(pipeline_name: str = "default", **kwargs):
        return {"status": "pipeline_started", "name": pipeline_name}
        
    @api.route("/api/pipeline/list", "GET")
    def list_pipelines():
        return {"pipelines": ["default", "ml_training", "inference"]}
        
    return api


if __name__ == "__main__":
    api = setup_api_server()
    api.run()
    
    print("\n=== Route Test ===")
    for route in api.get_routes():
        print(f"  {route}")
        
    print("\n=== Request Simulation ===")
    result = api.handle_request("GET", "/api/models")
    print(f"GET /api/models: {result}")
    
    result = api.handle_request("GET", "/api/models/test")
    print(f"GET /api/models/test: {result}")
    
    result = api.handle_request("POST", "/api/benchmark/run", func_name="test")
    print(f"POST /api/benchmark/run: {result}")
    
    result = api.handle_request("GET", "/api/pipeline/list")
    print(f"GET /api/pipeline/list: {result}")
    
    result = api.handle_request("GET", "/api/nonexistent")
    print(f"GET /api/nonexistent: {result}")
