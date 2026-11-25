"""A new SIMPL program for a given processor, as SIMPL 4.32's File > New SIMPL program writes it.

Decoded from SIMPL's own new CP4N program (f12-round8, made by driving SIMPL's window). The
processor's whole device tree comes from the device library through device_edit's builder; the
rest is fixed: the header, five top-level symbols, and empty FP and Bk records.
"""
from __future__ import annotations

from ..catalog.devices import DeviceLibrary
from .device_edit import _Build
from .rawfile import RawFile, Record

TOP_SYMBOLS = [  # (handle, SmC, Nm): what every new program starts with
    (1, "157", "Central Control Modules"), (2, "157", "Network Modules"), (3, "157", "Ethernet"),
    (4, "156", "Logic"), (5, "157", "DefineArguments"),
]


def installed_versions() -> dict[str, str]:
    """SIMPL's version and its Crestron/device database versions, from the registry and smpwin.exe."""
    import winreg

    out = {}
    base = r"SOFTWARE\WOW6432Node\Crestron Electronics Inc."
    for key, name in (("Crestron Database", "DbVr"), ("Device Database", "DvcDbVr")):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base + "\\" + key) as k:
                out[name] = winreg.QueryValueEx(k, "Version")[0]
        except OSError:
            pass
    return out


def smpwin_version(exe: str = r"C:\Program Files (x86)\Crestron\Simpl\smpwin.exe") -> tuple[str, str] | None:
    """('4.32.02', 'SMW4.3200.02') from smpwin.exe's file version (4.3200.02)."""
    import ctypes

    size = ctypes.windll.version.GetFileVersionInfoSizeW(exe, None)
    if not size:
        return None
    buf = ctypes.create_string_buffer(size)
    ctypes.windll.version.GetFileVersionInfoW(exe, 0, size, buf)
    ptr, n = ctypes.c_void_p(), ctypes.c_uint()
    ctypes.windll.version.VerQueryValueW(buf, "\\", ctypes.byref(ptr), ctypes.byref(n))
    ms, ls = ctypes.cast(ptr.value + 8, ctypes.POINTER(ctypes.c_uint32 * 2)).contents
    major, minor, build = ms >> 16, ms & 0xFFFF, ls >> 16
    return f"{major}.{minor // 100:02d}.{build:02d}", f"SMW{major}.{minor:04d}.{build:02d}"


def new_program(devlib: DeviceLibrary, lib, processor, *, file_name: str, system_name: str = "",
                versions: dict[str, str], lib_version: str) -> RawFile:
    """The records of a new program. ``versions``: RelVrs, SavedBy, DbVr, DvcDbVr."""
    from .edit import EditError, Editor

    hd = [("ObjTp", "Hd"), ("CnC", str(processor.code)), ("CnH", "2"), ("S0Nd", "1"), ("S1Nd", "2"), ("SLNd", "3"),
          ("PrNm", file_name), ("DbVr", versions["DbVr"]), ("DvcDbVr", versions["DvcDbVr"])]
    if system_name:
        hd.append(("CltNm", system_name))
    hd += [("SmVr", lib_version), ("DvVr", lib_version), ("TpN1", "1"), ("TpN2", "2"), ("TpN3", "3"),
           ("TpN4", "4"), ("TpN5", "5"), ("APg", "1"), ("FltTmp", "1"), ("FpCS", "0"), ("EnType", "0"),
           ("ZeroOnIoOk", "0"), ("PIT", ""), ("SGMethod", "1")]
    raw = RawFile(items=[
        Record(lines=[("Version", "1")]),
        Record(lines=[("ObjTp", "FSgntr"), ("Sgntr", "SimplWindow"), ("RelVrs", versions["RelVrs"]),
                      ("IntStrVrs", "2"), ("MinSMWVrs", processor.fields.get("SMWRev") or "4.14.00"),
                      ("MinTIOVrs", processor.fields.get("TIORev") or "1099"), ("SavedBy", versions["SavedBy"])]),
        Record(lines=hd),
    ])
    ed = Editor(raw, lib)
    b = _Build(ed, devlib, lib_version, lib_version, next_sm=len(TOP_SYMBOLS) + 1, next_cm=1)
    try:
        _, top_syms = b.device(processor, handle=2, parent=1, address="00", slot_code=None, sym_parent=1, db=1)
    except EditError as e:
        raise EditError(f"can't build a {processor.name} program yet: {e}") from None
    dv = sorted(b.dv, key=lambda lines: int(dict(lines)["H"].split(",")[0].split(".")[0]))
    raw.items += [Record(lines=lines) for lines in dv]
    raw.items += [Record(lines=lines) for lines in b.cm]
    raw.items.append(Record(lines=[("ObjTp", "Db"), ("H", "1"), ("DvH", "2"), ("Whc", "3"), ("Mnf", "Crestron"),
                                   ("Mdl", processor.name)]))
    raw.items.append(Record(lines=[("ObjTp", "FP")]))
    raw.items.append(Record(lines=[("ObjTp", "Bk"), ("Nm1", "\\"), ("Sx1", "0"), ("Sy1", "0"), ("Mx1", "0")]))
    for h, code, name in TOP_SYMBOLS:
        lines = [("ObjTp", "Sm"), ("H", str(h)), ("SmC", code), ("Nm", name), ("ObjVer", "1"),
                 ("SmVr", lib_version), ("CF", "2")]
        if code == "157":
            lines += [("n1I", "1"), ("n1O", "1")]
            if h == 1 and top_syms:
                lines += [("mC", str(len(top_syms)))] + [(f"C{i}", str(c)) for i, c in enumerate(top_syms, 1)]
            lines += [("mI", "1"), ("mO", "1"), ("tO", "1"), ("mP", "1"), ("P1", "")]
        raw.items.append(Record(lines=lines))
    raw.items += [Record(lines=b.sm[h]) for h in sorted(b.sm)]
    return raw
