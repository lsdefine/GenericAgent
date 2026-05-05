"""R208: Data Pipeline Orchestrator - ETL Flow + Data Transformation + Quality Checks + Lineage Tracking.
Demonstrates a data pipeline with extraction, transformation, loading, and lineage tracking.
"""
import time, uuid
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict

class StageStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

@dataclass
class DataRecord:
    id: str
    data: Dict
    metadata: Dict = field(default_factory=dict)

@dataclass
class PipelineStage:
    name: str
    transform: Callable[[List[DataRecord]], List[DataRecord]]
    quality_check: Optional[Callable[[List[DataRecord]], bool]] = None
    status: StageStatus = StageStatus.PENDING
    input_count: int = 0
    output_count: int = 0
    duration: float = 0.0

class LineageTracker:
    """Tracks data lineage through the pipeline."""
    
    def __init__(self):
        self.lineage: Dict[str, List[str]] = defaultdict(list)
        self.record_history: Dict[str, List[Dict]] = defaultdict(list)
    
    def track(self, stage: str, input_ids: List[str], output_ids: List[str]):
        for oid in output_ids:
            self.lineage[oid] = input_ids
            self.record_history[oid].append({"stage": stage, "time": time.time()})
    
    def get_ancestors(self, record_id: str) -> List[str]:
        ancestors = []
        to_visit = [record_id]
        visited = set()
        while to_visit:
            current = to_visit.pop(0)
            if current in visited:
                continue
            visited.add(current)
            parents = self.lineage.get(current, [])
            ancestors.extend(parents)
            to_visit.extend(parents)
        return list(set(ancestors))

class DataPipeline:
    """Data pipeline orchestrator."""
    
    def __init__(self):
        self.stages: List[PipelineStage] = []
        self.lineage = LineageTracker()
        self.results: Dict[str, Any] = {}
    
    def add_stage(self, stage: PipelineStage):
        self.stages.append(stage)
    
    def execute(self, data: List[DataRecord]) -> List[DataRecord]:
        """Execute all stages in sequence."""
        current_data = data
        
        for stage in self.stages:
            stage.status = StageStatus.RUNNING
            stage.input_count = len(current_data)
            start_time = time.time()
            
            try:
                # Apply transformation
                transformed = stage.transform(current_data)
                
                # Quality check
                if stage.quality_check and not stage.quality_check(transformed):
                    stage.status = StageStatus.FAILED
                    raise Exception(f"Quality check failed at stage: {stage.name}")
                
                # Track lineage
                input_ids = [r.id for r in current_data]
                output_ids = [r.id for r in transformed]
                self.lineage.track(stage.name, input_ids, output_ids)
                
                stage.output_count = len(transformed)
                stage.duration = time.time() - start_time
                stage.status = StageStatus.COMPLETED
                current_data = transformed
                
            except Exception as e:
                stage.status = StageStatus.FAILED
                stage.duration = time.time() - start_time
                raise
        
        return current_data
    
    def get_pipeline_report(self) -> Dict:
        return {
            "stages": [{
                "name": s.name,
                "status": s.status.value,
                "input": s.input_count,
                "output": s.output_count,
                "duration": round(s.duration, 4)
            } for s in self.stages],
            "lineage_stats": {
                "total_records_tracked": len(self.lineage.record_history),
                "stages_processed": len(self.stages)
            }
        }

def run_pipeline_demo():
    print("=== R208 Data Pipeline Orchestrator ===")
    
    pipeline = DataPipeline()
    
    # Define stages
    def extract_transform(records):
        return [DataRecord(id=r.id, data={"processed": True, **r.data}) for r in records]
    
    def filter_records(records):
        return [r for r in records if r.data.get("value", 0) > 50]
    
    def aggregate(records):
        total = sum(r.data.get("value", 0) for r in records)
        return [DataRecord(id="agg_1", data={"total": total, "count": len(records)})]
    
    def quality_check(records):
        return all(r.data.get("processed") for r in records)
    
    # Add stages
    pipeline.add_stage(PipelineStage("extract", extract_transform, quality_check))
    pipeline.add_stage(PipelineStage("filter", filter_records))
    pipeline.add_stage(PipelineStage("aggregate", aggregate))
    
    # Test 1: Normal pipeline execution
    input_data = [
        DataRecord(id=f"r{i}", data={"value": i * 10}) for i in range(1, 11)
    ]
    
    result = pipeline.execute(input_data)
    print(f"1. Final records: {len(result)}")
    print(f"2. Aggregated total: {result[0].data['total']}")
    
    # Test 2: Pipeline report
    report = pipeline.get_pipeline_report()
    print(f"3. Stages completed: {report['stages']}")
    
    # Test 3: Lineage tracking
    ancestors = pipeline.lineage.get_ancestors("agg_1")
    print(f"4. Lineage ancestors for agg_1: {len(ancestors)} records")
    
    print("\nR208 Data Pipeline Orchestrator ready.")

run_pipeline_demo()
