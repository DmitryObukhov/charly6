/**
 * 2D collision detection and resolution for circle vs axis-aligned rectangle.
 * Used for worm (circle) vs walls (rects). Symmetric: supports both
 * "worm moves into wall" and "wall moves into worm" resolution.
 */

export interface Circle {
  x: number
  y: number
  radius: number
}

export interface Rect {
  x: number
  y: number
  width: number
  height: number
}

export interface CollisionResult {
  collided: boolean
  /** Unit vector from rect toward circle (separation direction for circle) */
  normalX: number
  normalY: number
  /** How much the circle overlaps the rect; move circle by (normalX * depth, normalY * depth) to resolve */
  depth: number
}

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value))
}

/**
 * Detects overlap between circle and rect and returns collision normal and penetration depth.
 * Normal points from rect toward circle (so moving circle by normal * depth pushes circle out of rect).
 */
export function resolveCircleRectCollision(circle: Circle, rect: Rect): CollisionResult {
  const closestX = clamp(circle.x, rect.x, rect.x + rect.width)
  const closestY = clamp(circle.y, rect.y, rect.y + rect.height)
  const dx = circle.x - closestX
  const dy = circle.y - closestY
  const distSq = dx * dx + dy * dy
  const radiusSq = circle.radius * circle.radius

  if (distSq >= radiusSq) {
    return { collided: false, normalX: 0, normalY: 0, depth: 0 }
  }

  const dist = Math.sqrt(distSq)
  const depth = circle.radius - dist

  let normalX: number
  let normalY: number

  if (dist > 1e-6) {
    normalX = dx / dist
    normalY = dy / dist
  } else {
    // Circle center inside rect: push toward nearest edge
    const toLeft = circle.x - rect.x
    const toRight = rect.x + rect.width - circle.x
    const toTop = circle.y - rect.y
    const toBottom = rect.y + rect.height - circle.y
    const minHorz = Math.min(toLeft, toRight)
    const minVert = Math.min(toTop, toBottom)
    if (minHorz < minVert) {
      normalX = toLeft < toRight ? -1 : 1
      normalY = 0
    } else {
      normalX = 0
      normalY = toTop < toBottom ? -1 : 1
    }
  }

  return { collided: true, normalX, normalY, depth }
}

/**
 * Applies positional correction: moves circle out of rect along the collision normal.
 * Call after resolveCircleRectCollision when collided is true.
 */
export function applyCircleRectResolution(
  circle: { x: number; y: number; radius: number },
  result: CollisionResult
): void {
  if (!result.collided || result.depth <= 0) return
  circle.x += result.normalX * result.depth
  circle.y += result.normalY * result.depth
}

/**
 * Reflects a velocity vector (vx, vy) about a unit normal (nx, ny).
 * Returns new velocity direction (same magnitude implied by input scale).
 */
export function reflectVelocity(vx: number, vy: number, nx: number, ny: number): { vx: number; vy: number } {
  const dot = vx * nx + vy * ny
  return {
    vx: vx - 2 * dot * nx,
    vy: vy - 2 * dot * ny,
  }
}

/** Result for circle-circle collision. Normal from circleB toward circleA. */
export interface CircleCircleResult {
  collided: boolean
  normalX: number
  normalY: number
  depth: number
}

/**
 * Circle-circle collision. Normal points from B toward A (move A by normal * depth to resolve).
 */
export function resolveCircleCircleCollision(circleA: Circle, circleB: Circle): CircleCircleResult {
  const dx = circleA.x - circleB.x
  const dy = circleA.y - circleB.y
  const distSq = dx * dx + dy * dy
  const sumR = circleA.radius + circleB.radius
  const sumRSq = sumR * sumR

  if (distSq >= sumRSq || distSq < 1e-10) {
    return { collided: false, normalX: 0, normalY: 0, depth: 0 }
  }

  const dist = Math.sqrt(distSq)
  const depth = sumR - dist
  const normalX = dx / dist
  const normalY = dy / dist

  return { collided: true, normalX, normalY, depth }
}

export function applyCircleCircleResolution(
  circleA: { x: number; y: number; radius: number },
  result: CircleCircleResult
): void {
  if (!result.collided || result.depth <= 0) return
  circleA.x += result.normalX * result.depth
  circleA.y += result.normalY * result.depth
}

/**
 * Returns true if the segment from (ax,ay) to (bx,by) intersects the rect (including interior).
 * Uses parametric line + slab intervals (Liang–Barsky style). Used for light blocking.
 */
export function segmentIntersectsRect(
  ax: number,
  ay: number,
  bx: number,
  by: number,
  rect: Rect
): boolean {
  const minX = rect.x
  const maxX = rect.x + rect.width
  const minY = rect.y
  const maxY = rect.y + rect.height

  if (ax >= minX && ax <= maxX && ay >= minY && ay <= maxY) return true
  if (bx >= minX && bx <= maxX && by >= minY && by <= maxY) return true

  const dx = bx - ax
  const dy = by - ay

  function checkEdge(p: number, q: number): [number, number] {
    if (Math.abs(q) < 1e-10) return p <= 0 ? [0, 1] : [1, 0]
    const t = p / q
    return q < 0 ? [t, Infinity] : [-Infinity, t]
  }

  let tMin = 0
  let tMax = 1

  const checks = [
    checkEdge(ax - minX, -dx),
    checkEdge(maxX - ax, dx),
    checkEdge(ay - minY, -dy),
    checkEdge(maxY - ay, dy),
  ]

  for (const [t0, t1] of checks) {
    tMin = Math.max(tMin, t0)
    tMax = Math.min(tMax, t1)
    if (tMin > tMax) return false
  }

  return tMin <= tMax
}
