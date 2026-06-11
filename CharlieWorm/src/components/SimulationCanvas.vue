<template>
  <v-stage :config="stageConfig" ref="stageRef">
    <v-layer>
      <!-- 1. Field background (black rect) -->
      <v-rect :config="fieldConfig" />
      
      <!-- 2. Light glow (radial gradient) -->
      <v-circle :config="getLightGlowConfig()" />
      
      <!-- Shadow polygons ON TOP of glow — fully opaque black so no light bleeds through -->
      <v-line
        v-for="(wall, index) in shadowWalls"
        :key="'shadow-' + index"
        :config="getShadowLineConfig(wall)"
      />

      <!-- Water ripples (expanding concentric rings) -->
      <v-circle
        v-for="(ring, index) in waterRings"
        :key="'water-ring-' + index"
        :config="getWaterRingConfig(ring)"
      /> 

      <!-- Food ripples (expanding concentric rings, slower) -->
      <v-circle
        v-for="(ring, index) in foodRings"
        :key="'food-ring-' + index"
        :config="getFoodRingConfig(ring)"
      />
      
      <!-- Internal walls (brick groups) -->
      <v-group
        v-for="(wall, index) in internalWalls"
        :key="index"
        :config="getWallGroupConfig(wall, index)"
        @dragstart="handleDragStart($event, index)"
        @dragmove="handleDragMove($event, index)"
        @dragend="handleDragEnd($event, index)"
      >
        <!-- Same size as collision Rect; black = no light pixels through wall (bricks on top) -->
        <v-rect :config="{ x: 0, y: 0, width: wall.width, height: wall.height, fill: 'black' }" />
        <v-rect
          v-for="(brick, brickIndex) in getBrickPattern(wall)"
          :key="`brick-${index}-${brickIndex}`"
          :config="brick"
        />
      </v-group>
      
      <!-- Boundary walls (brick groups) -->
      <v-group
        v-for="(wall, index) in boundaryWalls"
        :key="'boundary-' + index"
        :config="{ x: wall.x, y: wall.y }"
      >
        <!-- Cement: same size as collision Rect -->
        <v-rect :config="{ x: 0, y: 0, width: wall.width, height: wall.height, fill: BRICK_GAP_COLOR }" />
        <v-rect
          v-for="(brick, brickIndex) in getBrickPattern(wall)"
          :key="'boundary-brick-' + index + '-' + brickIndex"
          :config="brick"
        />
      </v-group>
      
      <!-- Water source circle -->
   

        <v-text :config="getWaterLabelConfig()"
  @dragstart="() => {}"
   />

      <!-- Food source circle -->
  <v-text :config="getFoodLabelConfig()"
  @dragstart="() => {}"
   />
      <!-- Light source circle -->
      <v-circle
        :config="getLightSourceConfig()"
        @dragstart="handleLightDragStart"
        @dragmove="handleLightDragMove"
        @dragend="handleLightDragEnd"
      />
      
      <!-- Worm segments -->
      <v-circle
        v-for="(segment, index) in wormSegments"
        :key="index"
        :config="getSegmentConfig(segment, index)"
      />
    </v-layer>
  </v-stage>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { worldState } from '../simulation/worldState'
import { FIELD_WIDTH, FIELD_HEIGHT, WALL_THICKNESS, BRICK_GAP_COLOR } from '../simulation/constants'
import {
  resolveCircleRectCollision,
  applyCircleRectResolution,
  reflectVelocity,
  resolveCircleCircleCollision,
  applyCircleCircleResolution,
  segmentIntersectsRect,
  type Rect,
} from '../simulation/physics/collision'
import { charlySocket } from '../services/socketService'
const WORM_SEGMENT_COUNT = 1
const WORM_SEGMENT_RADIUS = 8
const MAX_SPEED = 1



/** Simulation scale: pixels per meter (for physical sensor values) */
const PIXELS_PER_METER = 100
/** Frames per second for velocity/force conversion */
const SIMULATION_FPS = 60
/** Impact duration for F = m*a (seconds). */
const IMPACT_DT = 1 / 60
/** Luminous intensity of light source in candela */
const LIGHT_INTENSITY_CANDELA = 800
/** Worm mass in kg (for impact force) */
const WORM_MASS = 0.02

interface Segment {
  x: number
  y: number
  angle: number
}

interface InternalWall {
  x: number
  y: number
  width: number
  height: number
}

const stageRef = ref()
const animationFrameId = ref<number | null>(null)

