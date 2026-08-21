// @vitest-environment happy-dom
import React, { forwardRef, useImperativeHandle, useState } from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { Composer } from '../components/chat/Composer';

const uploadFileMock = vi.fn();

vi.mock('../services/chat', () => ({
  uploadFile: uploadFileMock,
}));

vi.mock('../components/chat/Composer/usePlaceholder', () => ({
  usePlaceholder: () => ({ text: 'Type a message' }),
}));

vi.mock('../components/chat/Composer/CompletionDrawer', () => ({
  CompletionDrawer: () => null,
}));

vi.mock('../components/chat/Composer/AtRefPopover', () => ({
  AtRefPopover: () => null,
}));

vi.mock('../components/chat/Composer/ContextMenu', () => ({
  ContextMenu: ({ onUploadFile }: { onUploadFile: () => void }) => (
    <button type="button" onClick={onUploadFile}>Attach</button>
  ),
}));

vi.mock('../components/chat/Composer/ModelSelector', () => ({
  ModelSelector: () => null,
}));

vi.mock('../components/chat/Composer/SkillPanel', () => ({
  SkillPanel: () => null,
}));

vi.mock('../components/chat/Composer/StatusStack', () => ({
  StatusStack: () => null,
}));

vi.mock('../stores/settings', () => ({
  useSettingsStore: (selector: (state: { lang: 'en' | 'zh' }) => unknown) => selector({ lang: 'en' }),
}));

vi.mock('../components/chat/Composer/RichEditorInput', () => {
  const RichEditorInput = forwardRef(function MockRichEditorInput(
    {
      placeholder,
      onInput,
      onKeyDown,
    }: {
      placeholder: string;
      onInput: (plainText: string) => void;
      onKeyDown: (e: React.KeyboardEvent) => void;
    },
    ref: React.ForwardedRef<{
      clear: () => void;
      getText: () => string;
      setText: (text: string) => void;
      focus: () => void;
      insertChip: () => void;
      setSkillChip: () => void;
      getElement: () => HTMLTextAreaElement | null;
    }>,
  ) {
    const [value, setValue] = useState('');

    useImperativeHandle(ref, () => ({
      clear() {
        setValue('');
        onInput('');
      },
      getText() {
        return value;
      },
      setText(text: string) {
        setValue(text);
        onInput(text);
      },
      focus() {},
      insertChip() {},
      setSkillChip() {},
      getElement() {
        return null;
      },
    }), [value, onInput]);

    return (
      <textarea
        aria-label="Composer input"
        placeholder={placeholder}
        value={value}
        onChange={(e) => {
          setValue(e.target.value);
          onInput(e.target.value);
        }}
        onKeyDown={onKeyDown}
      />
    );
  });

  return { RichEditorInput };
});

class IdleFileReader {
  onload: null | ((event: { target: { result: string } }) => void) = null;
  onerror: null | (() => void) = null;

  readAsDataURL(_file: File) {}
}

class SuccessFileReader {
  onload: null | ((event: { target: { result: string } }) => void) = null;
  onerror: null | (() => void) = null;

  readAsDataURL(_file: File) {
    queueMicrotask(() => {
      this.onload?.({ target: { result: 'data:text/plain;base64,SGVsbG8=' } });
    });
  }
}

describe('Composer attachment lifecycle', () => {
  const originalFileReader = globalThis.FileReader;
  const originalResizeObserver = globalThis.ResizeObserver;

  beforeEach(() => {
    uploadFileMock.mockReset();
    globalThis.ResizeObserver = class {
      observe() {}
      disconnect() {}
      unobserve() {}
    } as unknown as typeof ResizeObserver;
  });

  afterEach(() => {
    globalThis.FileReader = originalFileReader;
    globalThis.ResizeObserver = originalResizeObserver;
  });

  it('disables the CTA while a non-image file is still uploading', async () => {
    globalThis.FileReader = IdleFileReader as unknown as typeof FileReader;

    render(<Composer onSend={vi.fn()} onStop={vi.fn()} isGenerating={false} />);

    const fileInput = document.querySelector('input[type="file"]:not([accept])') as HTMLInputElement;
    const file = new File(['hello'], 'draft.txt', { type: 'text/plain' });
    fireEvent.change(fileInput, { target: { files: [file] } });

    await waitFor(() => {
      expect(screen.getByText('draft.txt')).not.toBeNull();
    });

    const cta = screen.getByRole('button', { name: 'Send message' });
    expect(cta.getAttribute('data-state')).toBe('disabled');
    expect((cta as HTMLButtonElement).disabled).toBe(true);
  });

  it('shows an error state when file upload fails', async () => {
    globalThis.FileReader = SuccessFileReader as unknown as typeof FileReader;
    uploadFileMock.mockRejectedValueOnce(new Error('upload failed'));

    render(<Composer onSend={vi.fn()} onStop={vi.fn()} isGenerating={false} />);

    const fileInput = document.querySelector('input[type="file"]:not([accept])') as HTMLInputElement;
    const file = new File(['hello'], 'broken.txt', { type: 'text/plain' });
    fireEvent.change(fileInput, { target: { files: [file] } });

    await waitFor(() => {
      expect(screen.getByText('broken.txt')).not.toBeNull();
    });

    await waitFor(() => {
      expect(screen.getByTitle('upload failed')).not.toBeNull();
    });
  });
});
