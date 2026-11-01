"""Windows child ownership that survives the CLI parent's early exit.

The child starts suspended, enters a kill-on-close Job Object, and only then
runs. Job membership is inherited by descendants, including MCP servers.
"""

from __future__ import annotations

import ctypes
import subprocess
import time
from ctypes import wintypes

CREATE_SUSPENDED = 0x00000004


class _BasicLimits(ctypes.Structure):
    _fields_ = [('PerProcessUserTimeLimit', ctypes.c_int64), ('PerJobUserTimeLimit', ctypes.c_int64),
                ('LimitFlags', wintypes.DWORD), ('MinimumWorkingSetSize', ctypes.c_size_t),
                ('MaximumWorkingSetSize', ctypes.c_size_t), ('ActiveProcessLimit', wintypes.DWORD),
                ('Affinity', ctypes.c_size_t), ('PriorityClass', wintypes.DWORD),
                ('SchedulingClass', wintypes.DWORD)]


class _IOCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint64) for name in (
        'ReadOperationCount', 'WriteOperationCount', 'OtherOperationCount',
        'ReadTransferCount', 'WriteTransferCount', 'OtherTransferCount')]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [('BasicLimitInformation', _BasicLimits), ('IoInfo', _IOCounters),
                ('ProcessMemoryLimit', ctypes.c_size_t), ('JobMemoryLimit', ctypes.c_size_t),
                ('PeakProcessMemoryUsed', ctypes.c_size_t), ('PeakJobMemoryUsed', ctypes.c_size_t)]


class _ThreadEntry(ctypes.Structure):
    _fields_ = [('dwSize', wintypes.DWORD), ('cntUsage', wintypes.DWORD),
                ('th32ThreadID', wintypes.DWORD), ('th32OwnerProcessID', wintypes.DWORD),
                ('tpBasePri', wintypes.LONG), ('tpDeltaPri', wintypes.LONG),
                ('dwFlags', wintypes.DWORD)]


class _Accounting(ctypes.Structure):
    _fields_ = [('TotalUserTime', ctypes.c_int64), ('TotalKernelTime', ctypes.c_int64),
                ('ThisPeriodTotalUserTime', ctypes.c_int64), ('ThisPeriodTotalKernelTime', ctypes.c_int64),
                ('TotalPageFaultCount', wintypes.DWORD), ('TotalProcesses', wintypes.DWORD),
                ('ActiveProcesses', wintypes.DWORD), ('TotalTerminatedProcesses', wintypes.DWORD)]


