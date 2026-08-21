import { describe, it, expect } from 'vitest';

function normalizeTs(ts: number): number {
  return ts < 1e12 ? ts * 1000 : ts;
}

function filterByDate(
  entries: Array<{ ts: number }>,
  from: Date | null,
  to: Date | null,
) {
  if (!from && !to) return entries;
  return entries.filter((e) => {
    const ts = normalizeTs(e.ts);
    if (from && ts < from.getTime()) return false;
    if (to && ts > to.getTime()) return false;
    return true;
  });
}

describe('token date filter', () => {
  const entries = [
    { ts: 1720000000 },      // seconds: 2024-07-03
    { ts: 1720000000000 },   // milliseconds: 2024-07-03
    { ts: 1721000000 },      // seconds: 2024-07-15
    { ts: 1722000000000 },   // milliseconds: 2024-07-26
  ];

  it('normalizes seconds to milliseconds', () => {
    expect(normalizeTs(1720000000)).toBe(1720000000000);
    expect(normalizeTs(1720000000000)).toBe(1720000000000);
  });

  it('filters with from date', () => {
    const from = new Date('2024-07-10');
    const result = filterByDate(entries, from, null);
    expect(result).toHaveLength(2);
  });

  it('filters with to date', () => {
    const to = new Date('2024-07-10');
    const result = filterByDate(entries, null, to);
    expect(result).toHaveLength(2);
  });

  it('filters with both from and to', () => {
    const from = new Date('2024-07-04');
    const to = new Date('2024-07-20');
    const result = filterByDate(entries, from, to);
    expect(result).toHaveLength(1); // only 2024-07-15
  });

  it('returns all when no filter', () => {
    const result = filterByDate(entries, null, null);
    expect(result).toHaveLength(4);
  });
});
