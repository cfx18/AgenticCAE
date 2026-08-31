import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { STLLoader } from "three/addons/loaders/STLLoader.js";

const VIEW_DIRECTION = new THREE.Vector3(1, -1.25, 0.85).normalize();
const COLORS = { truth: 0x4397b8, candidate: 0xdf843d };

class GeometryViewport {
  constructor(container, manager) {
    this.container = container;
    this.manager = manager;
    this.canvas = container.querySelector("canvas");
    this.fallback = container.querySelector(".geometry-fallback");
    this.status = container.querySelector(".viewer-status");
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x1c252c);
    this.camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.01, 10000);
    this.renderer = new THREE.WebGLRenderer({ canvas: this.canvas, antialias: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.controls = new OrbitControls(this.camera, this.canvas);
    this.controls.enableDamping = false;
    this.controls.screenSpacePanning = true;
    this.controls.zoomToCursor = true;
    this.controls.addEventListener("change", () => this.manager.syncFrom(this));
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x26323a, 2.1));
    const key = new THREE.DirectionalLight(0xffffff, 2.8);
    key.position.set(3, -4, 6);
    this.scene.add(key);
    const fill = new THREE.DirectionalLight(0x8fc8df, 1.2);
    fill.position.set(-4, 2, 1);
    this.scene.add(fill);
    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(container);
  }

  addGeometry(geometry, color, opacity = 1) {
    const material = new THREE.MeshStandardMaterial({
      color, roughness: 0.68, metalness: 0.05, transparent: opacity < 1,
      opacity, depthWrite: opacity >= 1, side: THREE.DoubleSide,
    });
    const mesh = new THREE.Mesh(geometry.clone(), material);
    this.scene.add(mesh);
    const edges = new THREE.LineSegments(
      new THREE.EdgesGeometry(geometry, 28),
      new THREE.LineBasicMaterial({ color: 0xe7edf0, transparent: true, opacity: 0.32 }),
    );
    this.scene.add(edges);
  }

  showInteractive() {
    this.container.dataset.viewerState = "ready";
    this.canvas.hidden = false;
    if (this.fallback) this.fallback.hidden = true;
    this.status.textContent = "";
  }

  showFallback(message) {
    this.container.dataset.viewerState = message === "Loading geometry" ? "loading" : "fallback";
    this.canvas.hidden = true;
    const hasFallback = Boolean(this.fallback?.getAttribute("src"));
    if (this.fallback) this.fallback.hidden = !hasFallback;
    this.status.textContent = hasFallback ? "" : message;
  }

  resize() {
    const width = Math.max(1, this.container.clientWidth);
    const height = Math.max(1, this.container.clientHeight);
    this.renderer.setSize(width, height, false);
    const halfHeight = this.manager.frustumHeight / 2;
    const halfWidth = halfHeight * width / height;
    this.camera.left = -halfWidth;
    this.camera.right = halfWidth;
    this.camera.top = halfHeight;
    this.camera.bottom = -halfHeight;
    this.camera.updateProjectionMatrix();
    this.render();
  }

  render() {
    if (!this.canvas.hidden) this.renderer.render(this.scene, this.camera);
  }

  dispose() {
    this.resizeObserver.disconnect();
    this.controls.dispose();
    this.scene.traverse((item) => {
      item.geometry?.dispose?.();
      if (Array.isArray(item.material)) item.material.forEach((material) => material.dispose());
      else item.material?.dispose?.();
    });
    this.renderer.dispose();
    this.renderer.forceContextLoss();
  }
}

class SynchronizedGeometryViewers {
  constructor(containers, geometry) {
    this.geometryPaths = geometry;
    this.frustumHeight = 1;
    this.center = new THREE.Vector3();
    this.distance = 10;
    this.syncing = false;
    this.disposed = false;
    this.viewports = Object.fromEntries(
      Object.entries(containers).map(([name, container]) => [name, new GeometryViewport(container, this)]),
    );
    this.resetBindings = Object.values(containers).map((container) => {
      const button = container.querySelector(".reset-view");
      const handler = () => this.reset();
      button?.addEventListener("click", handler);
      return { button, handler };
    });
    this.load();
  }