// Light source position
const lightPosition = ref({ x: 400, y: 150 })
const LIGHT_RADIUS = 12
const LIGHT_GLOW_RADIUS = 180

// Water source (draggable blue circle) and ripple animation
const WATER_RADIUS = 10
const WATER_SMELL_RADIUS = 150
const WATER_RIPPLE_MAX_RADIUS = 150
const WATER_RIPPLE_BASE_ALPHA = 0.3
const WATER_RIPPLE_PERIOD_SECONDS = 3.5
const WATER_RIPPLE_PHASE_STEP = 1 / (WATER_RIPPLE_PERIOD_SECONDS * SIMULATION_FPS)
/** Fade out by this phase (0.5 = invisible by halfway through expansion). */
const WATER_RIPPLE_FADE_END_PHASE = 0.5

const waterPosition = ref({ x: 500, y: 300 })

interface WaterRing {
  phase: number
}

const waterRings = ref<WaterRing[]>([
  { phase: 0 },
  { phase: 1 / 3 },
  { phase: 2 / 3 },
])

// Food source (draggable orange circle) and ripple animation — slower than water
const FOOD_RADIUS = 10
const FOOD_SMELL_RADIUS = 250
const FOOD_RIPPLE_MAX_RADIUS = 250
const FOOD_RIPPLE_BASE_ALPHA = 0.3
const FOOD_RIPPLE_PERIOD_SECONDS = 3
const FOOD_RIPPLE_PHASE_STEP = 1 / (FOOD_RIPPLE_PERIOD_SECONDS * SIMULATION_FPS)

const foodPosition = ref({ x: 350, y: 400 })

interface FoodRing {
  phase: number
}

const foodRings = ref<FoodRing[]>([
  { phase: 0 },
  { phase: 1 / 3 },
  { phase: 2 / 3 },
])

// Internal walls: same thickness as boundary (WALL_THICKNESS); solid black block with bricks on top
const internalWalls = ref<InternalWall[]>([
  { x: 200, y: 250, width: WALL_THICKNESS, height: 250 },
  { x: 550, y: 150, width: WALL_THICKNESS, height: 250 },
  { x: 150, y: 180, width: 280, height: WALL_THICKNESS },
  { x: 450, y: 380, width: 280, height: WALL_THICKNESS },
])

/** Previous positions of internal walls (for velocity and F = m*a on moving wall impact). */
const internalWallsPrevPosition = ref<{ x: number; y: number }[]>(
  internalWalls.value.map((w) => ({ x: w.x, y: w.y }))
)

// Brick pattern constants
const BRICK_WIDTH = 18
const BRICK_HEIGHT = 10
const BRICK_GAP = 2
const BRICK_OFFSET = 9 // Half brick width for alternating rows
const BRICK_COLOR = '#8D6E63'
const BRICK_GAP_COLOR = '#3E2723'
const WALL_BG_COLOR = '#5D4037'

const stageConfig = {
  width: FIELD_WIDTH,
  height: FIELD_HEIGHT,
}

const fieldConfig = {
  x: WALL_THICKNESS,
  y: WALL_THICKNESS,
  width: FIELD_WIDTH - WALL_THICKNESS * 2,
  height: FIELD_HEIGHT - WALL_THICKNESS * 2,
  fill: 'black',
}

/** Boundary walls: same geometry for rendering and collision. */
const boundaryWalls: Rect[] = [
  { x: 0, y: 0, width: FIELD_WIDTH, height: WALL_THICKNESS },
  { x: 0, y: FIELD_HEIGHT - WALL_THICKNESS, width: FIELD_WIDTH, height: WALL_THICKNESS },
  { x: 0, y: 0, width: WALL_THICKNESS, height: FIELD_HEIGHT },
  { x: FIELD_WIDTH - WALL_THICKNESS, y: 0, width: WALL_THICKNESS, height: FIELD_HEIGHT },
]

function getBoundaryRects(): Rect[] {
  return boundaryWalls
}

/** Config for non-draggable wall group (boundary). Bricks use local coords (0,0 = top-left). */
function getStaticWallGroupConfig(wall: Rect) {
  return {
    x: wall.x,
    y: wall.y,
    clipX: 0,
    clipY: 0,
    clipWidth: wall.width,
    clipHeight: wall.height,
  }
}

/** All walls (boundary + internal) for collision. Boundary = canvas frame; all walls are solid and impassable. */
function getAllWalls(): Rect[] {
  return [...getBoundaryRects(), ...internalWalls.value]
}

