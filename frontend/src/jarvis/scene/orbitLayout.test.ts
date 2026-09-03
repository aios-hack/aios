import { describe, expect, it } from 'vitest';
import { MAX_ORBIT_CARDS } from '../scenes';
import {
  RADIUS_SQUEEZE_Y,
  SEAT_ANGLES_DEG,
  clearsSphere,
  minimumSeatGap,
  orbitSeats,
  seatAngle
} from './orbitLayout';

const RADIUS_PX = 420;
const CARD_W = 280;
const CARD_H = 240;
const SPHERE_PX = 280;

const boxOf = (seat: { x: number; y: number }) => ({
  left: seat.x * RADIUS_PX - CARD_W / 2,
  right: seat.x * RADIUS_PX + CARD_W / 2,
  top: seat.y * RADIUS_PX - CARD_H / 2,
  bottom: seat.y * RADIUS_PX + CARD_H / 2
});

const overlapArea = (
  a: { left: number; right: number; top: number; bottom: number },
  b: { left: number; right: number; top: number; bottom: number }
): number => {
  const x = Math.max(0, Math.min(a.right, b.right) - Math.max(a.left, b.left));
  const y = Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top));
  return x * y;
};

describe('orbit seats', () => {
  const seats = orbitSeats(MAX_ORBIT_CARDS, 1, 80);

  it('offers a seat for every card the orbit is allowed to show', () => {
    expect(SEAT_ANGLES_DEG.length).toBeGreaterThanOrEqual(MAX_ORBIT_CARDS);
    expect(seats).toHaveLength(MAX_ORBIT_CARDS);
  });

  it('staggers arrival so the cards land in reading order', () => {
    expect(seats.map((seat) => seat.delayMs)).toEqual([0, 80, 160, 240, 320, 400]);
  });

  it('reuses the catalogue of angles and wraps past its end', () => {
    expect(seatAngle(0)).toBe(SEAT_ANGLES_DEG[0]);
    expect(seatAngle(SEAT_ANGLES_DEG.length)).toBe(SEAT_ANGLES_DEG[0]);
  });

  it('keeps every seat off the sphere in the middle', () => {
    expect(clearsSphere(seats, 0.4)).toBe(true);
  });

  it('leaves no card box touching the sphere at the real stage size', () => {
    const sphere = {
      left: -SPHERE_PX / 2,
      right: SPHERE_PX / 2,
      top: -SPHERE_PX / 2,
      bottom: SPHERE_PX / 2
    };
    for (const seat of seats) {
      expect(overlapArea(boxOf(seat), sphere), `seat ${seat.angleDeg}`).toBe(0);
    }
  });

  it('leaves no two card boxes overlapping each other', () => {
    for (let i = 0; i < seats.length; i += 1) {
      for (let j = i + 1; j < seats.length; j += 1) {
        expect(
          overlapArea(boxOf(seats[i]), boxOf(seats[j])),
          `seats ${seats[i].angleDeg} and ${seats[j].angleDeg}`
        ).toBe(0);
      }
    }
  });

  it('spreads the seats rather than stacking them on one point', () => {
    expect(minimumSeatGap(seats)).toBeGreaterThan(0.2);
  });

  it('mirrors the seats left and right so the scene stays balanced', () => {
    const rights = seats.filter((seat) => seat.x > 0).length;
    const lefts = seats.filter((seat) => seat.x < 0).length;
    expect(rights).toBe(lefts);
  });

  it('stretches the ring vertically, since the cards are wider than they are tall', () => {
    expect(RADIUS_SQUEEZE_Y).toBeGreaterThan(1);
  });
});