  async loadGeometry(path) {
    if (!path) return null;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10000);
    try {
      const response = await fetch(path, { cache: "no-store", signal: controller.signal });
      if (!response.ok) throw new Error(`Geometry request failed: ${response.status}`);
      const geometry = new STLLoader().parse(await response.arrayBuffer());
      geometry.computeVertexNormals();
      geometry.computeBoundingBox();
      return geometry;
    } finally {
      clearTimeout(timeout);
    }
  }

  async load() {
    Object.values(this.viewports).forEach((viewport) => viewport.showFallback("Loading geometry"));
    try {
      const [truth, candidate] = await Promise.all([
        this.loadGeometry(this.geometryPaths.ground_truth),
        this.loadGeometry(this.geometryPaths.candidate),
      ]);
      if (this.disposed) {
        truth?.dispose();
        candidate?.dispose();
        return;
      }
      const bounds = new THREE.Box3();
      if (truth?.boundingBox) bounds.union(truth.boundingBox);
      if (candidate?.boundingBox) bounds.union(candidate.boundingBox);
      if (bounds.isEmpty()) throw new Error("No interactive geometry is available");
      bounds.getCenter(this.center);
      const size = bounds.getSize(new THREE.Vector3());
      const span = Math.max(size.x, size.y, size.z, 1e-6);
      this.frustumHeight = span * 1.45;
      this.distance = span * 4;
      if (truth) {
        this.viewports.truth.addGeometry(truth, COLORS.truth);
        this.viewports.truth.showInteractive();
        this.viewports.overlay.addGeometry(truth, COLORS.truth, candidate ? 0.48 : 1);
        this.viewports.overlay.showInteractive();
      } else {
        this.viewports.truth.showFallback("Ground-truth geometry unavailable");
      }
      if (candidate) {
        this.viewports.candidate.addGeometry(candidate, COLORS.candidate);
        this.viewports.candidate.showInteractive();
        this.viewports.overlay.addGeometry(candidate, COLORS.candidate, truth ? 0.66 : 1);
        this.viewports.overlay.showInteractive();
      } else {
        this.viewports.candidate.showFallback("Candidate geometry unavailable");
        if (!truth) this.viewports.overlay.showFallback("Overlay geometry unavailable");
      }
      truth?.dispose();
      candidate?.dispose();
      this.reset();
    } catch (error) {
      if (this.disposed) return;
      Object.values(this.viewports).forEach((viewport) => viewport.showFallback(error.message));
    }
  }

  reset() {
    const source = Object.values(this.viewports).find((viewport) => !viewport.canvas.hidden);
    if (!source) return;
    source.camera.position.copy(this.center).addScaledVector(VIEW_DIRECTION, this.distance);
    source.camera.up.set(0, 0, 1);
    source.camera.zoom = 1;
    source.controls.target.copy(this.center);
    source.camera.near = Math.max(this.distance / 1000, 0.001);
    source.camera.far = this.distance * 10;
    source.camera.updateProjectionMatrix();
    source.controls.update();
    this.syncFrom(source);
  }

  syncFrom(source) {
    if (this.syncing || this.disposed) return;
    this.syncing = true;
    for (const viewport of Object.values(this.viewports)) {
      if (viewport !== source) {
        viewport.camera.position.copy(source.camera.position);
        viewport.camera.quaternion.copy(source.camera.quaternion);
        viewport.camera.up.copy(source.camera.up);
        viewport.camera.zoom = source.camera.zoom;
        viewport.camera.near = source.camera.near;
        viewport.camera.far = source.camera.far;
        viewport.controls.target.copy(source.controls.target);
        viewport.camera.updateProjectionMatrix();
        viewport.controls.update();
      }
      viewport.resize();
    }
    this.syncing = false;
  }

  dispose() {
    this.disposed = true;
    this.resetBindings.forEach(({ button, handler }) => button?.removeEventListener("click", handler));
    Object.values(this.viewports).forEach((viewport) => viewport.dispose());
  }
}

export function createSynchronizedGeometryViewers({ containers, geometry }) {
  try {
    return new SynchronizedGeometryViewers(containers, geometry);
  } catch (error) {
    Object.values(containers).filter(Boolean).forEach((container) => {
      const canvas = container.querySelector("canvas");
      const fallback = container.querySelector(".geometry-fallback");
      const status = container.querySelector(".viewer-status");
      if (canvas) canvas.hidden = true;
      const hasFallback = Boolean(fallback?.getAttribute("src"));
      if (fallback) fallback.hidden = !hasFallback;
      if (status) status.textContent = hasFallback ? "" : `3D viewer unavailable: ${error.message}`;
      container.dataset.viewerState = "fallback";
    });
    return { dispose() {} };
  }
}
