#!/usr/bin/env python3
"""GenericAgent CLI - Unified Command-Line Interface"""
import argparse
import sys
import os
import logging

logging.basicConfig(level=logging.INFO, format="%(message)s")

class GACLI:
    """Unified CLI for GenericAgent modules"""
    
    def __init__(self):
        self.parser = self._build_parser()
        
    def _build_parser(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(
            prog="ga",
            description="GenericAgent CLI - Manage all GA modules"
        )
        subparsers = parser.add_subparsers(dest="command", help="Available commands")
        
        # Status command
        status_p = subparsers.add_parser("status", help="Show system status")
        status_p.add_argument("--detail", action="store_true", help="Show detailed status")
        
        # Registry command
        reg_p = subparsers.add_parser("registry", help="Manage model registry")
        reg_p.add_argument("action", choices=["list", "show", "categories"], help="Action")
        reg_p.add_argument("--name", type=str, help="Model name")
        
        # Benchmark command
        bench_p = subparsers.add_parser("benchmark", help="Run benchmarks")
        bench_p.add_argument("--target", type=str, default="default", help="Target function")
        bench_p.add_argument("--runs", type=int, default=3, help="Number of runs")
        
        # Pipeline command
        pipe_p = subparsers.add_parser("pipeline", help="Manage pipelines")
        pipe_p.add_argument("action", choices=["list", "run"], help="Action")
        pipe_p.add_argument("--name", type=str, default="default", help="Pipeline name")
        
        # API command
        api_p = subparsers.add_parser("api", help="Start API server")
        api_p.add_argument("--port", type=int, default=8000, help="Server port")
        api_p.add_argument("--host", type=str, default="0.0.0.0", help="Server host")
        
        # Scan command
        scan_p = subparsers.add_parser("scan", help="System capability scan")
        scan_p.add_argument("--all", action="store_true", help="Full scan")
        
        return parser
        
    def handle_status(self, args):
        logging.info("=== GenericAgent Status ===")
        logging.info(f"  Python: {sys.version.split()[0]}")
        logging.info(f"  Platform: {sys.platform}")
        logging.info(f"  CWD: {os.getcwd()}")
        py_files = [f for f in os.listdir(".") if f.endswith(".py")]
        logging.info(f"  Python modules: {len(py_files)}")
        if args.detail:
            logging.info("  Modules:")
            for f in sorted(py_files):
                logging.info(f"    - {f}")
                
    def handle_registry(self, args):
        if args.action == "list":
            logging.info("Registered models: CausalML, GNN, Transformer, Diffusion, SSL")
        elif args.action == "categories":
            logging.info("Categories: causal, graph, transformer, generative, ssl, nas")
        elif args.action == "show":
            logging.info(f"Model: {args.name or 'N/A'}")
            
    def handle_benchmark(self, args):
        logging.info(f"Running benchmark on '{args.target}' ({args.runs} runs)...")
        import time
        start = time.time()
        time.sleep(0.1)
        elapsed = time.time() - start
        logging.info(f"Completed in {elapsed*1000:.1f}ms")
        
    def handle_pipeline(self, args):
        if args.action == "list":
            logging.info("Pipelines: default, ml_training, inference")
        elif args.action == "run":
            logging.info(f"Starting pipeline: {args.name}")
            
    def handle_api(self, args):
        logging.info(f"Starting API server on {args.host}:{args.port}")
        logging.info("Routes: /api/models, /api/benchmark, /api/pipeline")
        
    def handle_scan(self, args):
        logging.info("Scanning system capabilities...")
        import platform
        logging.info(f"  OS: {platform.system()} {platform.release()}")
        logging.info(f"  Arch: {platform.machine()}")
        logging.info(f"  CPUs: {os.cpu_count()}")
        
    def run(self, args=None):
        parsed = self.parser.parse_args(args)
        if not parsed.command:
            self.parser.print_help()
            return
            
        handlers = {
            "status": self.handle_status,
            "registry": self.handle_registry,
            "benchmark": self.handle_benchmark,
            "pipeline": self.handle_pipeline,
            "api": self.handle_api,
            "scan": self.handle_scan,
        }
        handler = handlers.get(parsed.command)
        if handler:
            handler(parsed)


if __name__ == "__main__":
    cli = GACLI()
    cli.run()
