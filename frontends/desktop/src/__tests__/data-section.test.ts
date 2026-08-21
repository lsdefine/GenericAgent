// @vitest-environment node
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

const BRIDGE_BASE = 'http://127.0.0.1:14168';

const mockSaveMykeyContent = vi.fn();
const mockGetMykeyContent = vi.fn();
const mockTauriInvoke = vi.fn();
const mockLoadFromBridge = vi.fn().mockResolvedValue(undefined);
const mockLoadSessions = vi.fn();

vi.mock('../../services/bridge', () => ({
  saveMykeyContent: (...args: any[]) => mockSaveMykeyContent(...args),
  getMykeyContent: (...args: any[]) => mockGetMykeyContent(...args),
  tauriInvoke: (...args: any[]) => mockTauriInvoke(...args),
}));

vi.mock('../../stores/settings', () => ({
  useSettingsStore: {
    getState: () => ({ loadFromBridge: mockLoadFromBridge }),
  },
}));

vi.mock('../../stores/chat', () => ({
  useChatStore: {
    getState: () => ({ loadSessions: mockLoadSessions }),
  },
}));

describe('DataSection logic', () => {
  let mockFetch: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    mockFetch = vi.fn();
    vi.stubGlobal('fetch', mockFetch);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  describe('import key config', () => {
    it('saves content and refreshes profiles on success', async () => {
      mockSaveMykeyContent.mockResolvedValue(undefined);

      const content = 'native_oai_config = {"apikey": "sk-test", "model": "gpt-4"}';
      await mockSaveMykeyContent(content);
      await mockLoadFromBridge();

      expect(mockSaveMykeyContent).toHaveBeenCalledWith(content);
      expect(mockLoadFromBridge).toHaveBeenCalled();
    });

    it('throws on bridge error', async () => {
      mockSaveMykeyContent.mockRejectedValue(new Error('500 Internal Server Error'));

      await expect(mockSaveMykeyContent('bad')).rejects.toThrow('500');
    });
  });

  describe('export key config', () => {
    it('reads mykey content from bridge', async () => {
      const content = 'native_oai_config = {"apikey": "sk-x"}';
      mockGetMykeyContent.mockResolvedValue(content);

      const result = await mockGetMykeyContent();
      expect(result).toBe(content);
    });

    it('returns empty when no mykey exists', async () => {
      mockGetMykeyContent.mockResolvedValue('');

      const result = await mockGetMykeyContent();
      expect(result).toBe('');
    });
  });

  describe('import memory & sessions', () => {
    it('posts sourceDir to /memory/import and returns counts', async () => {
      mockFetch.mockResolvedValue({
        ok: true,
        status: 200,
        json: () => Promise.resolve({
          memoryCopied: 3,
          responsesCopied: 5,
          responsesSkipped: 2,
          sessionsAdded: 4,
        }),
      });

      const res = await fetch(`${BRIDGE_BASE}/memory/import`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sourceDir: '/path/to/repo' }),
      });
      const data = await res.json();

      expect(mockFetch).toHaveBeenCalledWith(
        `${BRIDGE_BASE}/memory/import`,
        expect.objectContaining({ method: 'POST' }),
      );
      expect(data.memoryCopied).toBe(3);
      expect(data.sessionsAdded).toBe(4);
    });

    it('handles error response from bridge', async () => {
      mockFetch.mockResolvedValue({
        ok: false,
        status: 400,
        json: () => Promise.resolve({ error: 'No memory data found' }),
      });

      const res = await fetch(`${BRIDGE_BASE}/memory/import`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sourceDir: '/empty/dir' }),
      });
      const data = await res.json();

      expect(res.ok).toBe(false);
      expect(data.error).toContain('No memory');
    });

    it('handles network failure gracefully', async () => {
      mockFetch.mockRejectedValue(new TypeError('Failed to fetch'));

      await expect(
        fetch(`${BRIDGE_BASE}/memory/import`, {
          method: 'POST',
          body: JSON.stringify({ sourceDir: '/path' }),
        }),
      ).rejects.toThrow('Failed to fetch');
    });
  });
});

