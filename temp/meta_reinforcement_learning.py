#!/usr/bin/env python3
"""
Meta-Reinforcement Learning for GenericAgent
元强化学习: MAML-RL、策略元学习、快速适应新环境
支持: 少样本适应、任务分布学习、元梯度更新
"""

import os
import json
import math
import logging
from typing import Dict, List, Optional, Tuple, Callable
from dataclasses import dataclass, field
import random

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

@dataclass
class Task:
    task_id: str
    dynamics: Dict  # Environment dynamics parameters
    reward_fn: Callable
    observation_dim: int
    action_dim: int

@dataclass
class Trajectory:
    states: List[List[float]]
    actions: List[int]
    rewards: List[float]
    done: bool

@dataclass
class Policy:
    weights: Dict[str, List[float]]
    learning_rate: float = 0.01


class MAMLPolicy:
    """MAML-based policy for meta-RL"""
    def __init__(self, observation_dim: int = 4, action_dim: int = 2, hidden_dim: int = 16):
        self.observation_dim = observation_dim
        self.action_dim = action_dim
        self.hidden_dim = hidden_dim
        
        # Initialize meta-parameters
        self.meta_weights = {
            'fc1': [random.uniform(-0.1, 0.1) for _ in range(observation_dim * hidden_dim)],
            'fc2': [random.uniform(-0.1, 0.1) for _ in range(hidden_dim * hidden_dim)],
            'output': [random.uniform(-0.1, 0.1) for _ in range(hidden_dim * action_dim)]
        }
        self.meta_lr = 0.001  # Outer loop learning rate
    
    def copy_weights(self) -> Dict[str, List[float]]:
        return {k: list(v) for k, v in self.meta_weights.items()}
    
    def load_weights(self, weights: Dict[str, List[float]]):
        self.meta_weights = {k: list(v) for k, v in weights.items()}
    
    def forward(self, state: List[float], weights: Dict[str, List[float]]) -> List[float]:
        """Forward pass with given weights"""
        h1_dim = self.hidden_dim
        h1 = [0.0] * h1_dim
        
        for i in range(h1_dim):
            for j in range(self.observation_dim):
                idx = i * self.observation_dim + j
                if idx < len(weights['fc1']) and j < len(state):
                    h1[i] += weights['fc1'][idx] * state[j]
            h1[i] = max(0, h1[i])  # ReLU
        
        h2 = [0.0] * h1_dim
        for i in range(h1_dim):
            for j in range(h1_dim):
                idx = i * h1_dim + j
                if idx < len(weights['fc2']):
                    h2[i] += weights['fc2'][idx] * h1[j]
            h2[i] = max(0, h2[i])
        
        output = [0.0] * self.action_dim
        for i in range(self.action_dim):
            for j in range(h1_dim):
                idx = i * h1_dim + j
                if idx < len(weights['output']):
                    output[i] += weights['output'][idx] * h2[j]
        
        # Softmax
        max_o = max(output)
        exp_o = [math.exp(o - max_o) for o in output]
        total = sum(exp_o)
        return [e / total for e in exp_o]
    
    def adapt(self, task: Task, trajectory: Trajectory, inner_lr: float = 0.01) -> Dict[str, List[float]]:
        """Inner loop adaptation: gradient update on single task"""
        theta = self.copy_weights()
        
        # Compute policy gradient from trajectory
        for t in range(len(trajectory.rewards)):
            state = trajectory.states[t]
            action = trajectory.actions[t]
            reward = trajectory.rewards[t]
            
            # Forward pass
            probs = self.forward(state, theta)
            
            # Policy gradient (REINFORCE)
            grad_scale = reward * (1 - probs[action])
            
            # Update output layer
            for j in range(self.hidden_dim):
                idx = action * self.hidden_dim + j
                if idx < len(theta['output']):
                    theta['output'][idx] += inner_lr * grad_scale * 0.1  # Simplified
        
        return theta
    
    def meta_update(self, task_gradients: List[Dict[str, List[float]]]) -> Dict[str, List[float]]:
        """Outer loop: meta-gradient update across tasks"""
        if not task_gradients:
            return self.meta_weights
        
        # Average gradients
        avg_grad = {}
        for key in self.meta_weights:
            grad_list = [tg.get(key, [0.0] * len(self.meta_weights[key])) for tg in task_gradients]
            n = len(self.meta_weights[key])
            avg_grad[key] = [
                sum(g[i] for g in grad_list) / len(grad_list)
                for i in range(n)
            ]
        
        # Update meta-weights
        for key in self.meta_weights:
            for i in range(len(self.meta_weights[key])):
                self.meta_weights[key][i] += self.meta_lr * avg_grad[key][i]
        
        return self.meta_weights


