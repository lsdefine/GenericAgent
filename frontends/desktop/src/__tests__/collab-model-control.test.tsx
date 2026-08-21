// @vitest-environment happy-dom
import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { CollabComposer } from '../components/collab/CollabComposer';


const selectModel = vi.fn();
const state = {
  sendMessage: vi.fn(),
  conductorTyping: true,
  connectionStatus: 'ready',
  modelConfig: { configured: 99, effective: 2, fallbackReason: 'invalid_configured' },
  runtimeModel: {
    configured: 1,
    effective: 1,
    fallbackReason: null,
    current: 'model-one',
    running: true,
  },
  loadModel: vi.fn(),
  selectModel,
};

vi.mock('../stores/conductor', () => ({
  useConductorStore: (selector: (value: typeof state) => unknown) => selector(state),
}));
vi.mock('../stores/settings', () => ({
  useSettingsStore: (selector: (value: { defaultModelNo: number }) => unknown) => selector({ defaultModelNo: 0 }),
}));
vi.mock('../components/chat/Composer', () => ({
  Composer: ({ modelControl }: { modelControl?: React.ReactNode }) => <div>{modelControl}</div>,
}));
vi.mock('../components/chat/Composer/ModelSelector', () => ({
  ModelSelector: (props: {
    selectedNo: number;
    runningNo: number | null;
    isRunning: boolean;
    onSelect: (no: number) => void;
  }) => (
    <button
      data-testid="conductor-selector"
      data-selected={props.selectedNo}
      data-running={props.runningNo ?? ''}
      data-is-running={String(props.isRunning)}
      onClick={() => props.onSelect(3)}
    >
      model
    </button>
  ),
}));


describe('Collab model control', () => {
  it('uses the effective Conductor model and never the Session binding', () => {
    render(<CollabComposer />);

    const selector = screen.getByTestId('conductor-selector');
    expect(selector.getAttribute('data-selected')).toBe('2');
    expect(selector.getAttribute('data-running')).toBe('1');
    expect(selector.getAttribute('data-is-running')).toBe('true');
    fireEvent.click(selector);
    expect(selectModel).toHaveBeenCalledWith(3);
  });
});
