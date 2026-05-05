#!/usr/bin/env python3
"""Strategy Pattern - Interchangeable algorithms for sorting, compression, and encryption"""
from typing import List, Any, Callable
from abc import ABC, abstractmethod
import time

class SortStrategy(ABC):
    @abstractmethod
    def sort(self, data: List[Any]) -> List[Any]:
        pass
    
    @property
    @abstractmethod
    def name(self) -> str:
        pass

class QuickSort(SortStrategy):
    def sort(self, data: List[Any]) -> List[Any]:
        if len(data) <= 1:
            return data
        pivot = data[len(data) // 2]
        left = [x for x in data if x < pivot]
        middle = [x for x in data if x == pivot]
        right = [x for x in data if x > pivot]
        return self.sort(left) + middle + self.sort(right)
    
    @property
    def name(self) -> str:
        return "QuickSort"

class MergeSort(SortStrategy):
    def sort(self, data: List[Any]) -> List[Any]:
        if len(data) <= 1:
            return data
        mid = len(data) // 2
        left = self.sort(data[:mid])
        right = self.sort(data[mid:])
        return self._merge(left, right)
    
    def _merge(self, left, right):
        result = []
        i = j = 0
        while i < len(left) and j < len(right):
            if left[i] <= right[j]:
                result.append(left[i])
                i += 1
            else:
                result.append(right[j])
                j += 1
        result.extend(left[i:])
        result.extend(right[j:])
        return result
    
    @property
    def name(self) -> str:
        return "MergeSort"

class CompressionStrategy(ABC):
    @abstractmethod
    def compress(self, data: str) -> bytes:
        pass
    
    @abstractmethod
    def decompress(self, data: bytes) -> str:
        pass
    
    @property
    @abstractmethod
    def name(self) -> str:
        pass

class RunLengthCompression(CompressionStrategy):
    def compress(self, data: str) -> bytes:
        if not data:
            return b""
        result = []
        count = 1
        for i in range(1, len(data)):
            if data[i] == data[i-1]:
                count += 1
            else:
                result.append((count, data[i-1]))
                count = 1
        result.append((count, data[-1]))
        return str(result).encode()
    
    def decompress(self, data: bytes) -> str:
        pairs = eval(data.decode())
        return "".join(char * count for count, char in pairs)
    
    @property
    def name(self) -> str:
        return "RLE"

class CompressionContext:
    def __init__(self, strategy: CompressionStrategy):
        self._strategy = strategy
    
    @property
    def strategy(self):
        return self._strategy
    
    @strategy.setter
    def strategy(self, strategy: CompressionStrategy):
        self._strategy = strategy
    
    def compress(self, data: str) -> bytes:
        return self._strategy.compress(data)
    
    def decompress(self, data: bytes) -> str:
        return self._strategy.decompress(data)

class SortContext:
    def __init__(self, strategy: SortStrategy):
        self._strategy = strategy
    
    @property
    def strategy(self):
        return self._strategy
    
    @strategy.setter
    def strategy(self, strategy: SortStrategy):
        self._strategy = strategy
    
    def sort(self, data: List[Any]) -> List[Any]:
        return self._strategy.sort(data)

if __name__ == "__main__":
    import random
    data = [random.randint(1, 1000) for _ in range(100)]
    
    # Sort strategies
    ctx = SortContext(QuickSort())
    sorted_data = ctx.sort(data.copy())
    print(f"{ctx.strategy.name}: {len(sorted_data)} items sorted, valid={sorted_data == sorted(sorted_data)}")
    
    ctx.strategy = MergeSort()
    sorted_data = ctx.sort(data.copy())
    print(f"{ctx.strategy.name}: {len(sorted_data)} items sorted, valid={sorted_data == sorted(sorted_data)}")
    
    # Compression strategies
    ctx2 = CompressionContext(RunLengthCompression())
    original = "AAAABBBCCDAA" * 100
    compressed = ctx2.compress(original)
    decompressed = ctx2.decompress(compressed)
    ratio = len(compressed) / len(original) * 100
    print(f"{ctx2.strategy.name}: {len(original)} -> {len(compressed)} bytes ({ratio:.1f}%), match={decompressed == original}")
    
    print("\nStrategy pattern ready.")