/** All walls for shadow rendering (reactive so shadows update when internal walls move). */
const shadowWalls = computed(() => [...boundaryWalls, ...internalWalls.value])

function getShadowLineConfig(wall: Rect) {
  return {
    points: getShadowPolygon(wall),
    closed: true,
    fill: 'rgba(0, 0, 0, 1)',
    listening: false,
  }
}

const getWaterSourceConfig = () => {
  return {
    x: waterPosition.value.x,
    y: waterPosition.value.y,
    radius: WATER_RADIUS,
    fill: '#29B6F6',
    stroke: '#0288D1',
    strokeWidth: 1,
    draggable: true,
  }
}



const getFoodSourceConfig = () => ({
  x: foodPosition.value.x,
  y: foodPosition.value.y,
  radius: FOOD_RADIUS,
  fill: '#FF5722',
  stroke: '#D84315',
  strokeWidth: 1,
  draggable: true,
})



// Initialize worm (head only)
const wormSegments = ref<Segment[]>([])
const initializeWorm = () => {
  const centerX = FIELD_WIDTH / 2
  const centerY = FIELD_HEIGHT / 2
  wormSegments.value = [
    { x: centerX, y: centerY, angle: Math.PI / 2 },
  ]
}

const getSegmentConfig = (segment: Segment, index: number) => {
  return {
    x: segment.x,
    y: segment.y,
    radius: WORM_SEGMENT_RADIUS,
    fill: index === 0 ? '#4CAF50' : '#8BC34A', // Head is darker green
    stroke: '#2E7D32',
    strokeWidth: 1,
  }
}

const getLightGlowConfig = () => {
  return {
    x: lightPosition.value.x,
    y: lightPosition.value.y,
    radius: LIGHT_GLOW_RADIUS,
    fillRadialGradientStartPoint: { x: 0, y: 0 },
    fillRadialGradientStartRadius: 0,
    fillRadialGradientEndPoint: { x: 0, y: 0 },
    fillRadialGradientEndRadius: LIGHT_GLOW_RADIUS,
    fillRadialGradientColorStops: [0, 'rgba(255, 255, 150, 0.8)', 1, 'rgba(255, 255, 150, 0)'],
  }
}

const getLightSourceConfig = () => {
  return {
    x: lightPosition.value.x,
    y: lightPosition.value.y,
    radius: LIGHT_RADIUS,
    fill: '#FFFF00',
    stroke: '#FFD700',
    strokeWidth: 1,
    draggable: true,
  }
}

const getWallGroupConfig = (wall: InternalWall, index: number) => {
  return {
    x: wall.x,
    y: wall.y,
    draggable: true,
    clipX: 0,
    clipY: 0,
    clipWidth: wall.width,
    clipHeight: wall.height,
  }
}

interface BrickConfig {
  x: number
  y: number
  width: number
  height: number
  fill: string
  stroke: string
  strokeWidth: number
}

