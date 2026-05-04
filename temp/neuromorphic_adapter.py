#!/usr/bin/env python3
"""
Neuromorphic Computing Adapter for GenericAgent
类脑计算适配器: 脉冲神经网络(SNN)模拟、事件驱动计算、突触可塑性
支持: LIF神经元模型、STDP学习规则、事件队列、神经形态编码
"""

import os
import json
import time
import math
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Callable
from collections import deque
from dataclasses import dataclass

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

@dataclass
class LIFNeuron:
    """Leaky Integrate-and-Fire Neuron"""
    neuron_id: str
    membrane_potential: float = 0.0
    threshold: float = 1.0
    leak_rate: float = 0.1
    refractory_period: float = 0.002
    last_spike_time: float = -1.0
    spike_count: int = 0

@dataclass
class Synapse:
    pre_id: str
    post_id: str
    weight: float = 0.5
    delay: float = 0.001
    trace_pre: float = 0.0
    trace_post: float = 0.0


class STDP:
    """Spike-Timing-Dependent Plasticity"""
    def __init__(self, A_plus: float = 0.01, A_minus: float = 0.012,
                 tau_plus: float = 0.02, tau_minus: float = 0.02):
        self.A_plus = A_plus
        self.A_minus = A_minus
        self.tau_plus = tau_plus
        self.tau_minus = tau_minus
    
    def update(self, synapse: Synapse, t_pre: float, t_post: float) -> float:
        dt = t_post - t_pre
        if dt > 0:
            delta_w = self.A_plus * math.exp(-dt / self.tau_plus)
        else:
            delta_w = -self.A_minus * math.exp(dt / self.tau_minus)
        
        synapse.weight = max(0.0, min(1.0, synapse.weight + delta_w))
        return synapse.weight


class SpikeEvent:
    def __init__(self, neuron_id: str, timestamp: float, source: str = ""):
        self.neuron_id = neuron_id
        self.timestamp = timestamp
        self.source = source


class SpikingNeuralNetwork:
    def __init__(self, time_step: float = 0.001, stdp_enabled: bool = True):
        self.dt = time_step
        self.current_time = 0.0
        self.neurons: Dict[str, LIFNeuron] = {}
        self.synapses: Dict[Tuple[str, str], Synapse] = {}
        self.spike_queue: deque = deque()
        self.spike_history: List[SpikeEvent] = []
        self.stdp = STDP() if stdp_enabled else None
        self.event_callbacks: List[Callable] = []
    
    def add_neuron(self, neuron_id: str, threshold: float = 1.0, leak_rate: float = 0.1) -> LIFNeuron:
        neuron = LIFNeuron(neuron_id=neuron_id, threshold=threshold, leak_rate=leak_rate)
        self.neurons[neuron_id] = neuron
        return neuron
    
    def add_synapse(self, pre_id: str, post_id: str, weight: float = 0.5, delay: float = 0.001) -> Synapse:
        synapse = Synapse(pre_id=pre_id, post_id=post_id, weight=weight, delay=delay)
        self.synapses[(pre_id, post_id)] = synapse
        return synapse
    
    def inject_current(self, neuron_id: str, current: float):
        if neuron_id in self.neurons:
            self.neurons[neuron_id].membrane_potential += current * self.dt
    
    def step(self):
        """Simulate one time step"""
        self.current_time += self.dt
        
        # Update neurons
        spikes_now = []
        for nid, neuron in self.neurons.items():
            if self.current_time < neuron.last_spike_time + neuron.refractory_period:
                continue
            
            # Leak
            neuron.membrane_potential *= (1.0 - neuron.leak_rate * self.dt)
            
            # Check threshold
            if neuron.membrane_potential >= neuron.threshold:
                neuron.membrane_potential = 0.0
                neuron.last_spike_time = self.current_time
                neuron.spike_count += 1
                spikes_now.append(nid)
                self.spike_history.append(SpikeEvent(nid, self.current_time))
        
        # Process STDP
        if self.stdp:
            for nid in spikes_now:
                for (pre, post), syn in self.synapses.items():
                    if pre == nid:
                        syn.trace_pre = self.current_time
                        if syn.trace_post > 0:
                            self.stdp.update(syn, syn.trace_pre, syn.trace_post)
                    if post == nid:
                        syn.trace_post = self.current_time
                        if syn.trace_pre > 0:
                            self.stdp.update(syn, syn.trace_pre, syn.trace_post)
        
        # Propagate spikes through synapses
        for nid in spikes_now:
            for (pre, post), syn in self.synapses.items():
                if pre == nid:
                    self.neurons[post].membrane_potential += syn.weight
        
        # Notify callbacks
        for cb in self.event_callbacks:
            for nid in spikes_now:
                cb(nid, self.current_time)
    
    def simulate(self, duration: float, input_func: Callable = None):
        steps = int(duration / self.dt)
        for _ in range(steps):
            if input_func:
                input_func(self, self.current_time)
            self.step()
    
    def get_spike_raster(self) -> List[Dict]:
        return [{'neuron': e.neuron_id, 'time': e.timestamp} for e in self.spike_history]
    
    def get_firing_rates(self, window: float = 1.0) -> Dict[str, float]:
        cutoff = self.current_time - window
        counts = {}
        for e in self.spike_history:
            if e.timestamp > cutoff:
                counts[e.neuron_id] = counts.get(e.neuron_id, 0) + 1
        return {nid: cnt / window for nid, cnt in counts.items()}


class NeuromorphicEncoder:
    @staticmethod
    def rate_encode(value: float, max_rate: int = 100) -> List[float]:
        """Rate coding: value -> spike probability"""
        return [1.0 if (i / max_rate) < value else 0.0 for i in range(max_rate)]
    
    @staticmethod
    def temporal_encode(sequence: List[float]) -> List[float]:
        """Temporal coding: value -> spike latency"""
        return [1.0 - x for x in sequence if 0 <= x <= 1]


if __name__ == '__main__':
    snn = SpikingNeuralNetwork(time_step=0.001)
    
    # Create a simple network
    snn.add_neuron("input_1", threshold=0.8)
    snn.add_neuron("input_2", threshold=0.8)
    snn.add_neuron("hidden_1", threshold=1.0)
    snn.add_neuron("output_1", threshold=1.2)
    
    snn.add_synapse("input_1", "hidden_1", weight=0.6)
    snn.add_synapse("input_2", "hidden_1", weight=0.4)
    snn.add_synapse("hidden_1", "output_1", weight=0.7)
    
    # Input function
    def step_input(snn, t):
        if 0.01 < t < 0.05:
            snn.inject_current("input_1", 15.0)
        if 0.03 < t < 0.07:
            snn.inject_current("input_2", 10.0)
    
    print("=== SNN Simulation ===")
    snn.simulate(0.1, step_input)
    
    print(f"Total spikes: {len(snn.spike_history)}")
    rates = snn.get_firing_rates(window=0.1)
    print(f"Firing rates: {json.dumps(rates, indent=2)}")
    
    print("\n=== Neuromorphic Encoding ===")
    encoded = NeuromorphicEncoder.rate_encode(0.3, max_rate=10)
    print(f"Rate encode(0.3): {encoded}")
    print(f"Temporal encode([0.1, 0.5, 0.9]): {NeuromorphicEncoder.temporal_encode([0.1, 0.5, 0.9])}")
