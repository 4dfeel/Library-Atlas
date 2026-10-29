import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const styles = readFileSync(resolve(process.cwd(), 'src/styles/globals.css'), 'utf8');

function linearChannel(channel: number): number {
  const value = channel / 255;
  return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
}

function luminance(hex: string): number {
  const channels = hex
    .match(/[\da-f]{2}/gi)
    ?.map((channel) => linearChannel(Number.parseInt(channel, 16)));
  if (!channels || channels.length !== 3)
    throw new Error('Expected a six-digit opaque design color');
  return channels[0]! * 0.2126 + channels[1]! * 0.7152 + channels[2]! * 0.0722;
}

function color(token: string): string {
  const value = styles.match(new RegExp(`--${token}:\\s*(#[\\da-f]{6})\\s*;`, 'i'))?.[1];
  if (!value) throw new Error(`Missing semantic design color: ${token}`);
  return value;
}

function contrast(foreground: string, background: string): number {
  const first = luminance(color(foreground));
  const second = luminance(color(background));
  return (Math.max(first, second) + 0.05) / (Math.min(first, second) + 0.05);
}

describe('WCAG AA semantic text colors', () => {
  for (const background of ['background', 'sidebar', 'surface', 'surface-raised']) {
    for (const foreground of [
      'text-primary',
      'text-secondary',
      'text-muted',
      'accent',
      'success',
      'warning',
      'danger',
      'private',
    ]) {
      it(`${foreground} remains readable as normal text on ${background}`, () => {
        expect(contrast(foreground, background)).toBeGreaterThanOrEqual(4.5);
      });
    }
  }

  it('keeps the primary action label readable on its accent fill', () => {
    expect(contrast('accent-foreground', 'accent')).toBeGreaterThanOrEqual(4.5);
  });
});