const getBrickPattern = (wall: Rect): BrickConfig[] => {
  const bricks: BrickConfig[] = []
  const isVertical = wall.width < wall.height
  
  if (isVertical) {
    // Vertical wall: bricks are 10x18 (rotated), arranged in columns
    // Calculate exactly how many columns fit
    const brickColWidth = BRICK_HEIGHT + BRICK_GAP // 10 + 2 = 12px per column
    const numCols = Math.floor(wall.width / brickColWidth)
    
    // Calculate how many bricks fit in height
    const brickHeight = BRICK_WIDTH // 18px
    const brickRowHeight = BRICK_WIDTH + BRICK_GAP // 18 + 2 = 20px per row
    
    for (let col = 0; col < numCols; col++) {
      const colX = col * brickColWidth + BRICK_GAP
      const isOffsetCol = col % 2 === 1
      const offset = isOffsetCol ? BRICK_OFFSET : 0
      
      // Calculate how many bricks fit in this column
      const availableHeight = wall.height - offset
      const numBricksInCol = Math.floor(availableHeight / brickRowHeight)
      
      for (let i = 0; i < numBricksInCol; i++) {
        const y = offset + i * brickRowHeight + BRICK_GAP
        
        // Only add brick if it fits within wall boundaries
        if (y + BRICK_WIDTH <= wall.height) {
          bricks.push({
            x: colX,
            y,
            width: BRICK_HEIGHT, // 10px
            height: BRICK_WIDTH, // 18px
            fill: BRICK_COLOR,
            stroke: 'black',
            strokeWidth: 1,
          })
        }
      }
    }
  } else {
    // Horizontal wall: bricks are 18x10, arranged horizontally in rows
    // Calculate exactly how many rows fit
    const brickRowHeight = BRICK_HEIGHT + BRICK_GAP // 10 + 2 = 12px per row
    const numRows = Math.floor(wall.height / brickRowHeight)
    
    // Calculate how many bricks fit in width
    const brickWidth = BRICK_WIDTH // 18px
    const brickColWidth = BRICK_WIDTH + BRICK_GAP // 18 + 2 = 20px per column
    
    for (let row = 0; row < numRows; row++) {
      const rowY = row * brickRowHeight + BRICK_GAP
      const isOffsetRow = row % 2 === 1
      const offset = isOffsetRow ? BRICK_OFFSET : 0
      
      // Calculate how many bricks fit in this row
      const availableWidth = wall.width - offset
      const numBricksInRow = Math.floor(availableWidth / brickColWidth)
      
      for (let i = 0; i < numBricksInRow; i++) {
        const x = offset + i * brickColWidth + BRICK_GAP
        
        // Only add brick if it fits within wall boundaries
        if (x + BRICK_WIDTH <= wall.width) {
          bricks.push({
            x,
            y: rowY,
            width: BRICK_WIDTH, // 18px
            height: BRICK_HEIGHT, // 10px
            fill: BRICK_COLOR,
            stroke: 'black',
            strokeWidth: 1,
          })
        }
      }
    }
  }
  
  return bricks
}

const clamp = (value: number, min: number, max: number): number => {
  return Math.max(min, Math.min(max, value))
}

/** Universal resolution: push worm head out of all walls (boundary + internal). No bounce; 12 iterations. */
function resolveWormAgainstAllWalls(head: Segment): void {
  const circle = { x: head.x, y: head.y, radius: WORM_SEGMENT_RADIUS }
  const allWalls = getAllWalls()
  const maxIterations = 12
  for (let iter = 0; iter < maxIterations; iter++) {
    let resolved = false
    for (const wall of allWalls) {
      const result = resolveCircleRectCollision(circle, wall)
      if (result.collided) {
        applyCircleRectResolution(circle, result)
        resolved = true
      }
    }
    head.x = circle.x
    head.y = circle.y
    if (!resolved) break
  }
}

/**
 * Универсальная функция: червяк сталкивается со всеми стенами + лампой.
 * Отскок по нормали (bounce) учитывается.
 * Возвращает силу удара (impactForce) для сенсора.
 */
function resolveWormAgainstObstacles(
  head: { x: number; y: number; angle: number; radius?: number },
  speed: number,
  options: { bounce: boolean }
): number {
  const radius = head.radius ?? WORM_SEGMENT_RADIUS
  const circle = { x: head.x, y: head.y, radius }

  const allWalls = getAllWalls()
  const lamp = { x: lightPosition.value.x, y: lightPosition.value.y, radius: LIGHT_RADIUS }

  let lastNormalX = 0
  let lastNormalY = 0
  let impactForce = 0

  const maxIterations = 12
  for (let iter = 0; iter < maxIterations; iter++) {
    let resolved = false

    // 1. Столкновение со всеми стенами
    for (const wall of allWalls) {
      const result = resolveCircleRectCollision(circle, wall)
      if (result.collided) {
        applyCircleRectResolution(circle, result)
        lastNormalX = result.normalX
        lastNormalY = result.normalY
        resolved = true
      }
    }

    // 2. Столкновение с лампой
    const lampResult = resolveCircleCircleCollision(circle, lamp)
    if (lampResult.collided) {
      applyCircleCircleResolution(circle, lampResult)
      lastNormalX = lampResult.normalX
      lastNormalY = lampResult.normalY
      resolved = true
    }

    head.x = circle.x
    head.y = circle.y

    if (!resolved) break
  }

  // 3. Отскок скорости по нормали
  if (options.bounce && (lastNormalX !== 0 || lastNormalY !== 0)) {
    const vx = Math.cos(head.angle) * speed
    const vy = Math.sin(head.angle) * speed

    const restitution = 0.6
    const reflected = reflectVelocity(vx, vy, lastNormalX, lastNormalY)
    const newVx = reflected.vx * restitution
    const newVy = reflected.vy * restitution

    head.angle = Math.atan2(newVy, newVx)
    speed = Math.sqrt(newVx * newVx + newVy * newVy)

    // скорость вдоль нормали (проекция)
   const relativeVelocity = vx * lastNormalX + vy * lastNormalY

// удар только если движемся В СТЕНУ
if (relativeVelocity < 0) {
  const velocityMS = Math.abs(relativeVelocity) / PIXELS_PER_METER * SIMULATION_FPS
  const a = velocityMS / IMPACT_DT
  impactForce = WORM_MASS * a
}
  }

  return impactForce
}

