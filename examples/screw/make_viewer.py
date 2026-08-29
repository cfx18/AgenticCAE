"""Generate an in-conversation interactive 3D viewer fragment for the screw."""
from pathlib import Path

import numpy as np

from screw_model import thread_grid, core_grid, hex_head_faces, Z_THREAD, HEAD_H

THETA_PER_TURN = 18  # keep the mesh compact for inline embedding


def grid_tris(X, Y, Z):
    tris = []
    r, c = X.shape
    for i in range(r - 1):
        for j in range(c - 1):
            a = (X[i, j], Y[i, j], Z[i, j])
            b = (X[i, j + 1], Y[i, j + 1], Z[i, j + 1])
            cc = (X[i + 1, j + 1], Y[i + 1, j + 1], Z[i + 1, j + 1])
            d = (X[i + 1, j], Y[i + 1, j], Z[i + 1, j])
            tris.append((a, b, cc))
            tris.append((a, cc, d))
    return tris


def build_verts():
    tris = []
    Xt, Yt, Zt = thread_grid(theta_steps_per_turn=THETA_PER_TURN)
    tris.extend(grid_tris(Xt, Yt, Zt))
    Xc, Yc, Zc = core_grid(density=48)
    tris.extend(grid_tris(Xc, Yc, Zc))
    for f in hex_head_faces():
        for k in range(1, len(f) - 1):
            tris.append((f[0], f[k], f[k + 1]))

    verts = []
    for tri in tris:
        for p in tri:
            verts.extend((round(p[0], 2), round(p[1], 2), round(p[2], 2)))
    return verts, len(tris)


def main():
    verts, ntris = build_verts()
    xs = verts[0::3]
    ys = verts[1::3]
    zs = verts[2::3]
    cx = (min(xs) + max(xs)) / 2
    cy = (min(ys) + max(ys)) / 2
    cz = (min(zs) + max(zs)) / 2
    arr = []
    for i in range(0, len(verts), 3):
        arr.append(round(verts[i] - cx, 2))
        arr.append(round(verts[i + 1] - cy, 2))
        arr.append(round(verts[i + 2] - cz, 2))

    verts_js = ",".join(str(v) for v in arr)
    print("triangles:", ntris)
    print("floats:", len(arr))
    print("verts_js size (chars):", len(verts_js))

    template = '''<div id="screw-viewer" style="position:relative;width:100%;height:480px;overflow:hidden;"></div>
<p class="text-muted text-small">拖拽旋转 · 滚轮缩放 · 右键平移</p>
<script type="module">
import * as THREE from 'https://esm.sh/three@0.160.0';
import { OrbitControls } from 'https://esm.sh/three@0.160.0/examples/jsm/controls/OrbitControls.js';

const root = document.getElementById('screw-viewer');
const verts = [__VERTS__];
const geometry = new THREE.BufferGeometry();
geometry.setAttribute('position', new THREE.Float32BufferAttribute(verts, 3));
geometry.computeVertexNormals();

const material = new THREE.MeshStandardMaterial({
  color: 0xb7bec5, metalness: 0.1, roughness: 0.45,
  side: THREE.DoubleSide, flatShading: true,
});
const mesh = new THREE.Mesh(geometry, material);

const scene = new THREE.Scene();
scene.add(new THREE.AmbientLight(0xffffff, 0.55));
const dir = new THREE.DirectionalLight(0xffffff, 0.85);
dir.position.set(45, 70, 55);
scene.add(dir);
scene.add(mesh);

const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
renderer.setSize(root.clientWidth, root.clientHeight);
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
root.appendChild(renderer.domElement);

const camera = new THREE.PerspectiveCamera(45, root.clientWidth / root.clientHeight, 0.1, 1000);
camera.position.set(42, 46, 58);

const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.08;

function animate() {
  requestAnimationFrame(animate);
  controls.update();
  renderer.render(scene, camera);
}
animate();
</script>'''

    html = template.replace("__VERTS__", verts_js)
    root = Path(__file__).resolve().parents[2]
    out = root / "artifacts/examples/screw/screw-viewer.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        f.write(html)
    print("WROTE", out)
    print("file size (chars):", len(html))


if __name__ == "__main__":
    main()
