"""Read-only, bounded accessibility text from the window frozen at release.

Window ownership is sampled on the GUI thread while Arrow is hidden. Slow UIA
reads happen later on a worker against that handle, never the new foreground.
"""
from __future__ import annotations

import os
import sys
import time
from typing import Any

from arrow.capture.coordinate_mapper import CoordinateMapper


def read_accessible_window(root, *, max_chars=80000, max_nodes=2000, max_seconds=2) -> dict:
    lines, seen = [], set()
    count, size = 0, 0
    truncated = False
    stack = [root]
    deadline = time.monotonic() + max_seconds
    while stack:
        if count >= max_nodes or size >= max_chars or time.monotonic() >= deadline:
            truncated = True
            break
        node = stack.pop()
        count += 1
        try:
            if node.IsPassword:
                continue
        except AttributeError:
            # Some providers do not expose this property. Never read ValuePattern.
            pass
        except Exception:
            truncated = True
            continue
        text, document = '', ''
        try:
            text = str(node.Name or '').strip()
        except Exception:
            truncated = True
        if getattr(node, 'ControlTypeName', '') == 'DocumentControl':
            try:
                pattern = node.GetTextPattern()
                if pattern:
                    document = pattern.DocumentRange.GetText(max_chars - size + 1)
            except Exception:
                truncated = True
        for value in (text, document):
            value = (value or '').strip()
            if not value or value in seen:
                continue
            seen.add(value)
            remaining = max_chars - size - (1 if lines else 0)
            if len(value) > remaining:
                truncated = True
            if remaining <= 0:
                break
            lines.append(value[:remaining])
            size += len(lines[-1]) + (1 if len(lines) > 1 else 0)
        # A provider failure on one property must not hide all descendants.
        try:
            stack.extend(reversed(node.GetChildren()))
        except Exception:
            truncated = True
    return {'available': True, 'text': '\n'.join(lines), 'truncated': truncated,
            'status': 'partial' if truncated else 'complete', 'nodes_read': count}


def freeze_window_targets(annotations, *, screens=None, owner_lookup=None) -> dict:
    if owner_lookup is None and sys.platform != 'win32':
        return {}
    if not annotations:
        return {}
    mapper = CoordinateMapper(screens) if screens is not None else CoordinateMapper.from_qt()
    locate = owner_lookup or _window_at_point
    targets = {}
    for annotation in annotations:
        role = annotation.role
        if role not in ('source', 'destination') or role in targets:
            continue
        geom = annotation.geometry
        cx = geom.get('x', 0) + geom.get('width', 0) / 2
        cy = geom.get('y', 0) + geom.get('height', 0) / 2
        screen, px, py = mapper.virtual_to_physical(cx, cy)
        # Qt/Windows retains each monitor's physical origin under per-monitor DPI.
        point = (round(screen.x + px), round(screen.y + py))
        targets[role] = {'handle': 0, 'window_title': '', 'physical_point': list(point)}
        try:
            target = locate(*point)
            if target:
                targets[role] = {**target, 'physical_point': list(point)}
        except Exception:
            continue
    return targets


def _window_at_point(x, y) -> dict:
    import ctypes
    from ctypes import wintypes as wt
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.WindowFromPoint.argtypes = [wt.POINT]
    user.WindowFromPoint.restype = wt.HWND
    user.GetAncestor.argtypes = [wt.HWND, wt.UINT]
    user.GetAncestor.restype = wt.HWND
    user.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
    user.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
    user.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
    handle = user.GetAncestor(user.WindowFromPoint(wt.POINT(x, y)), 2)
    if not handle:
        return {}
    title, rect, pid = ctypes.create_unicode_buffer(2048), wt.RECT(), wt.DWORD()
    user.GetWindowTextW(handle, title, len(title))
    user.GetWindowRect(handle, ctypes.byref(rect))
    user.GetWindowThreadProcessId(handle, ctypes.byref(pid))
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
    kernel.OpenProcess.restype = wt.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)]
    kernel.CloseHandle.argtypes = [wt.HANDLE]
    process = ''
    proc = kernel.OpenProcess(0x1000, False, pid.value)
    if proc:
        try:
            path, length = ctypes.create_unicode_buffer(32768), wt.DWORD(32768)
            if kernel.QueryFullProcessImageNameW(proc, 0, path, ctypes.byref(length)):
                process = os.path.basename(path.value)
        finally:
            kernel.CloseHandle(proc)
    return {'handle': int(handle), 'window_title': title.value, 'process': process, 'pid': pid.value,
            'bounds': [rect.left, rect.top, rect.right, rect.bottom]}


def _read_target(target) -> dict:
    if sys.platform != 'win32':
        return {'available': False, 'text': '', 'status': 'unavailable'}
    import uiautomation as auto
    with auto.UIAutomationInitializerInThread():
        root = auto.ControlFromHandle(target['handle'])
        if root is None or root.Name != target.get('window_title'):
            return {'available': False, 'text': '', 'status': 'window_changed'}
        result = read_accessible_window(root)
        try:
            element = auto.ControlFromPoint(*target['physical_point'])
            parent = element
            owned = False
            for _ in range(64):
                if parent is None:
                    break
                if parent.NativeWindowHandle == target['handle']:
                    owned = True
                    break
                parent = parent.GetParentControl()
            if owned and not element.IsPassword:
                result['element'] = {'name': element.Name, 'control_type': element.ControlTypeName,
                                     'automation_id': element.AutomationId}
        except Exception:
            pass
        return result


def collect_window_contexts(targets, *, reader=None) -> dict[str, Any]:
    result = {}
    for role, target in targets.items():
        try:
            if not target.get('handle'):
                raise ValueError('Window ownership is unavailable')
            evidence = (reader or _read_target)(target)
        except Exception:
            evidence = {'available': False, 'text': '', 'status': 'unavailable'}
        result[role] = {**target, **evidence}
    return result