/** Resolve worm (circle) against all walls: push out and reflect velocity. Movement is blocked/reflected; no pass-through. */
function resolveWormAgainstWalls(
  head: { x: number; y: number; angle: number; radius?: number },
  walls: Rect[],
  options: { bounce: boolean; speed: number }
): { anyCollision: boolean; impactSpeed: number } {
  const radius = head.radius ?? WORM_SEGMENT_RADIUS
  const circle = { x: head.x, y: head.y, radius }
  let anyCollision = false
  let impactSpeed = 0
  let lastNormalX = 0
  let lastNormalY = 0

  const maxIterations = 12
  for (let iter = 0; iter < maxIterations; iter++) {
    let resolved = false
    for (const wall of walls) {
      const result = resolveCircleRectCollision(circle, wall)
      if (result.collided) {
        applyCircleRectResolution(circle, result)
        lastNormalX = result.normalX
        lastNormalY = result.normalY
        anyCollision = true
        resolved = true
      }
    }
    head.x = circle.x
    head.y = circle.y
    if (!resolved) break
  }

if (anyCollision && options.bounce && options.speed !== 0) {
  // 1️⃣ текущая скорость по компонентам
  const vx = Math.cos(head.angle) * options.speed
  const vy = Math.sin(head.angle) * options.speed

  // 2️⃣ коэффициент упругости (0 = полностью глухо, 1 = идеально отражается)
  const restitution = 0.6

  // 3️⃣ отражение скорости по нормали
  const reflected = reflectVelocity(vx, vy, lastNormalX, lastNormalY)
  const newVx = reflected.vx * restitution
  const newVy = reflected.vy * restitution

  // 4️⃣ обновляем угол и скорость червяка
  head.angle = Math.atan2(newVy, newVx)
  options.speed = Math.sqrt(newVx * newVx + newVy * newVy)

  // 5️⃣ вычисляем компонент силы удара вдоль нормали
  const relativeVelocity = (vx * lastNormalX + vy * lastNormalY)
  const IMPACT_DT = 1 / SIMULATION_FPS // интервал кадра
  const velocityMS = (relativeVelocity / PIXELS_PER_METER)
  const a = (2 * velocityMS) / IMPACT_DT
  impactForce = WORM_MASS * a
}

  return { anyCollision, impactSpeed }
}

// Drag handlers for internal walls
const handleDragStart = (event: any, index: number) => {
  // Optional: add visual feedback
}

const handleDragMove = (event: any, index: number) => {
  const wall = internalWalls.value[index]
  const target = event.target

  const minX = WALL_THICKNESS
  const maxX = FIELD_WIDTH - WALL_THICKNESS - wall.width
  const minY = WALL_THICKNESS
  const maxY = FIELD_HEIGHT - WALL_THICKNESS - wall.height

  const constrainedX = clamp(target.x(), minX, maxX)
  const constrainedY = clamp(target.y(), minY, maxY)

  target.x(constrainedX)
  target.y(constrainedY)

  const newWallRect: Rect = { ...wall, x: constrainedX, y: constrainedY }
  internalWalls.value[index] = newWallRect

  resolveWormAgainstAllWalls(wormSegments.value[0])
  internalWallsPrevPosition.value[index] = { x: constrainedX, y: constrainedY }
}

const handleDragEnd = (event: any, index: number) => {
  const wall = internalWalls.value[index]
  const target = event.target

  const minX = WALL_THICKNESS
  const maxX = FIELD_WIDTH - WALL_THICKNESS - wall.width
  const minY = WALL_THICKNESS
  const maxY = FIELD_HEIGHT - WALL_THICKNESS - wall.height

  const constrainedX = clamp(target.x(), minX, maxX)
  const constrainedY = clamp(target.y(), minY, maxY)

  target.x(constrainedX)
  target.y(constrainedY)

  const newWallRect: Rect = { ...wall, x: constrainedX, y: constrainedY }
  internalWalls.value[index] = newWallRect

  resolveWormAgainstAllWalls(wormSegments.value[0])
  internalWallsPrevPosition.value[index] = { x: constrainedX, y: constrainedY }
}

