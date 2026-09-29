import { describe, expect, it } from 'vitest';
import { confidencePercent, heatColor, percentagePointDelta, splitContributions } from './format';

describe('operational rendering helpers', () => {
  it('renders the existing confidence transformation without changing probability', () => {
    const probability = 0.317;
    expect(confidencePercent(100 * (1 - probability))).toBe('68%');
    expect(probability).toBe(0.317);
  });
  it('uses finite map colors for constant and changing fields', () => {
    expect(heatColor(1, 1, 1)).toMatch(/^rgb\(/);
    expect(heatColor(0, 0, 1)).not.toBe(heatColor(1, 0, 1));
  });
  it('calculates comparison changes in percentage points', () => {
    expect(percentagePointDelta(.64, .31)).toBeCloseTo(33);
  });
  it('separates positive and negative model contributions without causal claims', () => {
    const result = splitContributions([
      { feature: 'forecast_precipitation', feature_value: 10, contribution: .4, direction: 'increases_model_bust_score' },
      { feature: 'forecast_wind_speed_10m', feature_value: 4, contribution: -.2, direction: 'decreases_model_bust_score' },
      { feature: 'month', feature_value: 8, contribution: 0, direction: 'neutral' }
    ]);
    expect(result.positive.map(item => item.feature)).toEqual(['forecast_precipitation']);
    expect(result.negative.map(item => item.feature)).toEqual(['forecast_wind_speed_10m']);
  });
});
