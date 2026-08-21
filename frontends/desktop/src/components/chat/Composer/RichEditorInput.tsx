import { useRef, useCallback, useEffect, useImperativeHandle, forwardRef } from 'react';
import { composerPlainText, normalizeComposerDom, replaceAllContent, insertChipWithSpace, replaceWithSkillChip } from './rich-editor';

export interface RichEditorHandle {
  focus: () => void;
  clear: () => void;
  getText: () => string;
  setText: (text: string) => void;
  insertChip: (kind: string, value: string, label?: string) => void;
  setSkillChip: (id: string, prompt: string) => void;
  getElement: () => HTMLDivElement | null;
}

interface Props {
  placeholder: string;
  disabled: boolean;
  onInput: (plainText: string) => void;
  onKeyDown: (e: React.KeyboardEvent) => void;
  onSlashTrigger?: (query: string) => void;
  onSlashDismiss?: () => void;
  onAtTrigger?: (query: string) => void;
  onAtDismiss?: () => void;
  onPasteFiles?: (files: File[]) => void;
}

export const RichEditorInput = forwardRef<RichEditorHandle, Props>(function RichEditorInput(
  { placeholder, disabled, onInput, onKeyDown, onSlashTrigger, onSlashDismiss, onAtTrigger, onAtDismiss, onPasteFiles },
  ref,
) {
  const editorRef = useRef<HTMLDivElement>(null);
  const isComposingRef = useRef(false);
  const lastTextRef = useRef('');

  useImperativeHandle(ref, () => ({
    focus() {
      editorRef.current?.focus();
    },
    clear() {
      if (editorRef.current) {
        editorRef.current.textContent = '';
        lastTextRef.current = '';
      }
    },
    getText() {
      return editorRef.current ? composerPlainText(editorRef.current) : '';
    },
    setText(text: string) {
      if (editorRef.current) {
        replaceAllContent(editorRef.current, text);
        lastTextRef.current = text;
        onInput(text);
      }
    },
    insertChip(kind: string, value: string, label?: string) {
      if (editorRef.current) {
        editorRef.current.focus();
        insertChipWithSpace(editorRef.current, kind, value, label);
        fireInput();
      }
    },
    setSkillChip(id: string, prompt: string) {
      if (editorRef.current) {
        replaceWithSkillChip(editorRef.current, id, prompt);
        fireInput();
      }
    },
    getElement() {
      return editorRef.current;
    },
  }));

  const fireInput = useCallback(() => {
    if (!editorRef.current) return;
    const text = composerPlainText(editorRef.current);
    lastTextRef.current = text;
    onInput(text);

    // Slash trigger detection
    const trimmed = text.trimStart();
    if (trimmed.startsWith('/') && !trimmed.includes('\n')) {
      onSlashTrigger?.(trimmed.slice(1));
    } else {
      onSlashDismiss?.();
    }

    // @ trigger detection: find last `@` not inside a chip
    const atMatch = text.match(/@([^\s@]*)$/);
    if (atMatch) {
      onAtTrigger?.(atMatch[1]);
    } else {
      onAtDismiss?.();
    }
  }, [onInput, onSlashTrigger, onSlashDismiss, onAtTrigger, onAtDismiss]);

  const handleInput = useCallback(() => {
    if (isComposingRef.current) return;
    if (editorRef.current) {
      normalizeComposerDom(editorRef.current);
    }
    fireInput();
  }, [fireInput]);

  const handleCompositionStart = useCallback(() => {
    isComposingRef.current = true;
  }, []);

  const handleCompositionEnd = useCallback(() => {
    isComposingRef.current = false;
    handleInput();
  }, [handleInput]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (isComposingRef.current || e.nativeEvent.isComposing || e.keyCode === 229) return;
    onKeyDown(e);
  }, [onKeyDown]);

  const handlePaste = useCallback((e: React.ClipboardEvent) => {
    const items = e.clipboardData?.items;
    if (!items) return;

    // Check for images
    const imageFiles: File[] = [];
    for (const item of Array.from(items)) {
      if (item.type.startsWith('image/') && item.type !== 'image/svg+xml') {
        const file = item.getAsFile();
        if (file) imageFiles.push(file);
      }
    }
    if (imageFiles.length > 0) {
      e.preventDefault();
      onPasteFiles?.(imageFiles);
      return;
    }

    // For text, paste as plain text only
    const text = e.clipboardData.getData('text/plain');
    if (text) {
      e.preventDefault();
      document.execCommand('insertText', false, text);
    }
  }, [onPasteFiles]);

  // Auto-resize via measured height
  useEffect(() => {
    const el = editorRef.current;
    if (!el) return;
    const observer = new ResizeObserver((entries) => {
      const height = entries[0]?.borderBoxSize?.[0]?.blockSize ?? el.offsetHeight;
      el.style.setProperty('--editor-scroll-height', `${height}px`);
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  return (
    <div
      ref={editorRef}
      data-slot="composer-rich-input"
      contentEditable={!disabled}
      role="textbox"
      aria-multiline="true"
      aria-placeholder={placeholder}
      data-placeholder={placeholder}
      suppressContentEditableWarning
      onInput={handleInput}
      onKeyDown={handleKeyDown}
      onCompositionStart={handleCompositionStart}
      onCompositionEnd={handleCompositionEnd}
      onPaste={handlePaste}
    />
  );
});
