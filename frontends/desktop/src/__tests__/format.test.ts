// @vitest-environment node
import { describe, it, expect } from 'vitest';
import { formatNumber, formatTokenCount } from '../utils/format';

describe('formatNumber', () => {
  it('returns plain number below 1000', () => {
    expect(formatNumber(0)).toBe('0');
    expect(formatNumber(999)).toBe('999');
    expect(formatNumber(42)).toBe('42');
  });

  it('formats thousands as K', () => {
    expect(formatNumber(1000)).toBe('1.0K');
    expect(formatNumber(1500)).toBe('1.5K');
    expect(formatNumber(999999)).toBe('1000.0K');
  });

  it('formats millions as M', () => {
    expect(formatNumber(1000000)).toBe('1.0M');
    expect(formatNumber(2500000)).toBe('2.5M');
  });
});

describe('formatTokenCount', () => {
  it('returns plain number below 1000', () => {
    expect(formatTokenCount(0)).toBe('0');
    expect(formatTokenCount(500)).toBe('500');
  });

  it('formats thousands as K with 1 decimal', () => {
    expect(formatTokenCount(1000)).toBe('1.0K');
    expect(formatTokenCount(12345)).toBe('12.3K');
  });

  it('formats millions as M with 2 decimals', () => {
    expect(formatTokenCount(1000000)).toBe('1.00M');
    expect(formatTokenCount(1234567)).toBe('1.23M');
  });
});
