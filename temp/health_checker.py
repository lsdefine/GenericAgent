"""R220: Health Check Aggregator - Multi-service Probe + Dependency Graph + Failure Propagation + Health Scoring.
Demonstrates health check aggregation.
"""
import time, random
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass, field
from enum import Enum

class HealthStatus(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"

@dataclass
class ServiceHealth:
    name: str
    status: HealthStatus = HealthStatus.UNKNOWN
    response_time: float = 0.0
    last_check: float = 0.0
    check_count: int = 0
    failure_count: int = 0
    details: str = ""

class HealthCheckAggregator:
    """Aggregates health checks across multiple services with dependency awareness."""
    
    def __init__(self):
        self.services: Dict[str, ServiceHealth] = {}
        self.dependencies: Dict[str, List[str]] = {}  # service -> depends on
        self.check_functions: Dict[str, Callable] = {}
        self.thresholds = {
            "degraded_response_time": 500.0,  # ms
            "unhealthy_response_time": 2000.0,
            "failure_rate_threshold": 0.5
        }
    
    def register_service(self, name: str, check_fn: Callable, dependencies: List[str] = None):
        self.services[name] = ServiceHealth(name=name)
        self.check_functions[name] = check_fn
        if dependencies:
            self.dependencies[name] = dependencies
    
    def check_service(self, name: str) -> ServiceHealth:
        """Run health check for a single service."""
        if name not in self.services:
            return ServiceHealth(name=name, status=HealthStatus.UNKNOWN)
        
        service = self.services[name]
        start_time = time.time()
        
        try:
            result = self.check_functions[name]()
            response_time = (time.time() - start_time) * 1000  # ms
            
            service.response_time = response_time
            service.last_check = time.time()
            service.check_count += 1
            
            # Determine status based on response time and result
            if not result.get("healthy", False):
                service.status = HealthStatus.UNHEALTHY
                service.failure_count += 1
                service.details = result.get("message", "Check failed")
            elif response_time > self.thresholds["unhealthy_response_time"]:
                service.status = HealthStatus.UNHEALTHY
                service.details = f"Response time {response_time:.0f}ms > threshold"
            elif response_time > self.thresholds["degraded_response_time"]:
                service.status = HealthStatus.DEGRADED
                service.details = f"Response time {response_time:.0f}ms degraded"
            else:
                service.status = HealthStatus.HEALTHY
                service.details = "OK"
        
        except Exception as e:
            service.status = HealthStatus.UNHEALTHY
            service.failure_count += 1
            service.check_count += 1
            service.last_check = time.time()
            service.details = str(e)
        
        return service
    
    def get_aggregated_health(self) -> Dict:
        """Get aggregated health status considering dependencies."""
        # Check all services
        for name in self.services:
            self.check_service(name)
        
        # Calculate dependency-aware health
        overall_status = HealthStatus.HEALTHY
        service_statuses = {}
        
        for name, service in self.services.items():
            effective_status = self._calculate_effective_status(name)
            service_statuses[name] = {
                "status": effective_status.value,
                "response_time": service.response_time,
                "details": service.details,
                "failure_rate": service.failure_count / max(1, service.check_count)
            }
            
            # Overall is worst of all
            if effective_status == HealthStatus.UNHEALTHY:
                overall_status = HealthStatus.UNHEALTHY
            elif effective_status == HealthStatus.DEGRADED and overall_status != HealthStatus.UNHEALTHY:
                overall_status = HealthStatus.DEGRADED
        
        # Calculate health score (0-100)
        health_score = self._calculate_health_score()
        
        return {
            "overall_status": overall_status.value,
            "health_score": health_score,
            "services": service_statuses,
            "dependency_graph": self.dependencies
        }
    
    def _calculate_effective_status(self, name: str) -> HealthStatus:
        """Calculate effective status considering dependency failures."""
        service = self.services[name]
        status = service.status
        
        # Check if any dependency is unhealthy
        if name in self.dependencies:
            for dep in self.dependencies[name]:
                if dep in self.services:
                    dep_status = self.services[dep].status
                    if dep_status == HealthStatus.UNHEALTHY:
                        # Dependency failure propagates
                        return HealthStatus.UNHEALTHY
                    elif dep_status == HealthStatus.DEGRADED and status == HealthStatus.HEALTHY:
                        status = HealthStatus.DEGRADED
        
        return status
    
    def _calculate_health_score(self) -> float:
        """Calculate overall health score (0-100)."""
        if not self.services:
            return 0.0
        
        scores = []
        for name, service in self.services.items():
            if service.status == HealthStatus.HEALTHY:
                # Base 100, reduce by response time
                score = max(0, 100 - (service.response_time / 20))
            elif service.status == HealthStatus.DEGRADED:
                score = 50
            elif service.status == HealthStatus.UNHEALTHY:
                score = 0
            else:
                score = 25  # Unknown
            scores.append(score)
        
        return round(sum(scores) / len(scores), 1)
    
    def get_dependency_impact(self, service_name: str) -> List[str]:
        """Get list of services impacted if this service fails."""
        impacted = []
        for name, deps in self.dependencies.items():
            if service_name in deps:
                impacted.append(name)
                # Recursive impact
                impacted.extend(self.get_dependency_impact(name))
        return list(set(impacted))

def run_health_demo():
    print("=== R220 Health Check Aggregator ===")
    
    aggregator = HealthCheckAggregator()
    
    # Simulated service checks
    def check_api():
        return {"healthy": True, "latency": 50}
    
    def check_db():
        return {"healthy": True, "latency": 10}
    
    def check_cache():
        # Simulate degraded cache
        return {"healthy": True, "latency": 800}
    
    def check_auth():
        return {"healthy": True, "latency": 30}
    
    def check_external():
        # Simulate failing external service
        return {"healthy": False, "message": "Timeout"}
    
    # Register services with dependencies
    aggregator.register_service("api", check_api, dependencies=["db", "cache", "auth"])
    aggregator.register_service("db", check_db)
    aggregator.register_service("cache", check_cache)
    aggregator.register_service("auth", check_auth, dependencies=["db"])
    aggregator.register_service("external", check_external)
    
    # Get aggregated health
    health = aggregator.get_aggregated_health()
    print(f"1. Overall status: {health['overall_status']}")
    print(f"   Health score: {health['health_score']}")
    
    for name, info in health['services'].items():
        print(f"   {name}: {info['status']} ({info['response_time']:.0f}ms)")
    
    # Dependency impact
    impact = aggregator.get_dependency_impact("db")
    print(f"2. If DB fails, impacted: {impact}")
    
    impact = aggregator.get_dependency_impact("cache")
    print(f"   If cache fails, impacted: {impact}")
    
    print("\nR220 Health Check Aggregator ready.")

run_health_demo()
