"""Quick smoke test: connect to a running AutoCAD 2024 via COM and draw a line."""
import time

import pythoncom
import pywintypes
import win32com.client

# RPC_E_CALL_REJECTED / RPC_E_SERVERCALL_RETRYLATER: AutoCAD is busy, retry.
_RETRY_HRESULTS = {-2147418111, -2147417846}


def call(fn, *args, attempts=20, delay=0.5, **kwargs):
    """Call fn(*args) retrying when AutoCAD briefly rejects the COM call."""
    for i in range(attempts):
        try:
            return fn(*args, **kwargs)
        except pywintypes.com_error as e:
            if e.hresult in _RETRY_HRESULTS and i < attempts - 1:
                time.sleep(delay)
                continue
            raise


def main():
    app = call(win32com.client.GetActiveObject, "AutoCAD.Application")
    print("CONNECTED to AutoCAD", app.Version)

    if call(lambda: app.Documents.Count) == 0:
        doc = call(lambda: app.Documents.Add())
        print("Created document:", doc.Name)
    else:
        doc = call(lambda: app.ActiveDocument)
        print("Using document:", doc.Name)

    ms = call(lambda: doc.ModelSpace)
    n_before = call(lambda: ms.Count)

    # Draw a line from (0,0,0) to (100,100,0)
    def point3d(x, y, z):
        return win32com.client.VARIANT(
            pythoncom.VT_ARRAY | pythoncom.VT_R8, (x, y, z)
        )

    line = call(lambda: ms.AddLine(point3d(0, 0, 0), point3d(100, 100, 0)))
    n_after = call(lambda: ms.Count)
    print("Line object:", call(lambda: line.ObjectName))
    print("Entities before/after:", n_before, "->", n_after)
    print("SMOKE TEST OK")


if __name__ == "__main__":
    main()
