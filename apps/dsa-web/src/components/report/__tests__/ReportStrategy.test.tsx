import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ReportStrategy } from '../ReportStrategy';

describe('ReportStrategy', () => {
  it('always renders the strategy plan even without sniper points', () => {
    render(<ReportStrategy language="zh" />);

    expect(screen.getByText('策略计划')).toBeInTheDocument();
    expect(screen.getByText('狙击点位')).toBeInTheDocument();
    expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(4);
  });

  it('shows the WR strategy name as the plan title', () => {
    render(
      <ReportStrategy
        language="en"
        strategy={{
          strategyName: 'BRK55 Mom WR62.7%',
          idealBuy: '180',
          stopLoss: '170',
          takeProfit: '195',
          entryPlan: 'break 55d high',
        }}
      />,
    );

    expect(screen.getByText('STRATEGY PLAN')).toBeInTheDocument();
    expect(screen.getByText('BRK55 Mom WR62.7%')).toBeInTheDocument();
    expect(screen.getByText('180')).toBeInTheDocument();
    expect(screen.getByText('Entry Plan: break 55d high')).toBeInTheDocument();
  });
});