// Light source drag handlers
const handleLightDragStart = (event: any) => {
  // Optional: add visual feedback
}

const handleLightDragMove = (event: any) => {
  const target = event.target
  
  // Constrain light to stay within field boundaries
  const minX = WALL_THICKNESS + LIGHT_RADIUS
  const maxX = FIELD_WIDTH - WALL_THICKNESS - LIGHT_RADIUS
  const minY = WALL_THICKNESS + LIGHT_RADIUS
  const maxY = FIELD_HEIGHT - WALL_THICKNESS - LIGHT_RADIUS
  
  // Get current position from Konva shape and constrain it
  const constrainedX = clamp(target.x(), minX, maxX)
  const constrainedY = clamp(target.y(), minY, maxY)
  
  // Update Konva shape position
  target.x(constrainedX)
  target.y(constrainedY)
  
  lightPosition.value = { x: constrainedX, y: constrainedY }
  pushWormOutOfLamp()
}

const handleLightDragEnd = (event: any) => {
  const target = event.target

  const minX = WALL_THICKNESS + LIGHT_RADIUS
  const maxX = FIELD_WIDTH - WALL_THICKNESS - LIGHT_RADIUS
  const minY = WALL_THICKNESS + LIGHT_RADIUS
  const maxY = FIELD_HEIGHT - WALL_THICKNESS - LIGHT_RADIUS

  const constrainedX = clamp(target.x(), minX, maxX)
  const constrainedY = clamp(target.y(), minY, maxY)

  target.x(constrainedX)
  target.y(constrainedY)

  lightPosition.value = { x: constrainedX, y: constrainedY }
  pushWormOutOfLamp()
}



/** Inverse square law: E = I / r^2. Returns illuminance in lux. */
function calculateLightLux(x: number, y: number): number {
  const dx = x - lightPosition.value.x
  const dy = y - lightPosition.value.y
  const distancePixels = Math.sqrt(dx * dx + dy * dy)
  const rMeters = distancePixels / PIXELS_PER_METER
  const rMinMeters = 0.01 // avoid singularity
  const r = Math.max(rMinMeters, rMeters)
  return LIGHT_INTENSITY_CANDELA / (r * r)
}

/** Water smell intensity at (x,y): 1 at source, linearly down to 0 at WATER_SMELL_RADIUS. */
function calculateWaterSmell(x: number, y: number): number {
  const dx = x - waterPosition.value.x
  const dy = y - waterPosition.value.y
  const distance = Math.sqrt(dx * dx + dy * dy)
  const intensity = Math.max(0, 1 - distance / WATER_SMELL_RADIUS)
  return intensity
}

/** True if any internal wall lies between worm and water source (reduces smell). */
function countWallsBetweenWormAndWater(pointX: number, pointY: number): number {
  const wx = waterPosition.value.x
  const wy = waterPosition.value.y
  let count = 0
  for (const wall of internalWalls.value) {
    if (segmentIntersectsRect(pointX, pointY, wx, wy, wall)) count++
  }
  return count
}

/** Food smell intensity at (x,y): max(0, 1 - distance/250). */
function calculateFoodSmell(x: number, y: number): number {
  const dx = x - foodPosition.value.x
  const dy = y - foodPosition.value.y
  const distance = Math.sqrt(dx * dx + dy * dy)
  return Math.max(0, 1 - distance / FOOD_SMELL_RADIUS)
}

/** Count internal walls intersecting segment worm → food (each multiplies intensity by 0.3). */
function countWallsBetweenWormAndFood(pointX: number, pointY: number): number {
  const fx = foodPosition.value.x
  const fy = foodPosition.value.y
  let count = 0
  for (const wall of internalWalls.value) {
    if (segmentIntersectsRect(pointX, pointY, fx, fy, wall)) count++
  }
  return count
}

/**
 * Returns true if any wall blocks the line of sight from the worm to the lamp.
 * Ray: worm head (pointX, pointY) → lamp center. Used so the panel shows exactly
 * what the worm feels: 0 lux when blocked, otherwise illuminance at that point.
 */
