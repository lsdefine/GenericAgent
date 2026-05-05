#!/usr/bin/env python3
"""Command Pattern - Encapsulates requests as objects with undo/redo and queuing"""
from typing import List, Optional, Any, Dict
from abc import ABC, abstractmethod
import time

class Command(ABC):
    @abstractmethod
    def execute(self) -> Any:
        pass
    
    @abstractmethod
    def undo(self) -> Any:
        pass
    
    @property
    @abstractmethod
    def description(self) -> str:
        pass

class CommandInvoker:
    def __init__(self):
        self._history: List[Command] = []
        self._redo_stack: List[Command] = []
        self._macro_commands: List[Command] = []
    
    def execute(self, command: Command) -> Any:
        result = command.execute()
        self._history.append(command)
        self._redo_stack.clear()
        return result
    
    def undo(self) -> Optional[Command]:
        if self._history:
            command = self._history.pop()
            command.undo()
            self._redo_stack.append(command)
            return command
        return None
    
    def redo(self) -> Optional[Command]:
        if self._redo_stack:
            command = self._redo_stack.pop()
            command.execute()
            self._history.append(command)
            return command
        return None
    
    def execute_macro(self, commands: List[Command]) -> List[Any]:
        results = []
        for cmd in commands:
            try:
                result = cmd.execute()
                self._history.append(cmd)
                results.append(result)
            except Exception as e:
                # Rollback executed commands
                for executed in reversed([c for c in self._history[-len(commands):] if c in commands]):
                    executed.undo()
                raise e
        return results
    
    def get_history(self) -> List[str]:
        return [c.description for c in self._history]

class TextEditor:
    def __init__(self):
        self.content = ""
        self.clipboard = ""
    
    def insert(self, text: str):
        self.content += text
    
    def delete(self, count: int) -> str:
        deleted = self.content[-count:] if count <= len(self.content) else self.content
        self.content = self.content[:-count] if count <= len(self.content) else ""
        return deleted
    
    def copy(self, count: int):
        self.clipboard = self.content[-count:] if count <= len(self.content) else self.content

class InsertCommand(Command):
    def __init__(self, editor: TextEditor, text: str):
        self.editor = editor
        self.text = text
        self.inserted_len = len(text)
    
    def execute(self):
        self.editor.insert(self.text)
    
    def undo(self):
        self.editor.delete(self.inserted_len)
    
    @property
    def description(self) -> str:
        return f"Insert '{self.text}'"

class DeleteCommand(Command):
    def __init__(self, editor: TextEditor, count: int):
        self.editor = editor
        self.count = count
        self.deleted_text = ""
    
    def execute(self):
        self.deleted_text = self.editor.delete(self.count)
    
    def undo(self):
        self.editor.insert(self.deleted_text)
    
    @property
    def description(self) -> str:
        return f"Delete {self.count} chars"

if __name__ == "__main__":
    editor = TextEditor()
    invoker = CommandInvoker()
    
    cmd1 = InsertCommand(editor, "Hello ")
    cmd2 = InsertCommand(editor, "World")
    cmd3 = DeleteCommand(editor, 5)
    
    invoker.execute(cmd1)
    invoker.execute(cmd2)
    print(f"Content: '{editor.content}'")
    
    invoker.undo()
    print(f"After undo delete: '{editor.content}'")
    
    invoker.execute(cmd3)
    print(f"After delete: '{editor.content}'")
    
    invoker.undo()
    print(f"After undo delete: '{editor.content}'")
    
    invoker.redo()
    print(f"After redo delete: '{editor.content}'")
    
    # Macro test
    editor2 = TextEditor()
    invoker2 = CommandInvoker()
    macro = [InsertCommand(editor2, "A"), InsertCommand(editor2, "B"), InsertCommand(editor2, "C")]
    invoker2.execute_macro(macro)
    print(f"Macro result: '{editor2.content}'")
    
    print(f"History: {invoker.get_history()}")
    print("Command pattern ready.")