class TaskSampler:
    """Sample tasks from task distribution"""
    def __init__(self):
        self.tasks: List[Task] = []
    
    def generate_task(self, task_id: str, difficulty: float = 0.5) -> Task:
        """Generate a new task with specified difficulty"""
        return Task(
            task_id=task_id,
            dynamics={
                'friction': random.uniform(0.1, 0.5) * difficulty,
                'gravity': random.uniform(8, 12) * difficulty,
                'mass': random.uniform(0.5, 2.0) * difficulty
            },
            reward_fn=lambda s, a: -sum((x - 0.5)**2 for x in s[:2]),
            observation_dim=4,
            action_dim=2
        )
    
    def sample_tasks(self, n: int) -> List[Task]:
        """Sample n tasks"""
        tasks = []
        for i in range(n):
            task = self.generate_task(f"task_{i}", difficulty=random.uniform(0.3, 0.8))
            tasks.append(task)
            self.tasks.append(task)
        return tasks


class MetaRLTrainer:
    """Main meta-RL training orchestrator"""
    def __init__(self, n_inner_steps: int = 5, n_outer_steps: int = 100,
                 inner_lr: float = 0.01, meta_lr: float = 0.001,
                 n_tasks_per_batch: int = 5):
        self.n_inner_steps = n_inner_steps
        self.n_outer_steps = n_outer_steps
        self.inner_lr = inner_lr
        self.meta_lr = meta_lr
        self.n_tasks_per_batch = n_tasks_per_batch
        
        self.policy = MAMLPolicy()
        self.task_sampler = TaskSampler()
        self.task_history: Dict[str, List[float]] = {}
    
    def collect_trajectory(self, task: Task, policy_weights: Dict) -> Trajectory:
        """Rollout trajectory using current policy"""
        states = []
        actions = []
        rewards = []
        
        state = [random.uniform(-1, 1) for _ in range(task.observation_dim)]
        
        for step in range(10):  # Max episode length
            probs = self.policy.forward(state, policy_weights)
            action = random.choices(range(task.action_dim), weights=probs)[0]
            
            # Simplified transition
            next_state = [s + random.uniform(-0.1, 0.1) for s in state]
            reward = task.reward_fn(state, action)
            
            states.append(state)
            actions.append(action)
            rewards.append(reward)
            
            state = next_state
        
        return Trajectory(states=states, actions=actions, rewards=rewards, done=True)
    
    def train(self) -> Dict:
        """Run meta-RL training"""
        for outer_iter in range(self.n_outer_steps):
            # Sample task batch
            tasks = self.task_sampler.sample_tasks(self.n_tasks_per_batch)
            
            task_gradients = []
            total_reward = 0
            
            for task in tasks:
                # Inner loop adaptation
                adapted_weights = self.policy.copy_weights()
                
                for inner_step in range(self.n_inner_steps):
                    trajectory = self.collect_trajectory(task, adapted_weights)
                    adapted_weights = self.policy.adapt(task, trajectory, self.inner_lr)
                    total_reward += sum(trajectory.rewards)
                
                # Compute gradient as difference
                grad = {
                    key: [adapted_weights[key][i] - self.policy.meta_weights[key][i]
                          for i in range(len(self.policy.meta_weights[key]))]
                    for key in self.policy.meta_weights
                }
                task_gradients.append(grad)
            
            # Meta-update
            self.policy.meta_update(task_gradients)
            
            if outer_iter % 20 == 0:
                avg_reward = total_reward / (self.n_tasks_per_batch * 10)
                logger.info(f"Outer iter {outer_iter}: avg_reward={avg_reward:.4f}")
        
        return {
            'meta_weights': self.policy.copy_weights(),
            'n_tasks_seen': len(self.task_sampler.tasks),
            'training_complete': True
        }


if __name__ == '__main__':
    print("=== Meta-Reinforcement Learning (MAML-RL) ===")
    
    trainer = MetaRLTrainer(n_outer_steps=50, n_tasks_per_batch=3, n_inner_steps=3)
    result = trainer.train()
    
    print(f"\nTraining complete!")
    print(f"Tasks seen: {result['n_tasks_seen']}")
    print(f"Meta-parameters: {list(result['meta_weights'].keys())}")
