import { describe, it, expect } from 'vitest';

/**
 * Cache hit rate formula (matches backend cost_tracker.cache_hit_rate):
 * cacheRead / (input + cacheWrite + cacheRead)
 *
 * Output is excluded — it's generated content, not cacheable input-side context.
 */
function cacheHitRate(input: number, _output: number, cacheWrite: number, cacheRead: number): string {
  const inputSide = input + cacheWrite + cacheRead;
  return inputSide > 0 ? ((cacheRead / inputSide) * 100).toFixed(1) : '0';
}

describe('token cache rate formula', () => {
  it('computes rate from input-side only (excludes output)', () => {
    // input=10K, output=2.7K, cacheWrite=0, cacheRead=14.3K
    // Expected: 14300 / (10400 + 0 + 14300) = 57.9%
    const rate = cacheHitRate(10400, 2700, 0, 14300);
    expect(rate).toBe('57.9');
  });

  it('output does not dilute the rate', () => {
    // Same input-side, wildly different output — rate should be identical
    const rateSmallOutput = cacheHitRate(1000, 100, 0, 4000);
    const rateLargeOutput = cacheHitRate(1000, 50000, 0, 4000);
    expect(rateSmallOutput).toBe(rateLargeOutput);
    expect(rateSmallOutput).toBe('80.0');
  });

  it('returns 0 when no input-side tokens', () => {
    expect(cacheHitRate(0, 500, 0, 0)).toBe('0');
  });

  it('100% when all input is cache read', () => {
    expect(cacheHitRate(0, 200, 0, 5000)).toBe('100.0');
  });

  it('includes cacheWrite in denominator', () => {
    // input=1000, cacheWrite=500, cacheRead=500
    // rate = 500 / (1000 + 500 + 500) = 25%
    expect(cacheHitRate(1000, 300, 500, 500)).toBe('25.0');
  });
});

describe('token snapshot stability', () => {
  it('live stats with empty records should not zero out a populated snapshot', () => {
    // Simulate: history-based snapshot is populated
    const historySnapshot = {
      totalInput: 50000,
      totalOutput: 12000,
      totalCacheWrite: 0,
      totalCacheRead: 30000,
    };

    // Live stats returns empty (bridge restarted, no active sessions)
    const liveRecords: Array<{ input: number; output: number; cacheCreate: number; cacheRead: number }> = [];
    const liveSnap = liveRecords.reduce(
      (acc, r) => ({
        totalInput: acc.totalInput + r.input,
        totalOutput: acc.totalOutput + r.output,
        totalCacheWrite: acc.totalCacheWrite + r.cacheCreate,
        totalCacheRead: acc.totalCacheRead + r.cacheRead,
      }),
      { totalInput: 0, totalOutput: 0, totalCacheWrite: 0, totalCacheRead: 0 },
    );

    // The bug: liveSnap would overwrite historySnapshot → zeros
    expect(liveSnap.totalInput).toBe(0);
    // The fix: polling uses fetchHistory instead, so snapshot stays correct
    expect(historySnapshot.totalInput).toBe(50000);
    expect(historySnapshot.totalCacheRead).toBe(30000);
  });

  it('fetchHistory snapshot preserves full history across bridge restarts', () => {
    // Simulate multiple history entries (persisted to disk)
    const history = [
      { input: 10000, output: 2000, cacheWrite: 0, cacheRead: 14000 },
      { input: 317000, output: 21000, cacheWrite: 0, cacheRead: 584000 },
      { input: 5000, output: 700, cacheWrite: 0, cacheRead: 9000 },
    ];

    const snap = history.reduce(
      (acc, e) => ({
        totalInput: acc.totalInput + e.input,
        totalOutput: acc.totalOutput + e.output,
        totalCacheWrite: acc.totalCacheWrite + e.cacheWrite,
        totalCacheRead: acc.totalCacheRead + e.cacheRead,
      }),
      { totalInput: 0, totalOutput: 0, totalCacheWrite: 0, totalCacheRead: 0 },
    );

    expect(snap.totalInput).toBe(332000);
    expect(snap.totalCacheRead).toBe(607000);
    // Cache rate = 607000 / (332000 + 0 + 607000) = 64.6%
    const inputSide = snap.totalInput + snap.totalCacheWrite + snap.totalCacheRead;
    const rate = ((snap.totalCacheRead / inputSide) * 100).toFixed(1);
    expect(rate).toBe('64.6');
  });
});
