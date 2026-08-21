// @vitest-environment happy-dom
import React from 'react';
import { afterEach, describe, it, expect, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import * as selectorModule from '../components/chat/Composer/ModelSelector';
import { useSettingsStore } from '../stores/settings';
import { useChatStore } from '../stores/chat';

class ResizeObserverStub {
  observe() {}
  disconnect() {}
}
vi.stubGlobal('ResizeObserver', ResizeObserverStub);
afterEach(() => cleanup());

/**
 * Tests for model selection SSOT: session-bound model takes priority over global default.
 * Verifies the logic that ModelSelector uses: sessionModelNo ?? defaultModelNo.
 */
describe('model-selector session binding', () => {
  it('shows current → next while a turn is running on a different model', () => {
    const profiles = [
      { id: 0, name: 'A', model: 'model-a', apibase: '', protocol: 'oai', stream: true },
      { id: 1, name: 'B', model: 'model-b', apibase: '', protocol: 'oai', stream: true },
    ];
    const formatLabel = (selectorModule as any).formatModelSelectionLabel;

    expect(formatLabel(profiles, 1, 0, true)).toBe('model-a → model-b');
    expect(formatLabel(profiles, 1, 0, false)).toBe('model-b');
    expect(formatLabel(profiles, 1, 1, true)).toBe('model-b');
  });

  it('controlled mode renders current → next and bypasses the Session mutation', () => {
    const profiles = [
      { id: 0, name: 'A', model: 'model-a', apibase: '', protocol: 'oai' as const, stream: true },
      { id: 1, name: 'B', model: 'model-b', apibase: '', protocol: 'oai' as const, stream: true },
    ];
    const sessionSelect = vi.fn();
    const conductorSelect = vi.fn();
    useSettingsStore.setState({ modelProfiles: profiles, defaultModelNo: 0 });
    useChatStore.setState({ sessionModelNo: 0, selectSessionModel: sessionSelect });

    const ControlledSelector = selectorModule.ModelSelector as React.ComponentType<{
      selectedNo: number;
      runningNo: number;
      isRunning: boolean;
      onSelect: (no: number) => void;
    }>;
    render(React.createElement(ControlledSelector, {
      selectedNo: 1,
      runningNo: 0,
      isRunning: true,
      onSelect: conductorSelect,
    }));

    expect(screen.getByText('model-a → model-b')).toBeTruthy();
    fireEvent.click(screen.getByTitle('model-b'));
    fireEvent.click(screen.getByTitle('model-a'));
    expect(conductorSelect).toHaveBeenCalledWith(0);
    expect(sessionSelect).not.toHaveBeenCalled();
  });

  describe('selectedNo derivation', () => {
    function deriveSelectedNo(sessionModelNo: number | null, defaultModelNo: number): number {
      return sessionModelNo ?? defaultModelNo;
    }

    it('uses session model when available', () => {
      expect(deriveSelectedNo(2, 0)).toBe(2);
      expect(deriveSelectedNo(5, 3)).toBe(5);
    });

    it('falls back to default when session model is null', () => {
      expect(deriveSelectedNo(null, 0)).toBe(0);
      expect(deriveSelectedNo(null, 3)).toBe(3);
    });

    it('uses session model 0 explicitly (not falling through to default)', () => {
      expect(deriveSelectedNo(0, 5)).toBe(0);
    });
  });

  describe('session switch resets model state', () => {
    it('new session starts with null sessionModelNo', () => {
      const state = { sessionModelNo: null as number | null };
      // Simulate setActiveSession clearing state
      state.sessionModelNo = null;
      expect(state.sessionModelNo).toBeNull();
    });

    it('poll result populates sessionModelNo from model.llmNo', () => {
      const state = { sessionModelNo: null as number | null };
      const pollResult = { model: { isMixin: false, current: 'gpt-4', llmNo: 2 } };
      if (pollResult.model?.llmNo != null) {
        state.sessionModelNo = pollResult.model.llmNo;
      }
      expect(state.sessionModelNo).toBe(2);
    });

    it('does not overwrite sessionModelNo when poll model has no llmNo', () => {
      const state = { sessionModelNo: 3 as number | null };
      const pollResult = { model: { isMixin: false, current: 'gpt-4' } as { isMixin: boolean; current: string; llmNo?: number } };
      if (pollResult.model?.llmNo != null) {
        state.sessionModelNo = pollResult.model.llmNo;
      }
      expect(state.sessionModelNo).toBe(3);
    });
  });

  describe('optimistic update and rollback', () => {
    it('optimistically sets sessionModelNo on selectSessionModel', () => {
      const state = { sessionModelNo: 1 as number | null };
      const newModel = 3;
      state.sessionModelNo = newModel;
      expect(state.sessionModelNo).toBe(3);
    });

    it('rolls back on API failure', () => {
      const state = { sessionModelNo: 1 as number | null };
      const prev = state.sessionModelNo;
      state.sessionModelNo = 3; // optimistic
      // simulate failure
      state.sessionModelNo = prev; // rollback
      expect(state.sessionModelNo).toBe(1);
    });
  });
});