def _kernel32():
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    signatures = {
        'CreateJobObjectW': ([ctypes.c_void_p, wintypes.LPCWSTR], wintypes.HANDLE),
        'SetInformationJobObject': ([wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD], wintypes.BOOL),
        'AssignProcessToJobObject': ([wintypes.HANDLE, wintypes.HANDLE], wintypes.BOOL),
        'OpenProcess': ([wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
        'WaitForSingleObject': ([wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD),
        'TerminateJobObject': ([wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
        'QueryInformationJobObject': ([wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                       wintypes.DWORD, ctypes.c_void_p], wintypes.BOOL),
        'CloseHandle': ([wintypes.HANDLE], wintypes.BOOL),
        'CreateToolhelp32Snapshot': ([wintypes.DWORD, wintypes.DWORD], wintypes.HANDLE),
        'Thread32First': ([wintypes.HANDLE, ctypes.POINTER(_ThreadEntry)], wintypes.BOOL),
        'Thread32Next': ([wintypes.HANDLE, ctypes.POINTER(_ThreadEntry)], wintypes.BOOL),
        'OpenThread': ([wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
        'ResumeThread': ([wintypes.HANDLE], wintypes.DWORD),
    }
    for name, (arguments, result) in signatures.items():
        method = getattr(kernel, name)
        method.argtypes = arguments
        method.restype = result
    return kernel


class WindowsJob:
    def __init__(self):
        self.kernel = _kernel32()
        self.handle = self.kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = _ExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = 0x00002000  # KILL_ON_JOB_CLOSE
        if not self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            error = ctypes.get_last_error()
            self.close()
            raise ctypes.WinError(error)

    def assign(self, process):
        if not self.kernel.AssignProcessToJobObject(self.handle, wintypes.HANDLE(int(process._handle))):
            raise ctypes.WinError(ctypes.get_last_error())

    def resume(self, process):
        # Popen closes its primary thread handle. The suspended process cannot
        # spawn other threads, so find that thread through documented Toolhelp.
        snapshot = self.kernel.CreateToolhelp32Snapshot(0x00000004, 0)  # SNAPTHREAD
        if snapshot == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            entry = _ThreadEntry()
            entry.dwSize = ctypes.sizeof(entry)
            found = self.kernel.Thread32First(snapshot, ctypes.byref(entry))
            while found:
                if entry.th32OwnerProcessID == process.pid:
                    thread = self.kernel.OpenThread(0x0002, False, entry.th32ThreadID)  # SUSPEND_RESUME
                    if not thread:
                        raise ctypes.WinError(ctypes.get_last_error())
                    try:
                        if self.kernel.ResumeThread(thread) == 0xFFFFFFFF:
                            raise ctypes.WinError(ctypes.get_last_error())
                    finally:
                        self.kernel.CloseHandle(thread)
                    return
                found = self.kernel.Thread32Next(snapshot, ctypes.byref(entry))
            raise OSError('Suspended child thread was not found')
        finally:
            self.kernel.CloseHandle(snapshot)

    def close(self):
        if self.handle:
            handle, self.handle = self.handle, None
            processes = []
            try:
                deadline = time.monotonic() + 5
                # Job accounting can reach zero before each process object is
                # signaled. Retain actual process handles *before* termination
                # so venv launchers and MCP descendants are fully reaped too.
                for process_id in self._process_ids(handle, deadline):
                    process = self.kernel.OpenProcess(0x00100000, False, process_id)  # SYNCHRONIZE
                    if process:
                        processes.append(process)
                    elif ctypes.get_last_error() != 87:  # INVALID_PARAMETER: already exited
                        raise ctypes.WinError(ctypes.get_last_error())
                if not self.kernel.TerminateJobObject(handle, 1):
                    raise ctypes.WinError(ctypes.get_last_error())
                for process in processes:
                    remaining_ms = max(0, int((deadline - time.monotonic()) * 1000))
                    result = self.kernel.WaitForSingleObject(process, remaining_ms)
                    if result == 258:  # WAIT_TIMEOUT
                        raise TimeoutError('Windows validation process exceeded the cleanup deadline')
                    if result != 0:  # WAIT_OBJECT_0
                        raise ctypes.WinError(ctypes.get_last_error())
                while True:
                    accounting = _Accounting()
                    if not self.kernel.QueryInformationJobObject(
                            handle, 1, ctypes.byref(accounting), ctypes.sizeof(accounting), None):
                        raise ctypes.WinError(ctypes.get_last_error())
                    if not accounting.ActiveProcesses:
                        break
                    if time.monotonic() >= deadline:
                        raise TimeoutError('Windows validation job did not stop before the cleanup deadline')
                    time.sleep(.01)
            finally:
                for process in processes:
                    self.kernel.CloseHandle(process)
                if not self.kernel.CloseHandle(handle):
                    raise ctypes.WinError(ctypes.get_last_error())

    def _process_ids(self, handle, deadline):
        capacity = 16
        while True:
            if time.monotonic() >= deadline:
                raise TimeoutError('Windows validation process snapshot exceeded the cleanup deadline')

            class ProcessList(ctypes.Structure):
                _fields_ = [('NumberOfAssignedProcesses', wintypes.DWORD),
                            ('NumberOfProcessIdsInList', wintypes.DWORD),
                            ('ProcessIdList', ctypes.c_size_t * capacity)]

            listing = ProcessList()
            if self.kernel.QueryInformationJobObject(handle, 3, ctypes.byref(listing), ctypes.sizeof(listing), None):
                return list(listing.ProcessIdList[:listing.NumberOfProcessIdsInList])
            if ctypes.get_last_error() != 234:  # ERROR_MORE_DATA
                raise ctypes.WinError(ctypes.get_last_error())
            capacity = max(capacity * 2, listing.NumberOfAssignedProcesses)


def start_job_process(command, **options):
    """Return (Popen, job); closing job always kills remaining descendants."""
    job = WindowsJob()
    process = None
    try:
        options['creationflags'] = options.get('creationflags', 0) | CREATE_SUSPENDED
        process = subprocess.Popen(command, **options)
        job.assign(process)
        job.resume(process)
        return process, job
    except BaseException:
        # If assignment or resumption fails, never leave a suspended child.
        try:
            if process is not None:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=5)
                if process.stdout:
                    process.stdout.close()
                if process.stderr:
                    process.stderr.close()
        finally:
            job.close()
        raise