describe('GaSourceBlock logic', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  describe('connect local repo', () => {
    it('validates and connects on valid repo', async () => {
      mockTauriInvoke
        .mockResolvedValueOnce('/Users/test/GenericAgent')
        .mockResolvedValueOnce('/Users/test/GenericAgent');

      const picked = await mockTauriInvoke('pick_directory', {});
      expect(picked).toBe('/Users/test/GenericAgent');

      const result = await mockTauriInvoke('set_ga_source', { dir: picked });
      expect(result).toBe('/Users/test/GenericAgent');
    });

    it('rejects repo without agentmain.py', async () => {
      mockTauriInvoke
        .mockResolvedValueOnce('/Users/test/not-ga')
        .mockRejectedValueOnce(new Error('not a GenericAgent source: agentmain.py not found'));

      const picked = await mockTauriInvoke('pick_directory', {});
      await expect(
        mockTauriInvoke('set_ga_source', { dir: picked }),
      ).rejects.toThrow('agentmain.py');
    });

    it('rejects a core that fails the package compatibility probe', async () => {
      mockTauriInvoke
        .mockResolvedValueOnce('/Users/test/partial-ga')
        .mockRejectedValueOnce(new Error('this GenericAgent core is not compatible: missing sessions'));

      const picked = await mockTauriInvoke('pick_directory', {});
      await expect(
        mockTauriInvoke('set_ga_source', { dir: picked }),
      ).rejects.toThrow('not compatible');
    });

    it('handles bridge startup timeout', async () => {
      mockTauriInvoke
        .mockResolvedValueOnce('/Users/test/GenericAgent')
        .mockRejectedValueOnce(new Error('bridge did not become ready within 20s'));

      const picked = await mockTauriInvoke('pick_directory', {});
      await expect(
        mockTauriInvoke('set_ga_source', { dir: picked }),
      ).rejects.toThrow('20s');
    });

    it('returns null when user cancels directory picker', async () => {
      mockTauriInvoke.mockResolvedValueOnce(null);

      const picked = await mockTauriInvoke('pick_directory', {});
      expect(picked).toBeNull();
    });
  });

  describe('disconnect', () => {
    it('clears ga_source and switches back to bundle', async () => {
      mockTauriInvoke.mockResolvedValueOnce('/bundle/path');

      const result = await mockTauriInvoke('clear_ga_source', {});
      expect(result).toBe('/bundle/path');
    });
  });

  describe('mapSourceError', () => {
    function mapSourceError(msg: string): string {
      if (msg.includes('agentmain.py')) return 'data.localRepoErrNoAgent';
      if (msg.includes('not compatible') || msg.includes('compatibility probe')) {
        return 'data.localRepoErrIncompatible';
      }
      if (msg.includes('20s') || msg.includes('ready')) return 'data.localRepoErrTimeout';
      if (msg.includes('no GenericAgent source')) return 'data.localRepoErrNoResolve';
      return 'data.localRepoSwitchFailed';
    }

    it('maps agentmain error correctly', () => {
      expect(mapSourceError('not a GenericAgent source: agentmain.py not found'))
        .toBe('data.localRepoErrNoAgent');
    });

    it('maps compatibility probe errors correctly', () => {
      expect(mapSourceError('this GenericAgent core is not compatible: missing sessions'))
        .toBe('data.localRepoErrIncompatible');
    });

    it('maps timeout error correctly', () => {
      expect(mapSourceError('bridge did not become ready within 20s'))
        .toBe('data.localRepoErrTimeout');
    });

    it('maps resolve error correctly', () => {
      expect(mapSourceError('no GenericAgent source resolved'))
        .toBe('data.localRepoErrNoResolve');
    });

    it('falls back to generic error', () => {
      expect(mapSourceError('some unexpected error'))
        .toBe('data.localRepoSwitchFailed');
    });
  });
});
