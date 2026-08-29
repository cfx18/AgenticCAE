"""Write a threaded screw into the running AutoCAD 2024 via COM."""
import time

import numpy as np
import pywintypes
import win32com.client
import pythoncom

from screw_model import RC, H, PITCH, N_TURNS, Z_THREAD, HEAD_H, R_HEAD, thread_grid

_RETRY_HRESULTS = {-2147418111, -2147417846}


def call(fn, *args, attempts=30, delay=0.5, **kwargs):
    for _ in range(attempts):
        try:
            return fn(*args, **kwargs)
        except pywintypes.com_error as e:
            if e.hresult in _RETRY_HRESULTS:
                time.sleep(delay)
                continue
            raise


def point3d(x, y, z):
    return win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, (float(x), float(y), float(z)))


def arr(arr1d):
    return win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, [float(v) for v in arr1d])


def main():
    app = call(win32com.client.GetActiveObject, "AutoCAD.Application")
    if call(lambda: app.Documents.Count) == 0:
        doc = call(lambda: app.Documents.Add())
    else:
        doc = call(lambda: app.ActiveDocument)
    print("Using document:", doc.Name)

    ms = call(lambda: doc.ModelSpace)

    # core shaft (solid cylinder)
    call(lambda: ms.AddCylinder(point3d(0, 0, Z_THREAD / 2), RC, Z_THREAD))
    # head (solid cylinder)
    call(lambda: ms.AddCylinder(point3d(0, 0, Z_THREAD + HEAD_H / 2), R_HEAD, HEAD_H))

    # thread as a 3D mesh surface (corrugated helical ridge)
    X, Y, Z = thread_grid(theta_steps_per_turn=20)
    R = X.shape[0]  # rows = theta steps
    flat = np.stack([X, Y, Z], axis=-1).reshape(-1)  # (R*4*3,)
    call(lambda: ms.Add3DMesh(R, 4, arr(flat)))

    n = call(lambda: ms.Count)
    print("Model space entities:", n)

    call(lambda: app.ZoomExtents())
    print("DONE")


if __name__ == "__main__":
    main()
