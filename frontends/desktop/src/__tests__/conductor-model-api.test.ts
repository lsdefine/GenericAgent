// @vitest-environment node
import { afterEach, describe, expect, it, vi } from 'vitest';
import * as servicesApi from '../services/services-api';


describe('Conductor model configuration API', () => {
  afterEach(() => vi.restoreAllMocks());

  it('loads the resolved Conductor model state from the bridge', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({
        model: { configured: null, effective: 1, fallbackReason: 'ui_default' },
      }),
    } as Response);

    const state = await (servicesApi as any).fetchConductorModel();

    expect(fetchMock).toHaveBeenCalledWith('http://127.0.0.1:14168/services/conductor/model');
    expect(state).toEqual({ configured: null, effective: 1, fallbackReason: 'ui_default' });
  });

  it('persists a Conductor model without touching a Session endpoint', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({
        ok: true,
        model: { configured: 2, effective: 2, fallbackReason: null },
      }),
    } as Response);

    const state = await (servicesApi as any).saveConductorModel(2);

    expect(fetchMock).toHaveBeenCalledWith(
      'http://127.0.0.1:14168/services/conductor/model',
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ llmNo: 2 }) }),
    );
    expect(state.configured).toBe(2);
    expect(String(fetchMock.mock.calls[0][0])).not.toContain('/session/');
  });
});
