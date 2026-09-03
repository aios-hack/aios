export interface OrbitSeat {
  angleDeg: number;
  x: number;
  y: number;
  delayMs: number;
}

export const SEAT_ANGLES_DEG: readonly number[] = [
  -16, 196, 16, 164, -55, 235
];

export const RADIUS_SQUEEZE_Y = 1.2;

export const seatAngle = (index: number): number =>
  SEAT_ANGLES_DEG[index % SEAT_ANGLES_DEG.length];

export const orbitSeats = (
  count: number,
  radius: number,
  staggerMs: number
): OrbitSeat[] => {
  const seats: OrbitSeat[] = [];
  for (let index = 0; index < count; index += 1) {
    const angleDeg = seatAngle(index);
    const radians = (angleDeg * Math.PI) / 180;
    seats.push({
      angleDeg,
      x: Math.cos(radians) * radius,
      y: Math.sin(radians) * radius * RADIUS_SQUEEZE_Y,
      delayMs: index * staggerMs
    });
  }
  return seats;
};

export const minimumSeatGap = (seats: readonly OrbitSeat[]): number => {
  let smallest = Number.POSITIVE_INFINITY;
  for (let i = 0; i < seats.length; i += 1) {
    for (let j = i + 1; j < seats.length; j += 1) {
      const gap = Math.hypot(seats[i].x - seats[j].x, seats[i].y - seats[j].y);
      if (gap < smallest) {
        smallest = gap;
      }
    }
  }
  return seats.length < 2 ? 0 : smallest;
};

export const clearsSphere = (seats: readonly OrbitSeat[], sphereRadius: number): boolean =>
  seats.every((seat) => Math.hypot(seat.x, seat.y) > sphereRadius);
