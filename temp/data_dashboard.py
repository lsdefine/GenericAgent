#!/usr/bin/env python3
"""Data Dashboard - Generate interactive HTML dashboards from benchmark results"""
import os
import json
from typing import Dict, List, Optional
from datetime import datetime

class DataDashboard:
    """Generate interactive HTML dashboards with Chart.js"""
    
    def __init__(self, output_dir: str = "dashboards"):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
    
    def generate_benchmark_dashboard(self, results: Dict, title: str = "Benchmark Results") -> str:
        """Generate HTML dashboard from benchmark results"""
        chart_data = json.dumps(results.get("metrics", {}))
        labels = list(results.get("metrics", {}).keys())
        values = list(results.get("metrics", {}).values())
        
        html = f"""<!DOCTYPE html>
<html>
<head>
    <title>{title}</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body {{ font-family: sans-serif; margin: 20px; background: #f5f5f5; }}
        .card {{ background: white; border-radius: 8px; padding: 20px; margin: 10px 0; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        .metric {{ display: inline-block; margin: 10px; padding: 10px 20px; background: #e3f2fd; border-radius: 4px; }}
        .chart-container {{ position: relative; height: 400px; }}
        h1 {{ color: #333; }}
    </style>
</head>
<body>
    <div class="card">
        <h1>{title}</h1>
        <p>Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>
        <div>
            {"".join(f"<div class='metric'><strong>{k}</strong>: {v}</div>" for k, v in results.get("metrics", {}).items())}
        </div>
    </div>
    <div class="card">
        <h2>Performance Comparison</h2>
        <div class="chart-container">
            <canvas id="benchmarkChart"></canvas>
        </div>
    </div>
    <script>
        const ctx = document.getElementById("benchmarkChart");
        new Chart(ctx, {{
            type: "bar",
            data: {{
                labels: {labels},
                datasets: [{{
                    label: "Performance Score",
                    data: {values},
                    backgroundColor: "rgba(54, 162, 235, 0.5)",
                    borderColor: "rgba(54, 162, 235, 1)",
                    borderWidth: 1
                }}]
            }},
            options: {{ responsive: true, maintainAspectRatio: false }}
        }});
    </script>
</body>
</html>"""
        
        filename = os.path.join(self.output_dir, f"dashboard_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html")
        with open(filename, 'w') as f:
            f.write(html)
        return filename
    
    def generate_summary_report(self, results: Dict) -> str:
        """Generate text summary report"""
        lines = ["# Dashboard Summary Report", f"Generated: {datetime.now()}", ""]
        metrics = results.get("metrics", {})
        for k, v in metrics.items():
            lines.append(f"- **{k}**: {v}")
        report = "\n".join(lines)
        filename = os.path.join(self.output_dir, f"summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md")
        with open(filename, 'w') as f:
            f.write(report)
        return filename


if __name__ == "__main__":
    dashboard = DataDashboard()
    
    sample_results = {
        "metrics": {
            "accuracy": 0.95,
            "f1_score": 0.92,
            "precision": 0.94,
            "recall": 0.91,
            "inference_time_ms": 45.2
        }
    }
    
    html_file = dashboard.generate_benchmark_dashboard(sample_results, "Model Benchmark Dashboard")
    print(f"HTML dashboard: {html_file}")
    
    md_file = dashboard.generate_summary_report(sample_results)
    print(f"Summary report: {md_file}")
    print("Dashboard generator ready.")
