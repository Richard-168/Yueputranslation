"""Give application-private CPython hosts a per-process UTF-8 Windows manifest."""

import ctypes
import hashlib
import struct
import xml.etree.ElementTree as ET
from ctypes import wintypes as w


def utf8_manifest(data):
    root = ET.fromstring(data)
    level = root.find(".//{urn:schemas-microsoft-com:asm.v3}requestedExecutionLevel")
    settings = root.find(".//{urn:schemas-microsoft-com:asm.v3}windowsSettings")
    if level is None or level.get("level") != "asInvoker" or settings is None:
        raise ValueError("Unrecognized private Python host manifest")
    namespace = "http://schemas.microsoft.com/SMI/2019/WindowsSettings"
    node = settings.find("{" + namespace + "}activeCodePage")
    if node is None:
        node = ET.SubElement(settings, "{" + namespace + "}activeCodePage")
    node.text = "UTF-8"
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def patch_host(path):
    original = path.read_bytes()
    original_digest = hashlib.sha256(original).hexdigest()
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LoadLibraryExW.argtypes = [w.LPCWSTR, w.HANDLE, w.DWORD]
    kernel.LoadLibraryExW.restype = w.HMODULE
    kernel.FindResourceW.argtypes = [w.HMODULE, ctypes.c_void_p, ctypes.c_void_p]
    kernel.FindResourceW.restype = ctypes.c_void_p
    kernel.SizeofResource.argtypes = [w.HMODULE, ctypes.c_void_p]
    kernel.SizeofResource.restype = w.DWORD
    kernel.LoadResource.argtypes = [w.HMODULE, ctypes.c_void_p]
    kernel.LoadResource.restype = ctypes.c_void_p
    kernel.LockResource.argtypes = [ctypes.c_void_p]
    kernel.LockResource.restype = ctypes.c_void_p
    kernel.FreeLibrary.argtypes = [w.HMODULE]
    callback_type = ctypes.WINFUNCTYPE(
        w.BOOL, w.HMODULE, ctypes.c_void_p, ctypes.c_void_p, w.WORD, w.LPARAM
    )
    kernel.EnumResourceLanguagesW.argtypes = [
        w.HMODULE,
        ctypes.c_void_p,
        ctypes.c_void_p,
        callback_type,
        w.LPARAM,
    ]
    languages = []

    @callback_type
    def language_callback(module, resource_type, name, language, parameter):
        languages.append(language)
        return True

    module = kernel.LoadLibraryExW(str(path.resolve()), None, 2)
    if not module:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        resource = kernel.FindResourceW(module, 1, 24)
        if not resource:
            raise ctypes.WinError(ctypes.get_last_error())
        size = kernel.SizeofResource(module, resource)
        pointer = kernel.LockResource(kernel.LoadResource(module, resource))
        manifest = utf8_manifest(ctypes.string_at(pointer, size))
        if (
            not kernel.EnumResourceLanguagesW(module, 24, 1, language_callback, 0)
            or len(languages) != 1
        ):
            raise ValueError("Expected exactly one Python host manifest language")
    finally:
        kernel.FreeLibrary(module)
    # A modified PE must not retain a now-invalid vendor signature. This does
    # not sign or claim to preserve PSF's signature; the development host is unsigned.
    data = bytearray(original)
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    optional = pe + 24
    if data[pe : pe + 4] != b"PE\0\0" or struct.unpack_from("<H", data, optional)[0] != 0x20B:
        raise ValueError("Expected a Windows x64 CPython PE image")
    certificate = optional + 112 + 4 * 8
    address, length = struct.unpack_from("<II", data, certificate)
    if address:
        if address + length != len(data):
            raise ValueError("Unexpected signed Python overlay")
        del data[address:]
        struct.pack_into("<II", data, certificate, 0, 0)
    temporary = path.with_suffix(".utf8-host")
    temporary.write_bytes(data)
    temporary.replace(path)
    kernel.BeginUpdateResourceW.argtypes = [w.LPCWSTR, w.BOOL]
    kernel.BeginUpdateResourceW.restype = w.HANDLE
    kernel.UpdateResourceW.argtypes = [
        w.HANDLE,
        ctypes.c_void_p,
        ctypes.c_void_p,
        w.WORD,
        ctypes.c_void_p,
        w.DWORD,
    ]
    kernel.UpdateResourceW.restype = w.BOOL
    kernel.EndUpdateResourceW.argtypes = [w.HANDLE, w.BOOL]
    kernel.EndUpdateResourceW.restype = w.BOOL
    handle = kernel.BeginUpdateResourceW(str(path.resolve()), False)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    buffer = ctypes.create_string_buffer(manifest)
    if not kernel.UpdateResourceW(handle, 24, 1, languages[0], buffer, len(manifest)):
        kernel.EndUpdateResourceW(handle, True)
        raise ctypes.WinError(ctypes.get_last_error())
    if not kernel.EndUpdateResourceW(handle, False):
        raise ctypes.WinError(ctypes.get_last_error())
    return dict(
        path="python/" + path.name,
        upstream_sha256=original_digest,
        patched_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        reason="Private host UTF-8 activeCodePage manifest; obsolete vendor signature removed",
    )
