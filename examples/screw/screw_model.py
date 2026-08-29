"""Build a threaded screw (M8-like) in mm and render it to PNG with matplotlib."""
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

# ---------- parameters (mm) ----------
RC = 3.3            # core (minor) radius
H = 0.75            # thread height above core (to major radius ~4.05)
PITCH = 1.25        # thread pitch
N_TURNS = 16        # number of thread turns
Z_THREAD = N_TURNS * PITCH       # threaded shank length (=20)
HEAD_H = 4.0        # head thickness
R_HEAD = 6.8        # head radius (across corners, hexagonal)

# thread tooth cross-section: (radial height h, axial offset s)
PROFILE = [(0.0, -PITCH / 2), (H, -PITCH / 4), (H, PITCH / 4), (0.0, PITCH / 2)]
PROFILE = np.array(PROFILE)  # (nprof, 2)


def thread_grid(theta_steps_per_turn=40):
    """Return X, Y, Z grids of the helical thread ridge."""
    n_t = N_TURNS * theta_steps_per_turn
    theta = np.linspace(0, 2 * np.pi * N_TURNS, n_t, endpoint=False)
    z_c = PITCH * theta / (2 * np.pi)  # helix centerline rise
    h = PROFILE[:, 0]
    s = PROFILE[:, 1]
    r = RC + h  # radial position (nprof,)
    # broadcast: (n_t, nprof)
    R = np.broadcast_to(r, (n_t, len(r)))
    S = np.broadcast_to(s, (n_t, len(s)))
    TH = np.broadcast_to(theta[:, None], (n_t, len(s)))
    ZC = np.broadcast_to(z_c[:, None], (n_t, len(s)))
    X = R * np.cos(TH)
    Y = R * np.sin(TH)
    Z = ZC + S
    return X, Y, Z


def core_grid(density=60):
    """Core shaft cylinder surface from z=0..Z_THREAD."""
    n = density
    theta = np.linspace(0, 2 * np.pi, n)
    z = np.array([0.0, Z_THREAD])
    TH, Z = np.meshgrid(theta, z)
    X = RC * np.cos(TH)
    Y = RC * np.sin(TH)
    return X, Y, Z


def hex_head_faces():
    """Return list of faces (each a list of 3D points) for a hex head."""
    z0, z1 = Z_THREAD, Z_THREAD + HEAD_H
    ang = np.linspace(0, 2 * np.pi, 7)  # 7 points closes the hexagon
    px = R_HEAD * np.cos(ang[:-1])
    py = R_HEAD * np.sin(ang[:-1])
    pts = np.stack([px, py], axis=1)  # (6,2)
    faces = []
    for i in range(6):
        a, b = pts[i], pts[(i + 1) % 6]
        faces.append([(a[0], a[1], z0), (b[0], b[1], z0), (b[0], b[1], z1), (a[0], a[1], z1)])
    faces.append([(p[0], p[1], z0) for p in pts])  # bottom cap
    faces.append([(p[0], p[1], z1) for p in pts])  # top cap
    return faces


def render(path):
    fig = plt.figure(figsize=(7, 7))
    ax = fig.add_subplot(111, projection="3d")

    # threaded shank ridge
    Xt, Yt, Zt = thread_grid()
    ax.plot_surface(Xt, Yt, Zt, color="#9aa4ad", shade=True, rstride=4, cstride=1)

    # core shaft
    Xc, Yc, Zc = core_grid()
    ax.plot_surface(Xc, Yc, Zc, color="#7f8a93", shade=True)

    # hex head
    faces = hex_head_faces()
    ax.add_collection3d(Poly3DCollection(faces, facecolor="#b0b7bd", edgecolor="#6f7980"))

    # squash to equal aspect and frame the screw
    ax.set_box_aspect((1, 1, 1.7))
    ax.set_xlim(-R_HEAD - 1, R_HEAD + 1)
    ax.set_ylim(-R_HEAD - 1, R_HEAD + 1)
    ax.set_zlim(-1, Z_THREAD + HEAD_H + 1)
    ax.view_init(elev=18, azim=35)
    ax.set_axis_off()
    plt.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)
    print("SAVED", path)


def stats():
    X, Y, Z = thread_grid()
    print("thread grid shape:", X.shape)
    print("thread z range:", float(Z.min()), float(Z.max()))
    print("thread radial max:", float(np.sqrt(X**2 + Y**2).max()))
    print("finite:", bool(np.all(np.isfinite(X)) and np.all(np.isfinite(Y)) and np.all(np.isfinite(Z))))


if __name__ == "__main__":
    stats()
    root = Path(__file__).resolve().parents[2]
    output = root / "artifacts/examples/screw/screw_render.png"
    output.parent.mkdir(parents=True, exist_ok=True)
    render(output)
