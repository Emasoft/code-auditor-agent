// fixture for webgl_three — exercises the four patterns the discoverer
// must handle:
//   1. new THREE.Scene()                  → SHADER_ENTRY-class (scene construction)
//   2. new THREE.WebGLRenderer()          → SHADER_ENTRY-class (renderer construction)
//   3. renderer.setAnimationLoop(fn)      → GAME_TICK-class (animation frame)
//   4. requestAnimationFrame(animate)     → GAME_TICK-class (raw RAF callback)
import * as THREE from 'three';

// Construct the scene graph.
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(75, 1.0, 0.1, 1000);
const renderer = new THREE.WebGLRenderer({ antialias: true });

// Per-frame update — physics, animation, render submission.
function tickPhysics(t: number): void {
  scene.rotation.y = t * 0.001;
  renderer.render(scene, camera);
}

renderer.setAnimationLoop(tickPhysics);

// Alternative frame driver — raw requestAnimationFrame loop.
function animate(now: number): void {
  renderer.render(scene, camera);
  requestAnimationFrame(animate);
}

requestAnimationFrame(animate);
