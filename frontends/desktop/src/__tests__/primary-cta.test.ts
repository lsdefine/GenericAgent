// @vitest-environment node
import { describe, it, expect } from 'vitest';
import { computeCTAState } from '../components/chat/Composer/PrimaryCTA';

describe('computeCTAState', () => {
  it('returns send when idle + has content', () => {
    expect(computeCTAState(false, true)).toBe('send');
  });

  it('returns disabled when idle + no content', () => {
    expect(computeCTAState(false, false)).toBe('disabled');
  });

  it('returns stop when generating + no content', () => {
    expect(computeCTAState(true, false)).toBe('stop');
  });

  it('returns queue when generating + has content', () => {
    expect(computeCTAState(true, true)).toBe('queue');
  });

  it('returns disabled when pending uploads regardless of other state', () => {
    expect(computeCTAState(false, true, true)).toBe('disabled');
    expect(computeCTAState(true, true, true)).toBe('disabled');
    expect(computeCTAState(true, false, true)).toBe('disabled');
    expect(computeCTAState(false, false, true)).toBe('disabled');
  });
});
