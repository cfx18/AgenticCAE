"""Draw a threaded screw in AutoCAD 2024 via COM and save it as screw.dwg."""
import math
from pathlib import Path
import time

import pywintypes
import win32com.client

import pythoncom

# RPC_E_CALL_REJECTED / RPC_E_SERVERCALL_RETRYLATER: AutoCAD busy -> retry.
_RETRY_HRESULTS = {-2147418111, -2147417846}


def call(fn, *args, attempts=40, delay=0.5, **kwargs):
    """Call fn(*args), retrying when AutoCAD briefly rejects the COM call."""
    for i in range(attempts):
        try:
            return fn(*args, **kwargs)
        except pywintypes.com_error as e:
            if e.hresult in _RETRY_HRESULTS and i < attempts - 1:
                time.sleep(delay)
                continue
            raise


def wait_count(ms, expected, timeout=45):
    """Wait until ModelSpace has at least `expected` entities."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if call(lambda: ms.Count) >= expected:
                return
        except Exception:
            pass
        time.sleep(1)
    raise TimeoutError(f"ModelSpace count did not reach {expected}")


def variant_array(values):
    return win32com.client.VARIANT(
        pythoncom.VT_ARRAY | pythoncom.VT_R8, list(values)
    )


def main():
    app = call(win32com.client.gencache.EnsureDispatch, "AutoCAD.Application")
    print("CONNECTED to AutoCAD", app.Version)

    if call(lambda: app.Documents.Count) > 0:
        doc = call(lambda: app.ActiveDocument)
    else:
        doc = call(lambda: app.Documents.Add())
    print("Using document:", call(lambda: doc.Name))
    ms = call(lambda: doc.ModelSpace)

    # ---- 1) Helix (thread path): radius 5, 12 turns, height 30 ----
    n0 = call(lambda: ms.Count)
    call(lambda: doc.SendCommand("_DELOBJ\n0\n_HELIX\n0,0,0\n5\n5\nT\n12\n30\n"))
    wait_count(ms, n0 + 1)
    helix = call(lambda: ms.Item(n0))
    print("Helix:", call(lambda: helix.ObjectName))

    # ---- 2) Thread profile: closed triangle, base sits on helix start ----
    # Outer point at crest (5.0), inner at root (4.2), pitch step 1.8.
    flat = [5.0, 0.0, 4.2, 0.0, 4.2, 1.8]
    poly = call(lambda: ms.AddLightWeightPolyline(variant_array(flat)))
    call(lambda: setattr(poly, "Closed", True))
    n1 = call(lambda: ms.Count)

    # ---- 3) Sweep the triangle along the helix ----
    # Select profile with L, empty Enter ends selection, then pick path.
    call(lambda: doc.SendCommand("_SWEEP\nL\n\n0,5,0\n"))
    try:
        wait_count(ms, n1 + 1)
    except TimeoutError:
        call(lambda: doc.SendCommand("\n"))  # empty Enter cancels pending prompt
        raise
    thread = call(lambda: ms.Item(call(lambda: ms.Count) - 1))
    print("Thread solid:", call(lambda: thread.ObjectName))
    call(lambda: helix.Delete())
    call(lambda: poly.Delete())

    # ---- 4) Shaft ----
    shaft = call(lambda: ms.AddCylinder((0.0, 0.0, 0.0), 4.15, 28.0))

    # ---- 5) Hex head ----
    hex_flat = []
    for i in range(6):
        a = math.radians(i * 60)
        hex_flat += [8.0 * math.cos(a), 8.0 * math.sin(a)]
    hexpoly = call(lambda: ms.AddLightWeightPolyline(variant_array(hex_flat)))
    call(lambda: setattr(hexpoly, "Closed", True))
    head = call(lambda: ms.AddExtrudedSolid(hexpoly, 8.0, 0.0))
    call(lambda: head.Move((0.0, 0.0, 0.0), (0.0, 0.0, 29.5)))
    call(lambda: hexpoly.Delete())

    # ---- 6) Pointed tip ----
    tip = call(lambda: ms.AddCone((0.0, 0.0, -1.5), 4.15, 2.0))

    # ---- 7) Union everything into one screw ----
    call(lambda: shaft.Boolean(0, thread))  # 0 = union
    call(lambda: shaft.Boolean(0, head))
    call(lambda: shaft.Boolean(0, tip))
    screw = shaft
    print("Final solid:", call(lambda: screw.ObjectName))

    # ---- 8) Verify via geometry data (not pixels) ----
    minpt = win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, [0, 0, 0])
    maxpt = win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, [0, 0, 0])
    try:
        call(lambda: screw.GetBoundingBox(minpt, maxpt))
        print("Bounding box min:", list(minpt.value))
        print("Bounding box max:", list(maxpt.value))
    except Exception as e:
        print("Bounding box query failed:", e)
    print("Entities in drawing:", call(lambda: ms.Count))

    # ---- 9) Save + set a nice 3D view ----
    root = Path(__file__).resolve().parents[2]
    path = root / "artifacts/examples/screw/screw.dwg"
    path.parent.mkdir(parents=True, exist_ok=True)
    call(lambda: doc.SaveAs(str(path)))
    call(lambda: doc.SendCommand("_VPOINT\n1,-1,1\n_ZOOM\nE\n_SHADEMODE\nR\n"))
    time.sleep(3)
    print("Saved:", path)
    print("DONE - look at the AutoCAD window")


if __name__ == "__main__":
    main()