function isLightBlocked(pointX: number, pointY: number): boolean {
  const lx = lightPosition.value.x
  const ly = lightPosition.value.y
  for (const wall of internalWalls.value) {
    const blocked = segmentIntersectsRect(pointX, pointY, lx, ly, wall)
    // console.log('NOT blocked. wall:', JSON.stringify(wall))  <-- убрать
    if (blocked) return true
  }
  return false
}
/** Lamp as solid obstacle (circle). Resolve worm vs lamp; returns true if any collision occurred. */
function resolveWormAgainstLamp(head: { x: number; y: number }): boolean {
  const circle = { x: head.x, y: head.y, radius: WORM_SEGMENT_RADIUS }
  const lamp = {
    x: lightPosition.value.x,
    y: lightPosition.value.y,
    radius: LIGHT_RADIUS,
  }
  let hadCollision = false
  for (let i = 0; i < 8; i++) {
    const result = resolveCircleCircleCollision(circle, lamp)
    if (!result.collided) break
    hadCollision = true
    applyCircleCircleResolution(circle, result)
    head.x = circle.x
    head.y = circle.y
  }
  return hadCollision
}

/** Push worm out of lamp when lamp is dragged (lamp is solid). */
function pushWormOutOfLamp(): void {
  const head = wormSegments.value[0]
  resolveWormAgainstLamp(head)
}

/**
 * Shadow polygon: all 4 wall corners extended away from the light to the field boundary,
 * then ordered by angle from light so the polygon fills the blocked region. Drawn below walls.
 */
function getShadowPolygon(wall: Rect): number[] {
  const lx = lightPosition.value.x
  const ly = lightPosition.value.y

  const corners: [number, number][] = [
    [wall.x, wall.y],
    [wall.x + wall.width, wall.y],
    [wall.x + wall.width, wall.y + wall.height],
    [wall.x, wall.y + wall.height],
  ]

  // сортируем углы по углу относительно света
  const sorted = corners
    .map(([x, y]) => ({
      x,
      y,
      angle: Math.atan2(y - ly, x - lx),
    }))
    .sort((a, b) => a.angle - b.angle)

  // берём крайние два — они образуют силуэт
  const c1 = sorted[0]
  const c2 = sorted[sorted.length - 1]

  function extend(x: number, y: number): [number, number] {
    const dx = x - lx
    const dy = y - ly
    const len = Math.sqrt(dx * dx + dy * dy)
    const ux = dx / len
    const uy = dy / len

    const far = Math.max(FIELD_WIDTH, FIELD_HEIGHT) * 2
    return [x + ux * far, y + uy * far]
  }

  const e1 = extend(c1.x, c1.y)
  const e2 = extend(c2.x, c2.y)

  return [
    c1.x, c1.y,
    c2.x, c2.y,
    e2[0], e2[1],
    e1[0], e1[1],
  ]
}

const updateWorm = () => {
  const head = wormSegments.value[0]

  worldState.sensors.wallImpactForce = 0

const direction = worldState.actuators.direction || 'move_n'
const strength  = worldState.actuators.strength  || 0

const directionAngles: Record<string, number> = {
    move_n:  -Math.PI / 2,
    move_ne: -Math.PI / 4,
    move_e:   0,
    move_se:  Math.PI / 4,
    move_s:   Math.PI / 2,
    move_sw:  3 * Math.PI / 4,
    move_w:   Math.PI,
    move_nw: -3 * Math.PI / 4,
}

const targetAngle = directionAngles[direction] ?? head.angle
const speed = strength * MAX_SPEED

const angleDiff = targetAngle - head.angle
const normalizedDiff = Math.atan2(Math.sin(angleDiff), Math.cos(angleDiff))
head.angle += normalizedDiff * 0.2

head.x += Math.cos(head.angle) * speed
head.y += Math.sin(head.angle) * speed

  // 2. Физика столкновений
  const impactForce = resolveWormAgainstObstacles(head, speed, { bounce: true })
  worldState.sensors.wallImpactForce = impactForce

  // 3. Расчет сенсоров (свет, вода, еда)
  const isCurrentlyShadowed = isLightBlocked(head.x, head.y)
  worldState.sensors.lightLux = isCurrentlyShadowed ? 0 : calculateLightLux(head.x, head.y)

  let waterIntensity = calculateWaterSmell(head.x, head.y)
  const wallCount = countWallsBetweenWormAndWater(head.x, head.y)
  if (wallCount > 0) waterIntensity *= Math.pow(0.3, wallCount)
  worldState.sensors.waterSmell = waterIntensity

  let foodIntensity = calculateFoodSmell(head.x, head.y)
  const foodWallCount = countWallsBetweenWormAndFood(head.x, head.y)
  if (foodWallCount > 0) foodIntensity *= Math.pow(0.3, foodWallCount)
  worldState.sensors.foodSmell = foodIntensity

  worldState.physics.wormVelocity = (Math.abs(speed) / PIXELS_PER_METER) * SIMULATION_FPS
  internalWallsPrevPosition.value = internalWalls.value.map((w) => ({ x: w.x, y: w.y }))

  charlySocket.send({
    sensors: {
      lightLux:        worldState.sensors.lightLux,
      wallImpactForce: worldState.sensors.wallImpactForce,
      waterSmell:      worldState.sensors.waterSmell,
      foodSmell:       worldState.sensors.foodSmell,
    }
  })

  // Увеличиваем счетчик шагов
  worldState.simulation.stepCount++
}


