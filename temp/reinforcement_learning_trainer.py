#!/usr/bin/env python3
"""
Reinforcement Learning Trainer for GenericAgent
强化学习训练器: DQN、策略梯度、PPO简化版、经验回放
支持: 环境模拟、Q学习、Actor-Critic、奖励塑形
"""

import os
import json
import math
import random
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Callable
from dataclasses import dataclass, field
from collections import deque

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

@dataclass
class Experience:
    state: List[float]
    action: int
    reward: float
    next_state: List[float]
    done: bool

@dataclass
class TrainingMetrics:
    episode: int
    total_reward: float
    avg_loss: float = 0.0
    epsilon: float = 1.0


class SimpleEnv:
    """Simplified RL Environment (CartPole-like)"""
    def __init__(self, state_dim: int = 4, action_dim: int = 2):
        self.state_dim = state_dim
        self.action_dim = action_dim
        self.state = [0.0] * state_dim
        self.step_count = 0
        self.max_steps = 200
    
    def reset(self) -> List[float]:
        self.state = [random.uniform(-0.05, 0.05) for _ in range(self.state_dim)]
        self.step_count = 0
        return self.state
    
    def step(self, action: int) -> Tuple[List[float], float, bool]:
        self.step_count += 1
        # Simulate dynamics
        force = 1.0 if action == 1 else -1.0
        self.state[0] += 0.02 * self.state[1]
        self.state[1] += 0.02 * (force + math.cos(self.state[0]) * 9.8)
        self.state = [max(-4.0, min(4.0, s)) for s in self.state]
        
        reward = 1.0 if abs(self.state[0]) < 0.5 else -10.0
        done = abs(self.state[0]) > 2.4 or self.step_count >= self.max_steps
        return self.state, reward, done


class DQNAgent:
    """Deep Q-Network Agent (simplified tabular approximation)"""
    def __init__(self, state_dim: int = 4, action_dim: int = 2, hidden_dim: int = 16,
                 lr: float = 0.01, gamma: float = 0.99, epsilon: float = 1.0,
                 epsilon_decay: float = 0.995, epsilon_min: float = 0.01,
                 batch_size: int = 32, memory_size: int = 2000):
        self.state_dim = state_dim
        self.action_dim = action_dim
        self.hidden_dim = hidden_dim
        self.lr = lr
        self.gamma = gamma
        self.epsilon = epsilon
        self.epsilon_decay = epsilon_decay
        self.epsilon_min = epsilon_min
        self.batch_size = batch_size
        
        # Simplified Q-network (linear approximation)
        self.weights = [[random.uniform(-0.1, 0.1) for _ in range(state_dim + 1)] 
                        for _ in range(action_dim)]
        
        self.memory = deque(maxlen=memory_size)
    
    def _q_values(self, state: List[float]) -> List[float]:
        return [sum(w[j] * (state[j] if j < len(state) else 1.0) 
                    for j in range(len(state) + 1)) 
                for w in self.weights]
    
    def act(self, state: List[float]) -> int:
        if random.random() < self.epsilon:
            return random.randint(0, self.action_dim - 1)
        q_vals = self._q_values(state)
        return q_vals.index(max(q_vals))
    
    def remember(self, experience: Experience):
        self.memory.append(experience)
    
    def replay(self) -> float:
        if len(self.memory) < self.batch_size:
            return 0.0
        
        batch = random.sample(list(self.memory), self.batch_size)
        total_loss = 0.0
        
        for exp in batch:
            q_vals = self._q_values(exp.state)
            target_q = list(q_vals)
            
            if exp.done:
                target_q[exp.action] = exp.reward
            else:
                next_q = self._q_values(exp.next_state)
                target_q[exp.action] = exp.reward + self.gamma * max(next_q)
            
            # Update weights
            error = target_q[exp.action] - q_vals[exp.action]
            total_loss += error ** 2
            for j in range(len(exp.state) + 1):
                x = exp.state[j] if j < len(exp.state) else 1.0
                self.weights[exp.action][j] += self.lr * error * x
        
        self.epsilon = max(self.epsilon_min, self.epsilon * self.epsilon_decay)
        return total_loss / len(batch)


class PolicyGradient:
    """REINFORCE Policy Gradient Agent"""
    def __init__(self, state_dim: int = 4, action_dim: int = 2, lr: float = 0.01, gamma: float = 0.99):
        self.state_dim = state_dim
        self.action_dim = action_dim
        self.lr = lr
        self.gamma = gamma
        self.policy_weights = [[random.uniform(-0.1, 0.1) for _ in range(state_dim + 1)]
                               for _ in range(action_dim)]
    
    def _logits(self, state: List[float]) -> List[float]:
        return [sum(w[j] * (state[j] if j < len(state) else 1.0) 
                    for j in range(len(state) + 1))
                for w in self.policy_weights]
    
    def _softmax(self, logits: List[float]) -> List[float]:
        max_l = max(logits)
        exp_l = [math.exp(l - max_l) for l in logits]
        total = sum(exp_l)
        return [e / total for e in exp_l]
    
    def act(self, state: List[float]) -> int:
        probs = self._softmax(self._logits(state))
        r = random.random()
        cum = 0.0
        for i, p in enumerate(probs):
            cum += p
            if r < cum:
                return i
        return len(probs) - 1
    
    def update(self, trajectories: List[List[Tuple]]):
        for trajectory in trajectories:
            T = len(trajectory)
            for t, (state, action, reward) in enumerate(trajectory):
                # Compute discounted return
                G = sum(self.gamma ** (k - t) * r for k, (_, _, r) in enumerate(trajectory[t:]))
                
                logits = self._logits(state)
                probs = self._softmax(logits)
                
                # Policy gradient update
                for a in range(self.action_dim):
                    indicator = 1.0 if a == action else 0.0
                    grad = (indicator - probs[a])
                    for j in range(len(state) + 1):
                        x = state[j] if j < len(state) else 1.0
                        self.policy_weights[a][j] += self.lr * G * grad * x


