"""Small cross-process locks for note read/modify/write operations."""

import contextlib
import hashlib
import os
import sys
import tempfile


@contextlib.contextmanager
def note_lock(path, timeout=10):
    """Serialize cooperating writers without putting authoritative state on disk."""
    if sys.platform == "win32":
        import ctypes
        import ctypes.wintypes as wt

        name = "Local\\personaltracker-" + hashlib.sha256(
            os.path.abspath(path).lower().encode("utf-8")
        ).hexdigest()
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.argtypes = (ctypes.c_void_p, wt.BOOL, wt.LPCWSTR)
        kernel32.CreateMutexW.restype = wt.HANDLE
        kernel32.WaitForSingleObject.argtypes = (wt.HANDLE, wt.DWORD)
        kernel32.ReleaseMutex.argtypes = (wt.HANDLE,)
        kernel32.CloseHandle.argtypes = (wt.HANDLE,)
        handle = kernel32.CreateMutexW(None, False, name)
        if not handle:
            raise OSError("could not create note lock")
        result = kernel32.WaitForSingleObject(handle, timeout * 1000)
        if result not in (0, 0x80):
            kernel32.CloseHandle(handle)
            raise OSError("timed out waiting to write %s" % path)
        try:
            yield
        finally:
            kernel32.ReleaseMutex(handle)
            kernel32.CloseHandle(handle)
        return

    import fcntl

    lock_path = os.path.join(
        tempfile.gettempdir(),
        "personaltracker-" + hashlib.sha256(os.path.abspath(path).encode("utf-8")).hexdigest() + ".lock",
    )
    with open(lock_path, "a", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