const gameLoop = () => {
  // Animate water ripples
  for (const ring of waterRings.value) {
    ring.phase += WATER_RIPPLE_PHASE_STEP
    if (ring.phase > 1) {
      ring.phase -= 1
    }
  }
  // Animate food ripples (slower period)
  for (const ring of foodRings.value) {
    ring.phase += FOOD_RIPPLE_PHASE_STEP
    if (ring.phase > 1) {
      ring.phase -= 1
    }
  }

  updateWorm()
  animationFrameId.value = requestAnimationFrame(gameLoop)
}

onMounted(() => {
  initializeWorm()
  animationFrameId.value = requestAnimationFrame(gameLoop)
})

onUnmounted(() => {
  if (animationFrameId.value !== null) {
    cancelAnimationFrame(animationFrameId.value)
  }
})


const getFoodLabelConfig = () => ({
  x: foodPosition.value.x, // центр иконки = центр источника
  y: foodPosition.value.y,
  text: '🍎',
  fontSize: 20,
   offsetX: 13,
  offsetY: 13,
  draggable: true,
  listening: true,
  dragBoundFunc: (pos: { x: number; y: number }) => ({
    x: clamp(pos.x, WALL_THICKNESS + FOOD_RADIUS, FIELD_WIDTH - WALL_THICKNESS - FOOD_RADIUS),
    y: clamp(pos.y, WALL_THICKNESS + FOOD_RADIUS, FIELD_HEIGHT - WALL_THICKNESS - FOOD_RADIUS),
  }),
  onDragMove: (e: any) => {
    const pos = e.target.position()
    foodPosition.value = { x: pos.x, y: pos.y } // обновляем центр источника
  },
})

const getWaterLabelConfig = () => ({
  x: waterPosition.value.x, // центр иконки = центр источника
  y: waterPosition.value.y,
  text: '💧',
  fontSize: 20,
   offsetX: 13,
  offsetY: 13,
  draggable: true,
  listening: true,
  dragBoundFunc: (pos: { x: number; y: number }) => ({
    x: clamp(pos.x, WALL_THICKNESS + WATER_RADIUS, FIELD_WIDTH - WALL_THICKNESS - WATER_RADIUS),
    y: clamp(pos.y, WALL_THICKNESS + WATER_RADIUS, FIELD_HEIGHT - WALL_THICKNESS - WATER_RADIUS),
  }),
  onDragMove: (e: any) => {
    const pos = e.target.position()
    waterPosition.value = { x: pos.x, y: pos.y } // обновляем центр источника
  },
})

const getWaterRingConfig = (ring: WaterRing) => {
  const radius = ring.phase * WATER_RIPPLE_MAX_RADIUS
  const alpha =
    ring.phase >= WATER_RIPPLE_FADE_END_PHASE
      ? 0
      : (1 - ring.phase / WATER_RIPPLE_FADE_END_PHASE) * WATER_RIPPLE_BASE_ALPHA
  return {
    x: waterPosition.value.x, // центр источника
    y: waterPosition.value.y,
    radius,
    stroke: `rgba(41, 182, 246, ${alpha})`,
    strokeWidth: 2,
    listening: false,
  }
}

const getFoodRingConfig = (ring: FoodRing) => {
  const radius = ring.phase * FOOD_RIPPLE_MAX_RADIUS
  const alpha = (1 - ring.phase) * FOOD_RIPPLE_BASE_ALPHA
  return {
    x: foodPosition.value.x, // центр источника
    y: foodPosition.value.y,
    radius,
    stroke: `rgba(255, 87, 34, ${alpha})`,
    strokeWidth: 2,
    listening: false,
  }
}
</script>

<style scoped></style>