class PPOAgent:
    """Proximal Policy Optimization (simplified)"""
    def __init__(self, state_dim: int = 4, action_dim: int = 2, lr: float = 0.001, 
                 gamma: float = 0.99, clip_epsilon: float = 0.2, n_epochs: int = 4):
        self.state_dim = state_dim
        self.action_dim = action_dim
        self.lr = lr
        self.gamma = gamma
        self.clip_epsilon = clip_epsilon
        self.n_epochs = n_epochs
        self.policy_weights = [[random.uniform(-0.1, 0.1) for _ in range(state_dim + 1)]
                               for _ in range(action_dim)]
        self.value_weights = [random.uniform(-0.1, 0.1) for _ in range(state_dim + 1)]
    
    def _policy_logits(self, state: List[float]) -> List[float]:
        return [sum(w[j] * (state[j] if j < len(state) else 1.0) 
                    for j in range(len(state) + 1))
                for w in self.policy_weights]
    
    def _value(self, state: List[float]) -> float:
        return sum(w[j] * (state[j] if j < len(state) else 1.0) 
                   for j, w in enumerate(self.value_weights))
    
    def act(self, state: List[float]) -> int:
        logits = self._policy_logits(state)
        max_l = max(logits)
        exp_l = [math.exp(l - max_l) for l in logits]
        total = sum(exp_l)
        probs = [e / total for e in exp_l]
        r = random.random()
        cum = 0.0
        for i, p in enumerate(probs):
            cum += p
            if r < cum:
                return i
        return len(probs) - 1
    
    def update(self, experiences: List[Experience], old_probs: List[List[float]]):
        for epoch in range(self.n_epochs):
            for exp, old_p in zip(experiences, old_probs):
                # Compute advantage (simplified GAE)
                v = self._value(exp.state)
                v_next = 0.0 if exp.done else self._value(exp.next_state)
                advantage = exp.reward + self.gamma * v_next - v
                
                # Clipped surrogate objective
                logits = self._policy_logits(exp.state)
                max_l = max(logits)
                exp_l = [math.exp(l - max_l) for l in logits]
                total = sum(exp_l)
                new_probs = [e / total for e in exp_l]
                
                ratio = new_probs[exp.action] / (old_p[exp.action] + 1e-10)
                clipped_ratio = max(1 - self.clip_epsilon, min(1 + self.clip_epsilon, ratio))
                surrogate = min(ratio * advantage, clipped_ratio * advantage)
                
                # Update policy
                for j in range(len(exp.state) + 1):
                    x = exp.state[j] if j < len(exp.state) else 1.0
                    for a in range(self.action_dim):
                        grad = (1.0 if a == exp.action else 0.0) - new_probs[a]
                        self.policy_weights[a][j] += self.lr * surrogate * grad * 0.1
                
                # Update value function
                value_error = (exp.reward + self.gamma * v_next - v) ** 2
                for j in range(len(exp.state) + 1):
                    x = exp.state[j] if j < len(exp.state) else 1.0
                    self.value_weights[j] += self.lr * value_error * x * 0.1


if __name__ == '__main__':
    print("=== Reinforcement Learning Trainer ===")
    
    # Test DQN
    print("\n--- DQN Agent ---")
    env = SimpleEnv()
    agent = DQNAgent(state_dim=4, action_dim=2)
    
    for episode in range(50):
        state = env.reset()
        total_reward = 0.0
        done = False
        
        while not done:
            action = agent.act(state)
            next_state, reward, done = env.step(action)
            agent.remember(Experience(state, action, reward, next_state, done))
            state = next_state
            total_reward += reward
        
        loss = agent.replay()
        if episode % 10 == 0:
            print(f"  Episode {episode}: reward={total_reward:.1f}, epsilon={agent.epsilon:.3f}, loss={loss:.4f}")
    
    # Test Policy Gradient
    print("\n--- Policy Gradient Agent ---")
    pg_agent = PolicyGradient(state_dim=4, action_dim=2)
    
    for episode in range(30):
        state = env.reset()
        trajectory = []
        total_reward = 0.0
        done = False
        
        while not done:
            action = pg_agent.act(state)
            next_state, reward, done = env.step(action)
            trajectory.append((state, action, reward))
            state = next_state
            total_reward += reward
        
        pg_agent.update([trajectory])
        if episode % 10 == 0:
            print(f"  Episode {episode}: reward={total_reward:.1f}")
    
    # Test PPO
    print("\n--- PPO Agent ---")
    ppo_agent = PPOAgent(state_dim=4, action_dim=2)
    
    for episode in range(20):
        state = env.reset()
        experiences = []
        old_probs = []
        total_reward = 0.0
        done = False
        
        while not done:
            action = ppo_agent.act(state)
            logits = ppo_agent._policy_logits(state)
            max_l = max(logits)
            exp_l = [math.exp(l - max_l) for l in logits]
            total = sum(exp_l)
            probs = [e / total for e in exp_l]
            old_probs.append(probs)
            
            next_state, reward, done = env.step(action)
            experiences.append(Experience(state, action, reward, next_state, done))
            state = next_state
            total_reward += reward
        
        ppo_agent.update(experiences, old_probs)
        if episode % 5 == 0:
            print(f"  Episode {episode}: reward={total_reward:.1f}")
