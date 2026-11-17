"""Read Windows GPU counters and adapter properties without loading a model."""

import ctypes as C
from dataclasses import dataclass
import re
from uuid import UUID


@dataclass(frozen=True)
class Adapter:
    name: str
    location: str
    total: int | None = None
    luid: tuple[int, int] | None = None
    pci: tuple[int, int, int] | None = None
    uuid: str = ""
    vendor: int = 0


UINT = C.c_uint32
PVOID = C.c_void_p
SIZE_T = C.c_size_t
HRESULT = C.c_int32


class Luid(C.Structure):
    _fields_ = [("low", UINT), ("high", C.c_int32)]


class AdapterDesc(C.Structure):
    _fields_ = [
        ("description", C.c_wchar * 128),
        ("vendor", UINT), ("device", UINT), ("subsystem", UINT), ("revision", UINT),
        ("dedicated", SIZE_T), ("dedicated_system", SIZE_T), ("shared", SIZE_T),
        ("luid", Luid), ("flags", UINT),
    ]


class OpenAdapter(C.Structure):
    _fields_ = [("luid", Luid), ("handle", UINT)]


class CloseAdapter(C.Structure):
    _fields_ = [("handle", UINT)]


class AdapterInfo(C.Structure):
    _fields_ = [("handle", UINT), ("kind", UINT), ("data", PVOID), ("size", UINT)]


class AdapterAddress(C.Structure):
    _fields_ = [("bus", UINT), ("device", UINT), ("function", UINT)]


# D3DKMT_ADAPTER_PERFDATA, including the SDK's 64-bit field alignment.
class AdapterPerfData(C.Structure):
    _fields_ = [
        ("physical_index", UINT),
        ("memory_frequency", C.c_uint64), ("max_memory_frequency", C.c_uint64),
        ("max_memory_frequency_oc", C.c_uint64), ("memory_bandwidth", C.c_uint64),
        ("pcie_bandwidth", C.c_uint64), ("fan_rpm", UINT), ("power", UINT),
        ("temperature", UINT), ("power_state_override", C.c_uint8),
    ]


class PdhNumber(C.Union):
    _fields_ = [("number", C.c_double), ("large", C.c_int64), ("text", C.c_wchar_p)]


class PdhValue(C.Structure):
    _fields_ = [("status", UINT), ("value", PdhNumber)]


class PdhItem(C.Structure):
    _fields_ = [("name", C.c_wchar_p), ("formatted", PdhValue)]


LOAD_LIBRARY_SEARCH_SYSTEM32 = 0x800
DXGI_ERROR_NOT_FOUND = 0x887A0002
DXGI_ADAPTER_FLAG_SOFTWARE = 2
FACTORY1_IID = (C.c_ubyte * 16).from_buffer_copy(UUID("770aae78-f26f-4dba-a829-253c83d1b387").bytes_le)
KMTQAITYPE_ADAPTERADDRESS = 6
KMTQAITYPE_ADAPTERPERFDATA = 62
PDH_MORE_DATA = 0x800007D2
PDH_FMT_DOUBLE = 0x0200
PDH_FMT_LARGE = 0x0400
PDH_FMT_NOCAP100 = 0x8000
COUNTER_INSTANCE = re.compile(r"luid_0x([0-9a-f]+)_0x([0-9a-f]+)_phys_(\d+)(?:_eng_(\d+))?", re.I)


def bind(library, name, result, *arguments):
    function = getattr(library, name)
    function.restype = result
    function.argtypes = arguments
    return function


def com_method(interface, slot, result, *arguments):
    vtable = C.cast(interface, C.POINTER(C.POINTER(PVOID))).contents
    return C.WINFUNCTYPE(result, PVOID, *arguments)(vtable[slot])


def release(interface):
    com_method(interface, 2, UINT)(interface)  # IUnknown::Release


def samples_for_adapter(items, luid):
    for name, number in items:
        match = COUNTER_INSTANCE.search(name)
        if match and (int(match[1], 16), int(match[2], 16)) == luid:
            yield match[3], match[4], number


class WindowsGpu:
    def __init__(self):
        dxgi = C.WinDLL("dxgi.dll", winmode=LOAD_LIBRARY_SEARCH_SYSTEM32)
        gdi = C.WinDLL("gdi32.dll", winmode=LOAD_LIBRARY_SEARCH_SYSTEM32)
        pdh = C.WinDLL("pdh.dll", winmode=LOAD_LIBRARY_SEARCH_SYSTEM32)
        self.create_factory = bind(dxgi, "CreateDXGIFactory1", HRESULT, PVOID, C.POINTER(PVOID))
        self.open_adapter = bind(gdi, "D3DKMTOpenAdapterFromLuid", HRESULT, C.POINTER(OpenAdapter))
        self.close_adapter = bind(gdi, "D3DKMTCloseAdapter", HRESULT, C.POINTER(CloseAdapter))
        self.adapter_info = bind(gdi, "D3DKMTQueryAdapterInfo", HRESULT, C.POINTER(AdapterInfo))
        self.open_query = bind(pdh, "PdhOpenQueryW", UINT, C.c_wchar_p, SIZE_T, C.POINTER(PVOID))
        self.add_counter = bind(pdh, "PdhAddEnglishCounterW", UINT, PVOID, C.c_wchar_p, SIZE_T, C.POINTER(PVOID))
        self.collect_query = bind(pdh, "PdhCollectQueryData", UINT, PVOID)
        self.formatted_array = bind(pdh, "PdhGetFormattedCounterArrayW", UINT, PVOID, UINT, C.POINTER(UINT), C.POINTER(UINT), PVOID)
        self.close_query = bind(pdh, "PdhCloseQuery", UINT, PVOID)
        self.query = PVOID()
        self.usage = PVOID()
        self.memory = PVOID()
        self.sampled_query = False

    def query_adapter(self, luid, kind, data):
        high, low = luid
        opened = OpenAdapter(Luid(low, high))
        if self.open_adapter(C.byref(opened)) < 0:
            return False
        try:
            request = AdapterInfo(opened.handle, kind, C.addressof(data), C.sizeof(data))
            return self.adapter_info(C.byref(request)) >= 0
        finally:
            self.close_adapter(C.byref(CloseAdapter(opened.handle)))

    def adapters(self):
        factory = PVOID()
        if self.create_factory(C.byref(FACTORY1_IID), C.byref(factory)) < 0:
            return []
        adapters = []
        try:
            enumerate_adapter = com_method(factory, 12, HRESULT, UINT, C.POINTER(PVOID))  # IDXGIFactory1::EnumAdapters1
            index = 0
            while True:
                adapter = PVOID()
                result = enumerate_adapter(factory, index, C.byref(adapter))
                if result & 0xFFFFFFFF == DXGI_ERROR_NOT_FOUND or result < 0:
                    break
                index += 1
                try:
                    desc = AdapterDesc()
                    get_desc = com_method(adapter, 10, HRESULT, C.POINTER(AdapterDesc))  # IDXGIAdapter1::GetDesc1
                    if get_desc(adapter, C.byref(desc)) < 0 or desc.flags & DXGI_ADAPTER_FLAG_SOFTWARE:
                        continue
                    luid = (desc.luid.high & 0xFFFFFFFF, desc.luid.low)
                    address = AdapterAddress()
                    pci = None
                    if self.query_adapter(luid, KMTQAITYPE_ADAPTERADDRESS, address):
                        pci = (address.bus, address.device, address.function)
                    location = "PCI %02x:%02x.%x" % pci if pci is not None else "Adapter %08x:%08x" % luid
                    adapters.append(Adapter(desc.description.strip(), location, desc.dedicated or None, luid, pci, vendor=desc.vendor))
                finally:
                    release(adapter)
        finally:
            release(factory)
        return adapters

    def start_counters(self):
        if self.query:
            return True
        if self.open_query(None, 0, C.byref(self.query)):
            return False
        if self.add_counter(self.query, r"\GPU Engine(*)\Utilization Percentage", 0, C.byref(self.usage)):
            self.usage = PVOID()
        if self.add_counter(self.query, r"\GPU Adapter Memory(*)\Dedicated Usage", 0, C.byref(self.memory)):
            self.memory = PVOID()
        return True

    def counter_items(self, counter, formatted_type, field):
        if not counter:
            return []
        size, count = UINT(), UINT()
        status = self.formatted_array(counter, formatted_type, C.byref(size), C.byref(count), None)
        # A process can create an engine instance while the buffer is allocated.
        for _ in range(2):
            if status != PDH_MORE_DATA or not size.value:
                return []
            buf = C.create_string_buffer(size.value)
            status = self.formatted_array(counter, formatted_type, C.byref(size), C.byref(count), buf)
            if status == 0:
                items = C.cast(buf, C.POINTER(PdhItem))
                return [
                    (item.name, getattr(item.formatted.value, field))
                    for item in (items[i] for i in range(count.value))
                    if item.name and item.formatted.status in (0, 1)
                ]
        return []

    def sample(self, adapter, metrics):
        values = {}
        counters_ok = bool(metrics & {"gpu", "vram"}) and self.start_counters() and self.collect_query(self.query) == 0
        if counters_ok:
            if "gpu" in metrics and self.sampled_query:
                # Processes sharing one engine add up. Parallel engines shouldn't
                # be added together: report the busiest engine on this adapter.
                engines = {}
                items = self.counter_items(self.usage, PDH_FMT_DOUBLE | PDH_FMT_NOCAP100, "number")
                for physical, engine, usage in samples_for_adapter(items, adapter.luid):
                    if engine is not None and 0.0 <= usage < float("inf"):
                        key = (physical, engine)
                        engines[key] = engines.get(key, 0) + usage
                if engines:
                    values["usage"] = min(100.0, max(engines.values()))
            self.sampled_query = True
            if "vram" in metrics and adapter.total:
                items = self.counter_items(self.memory, PDH_FMT_LARGE, "large")
                used = [amount for _, _, amount in samples_for_adapter(items, adapter.luid) if amount >= 0]
                if used:
                    values["vram"] = {"used": sum(used), "total": adapter.total}
        if "temp" in metrics:
            perf = AdapterPerfData()
            if self.query_adapter(adapter.luid, KMTQAITYPE_ADAPTERPERFDATA, perf) and 0 < perf.temperature <= 2000:
                values["temperature"] = perf.temperature / 10
        return values

    def close(self):
        if self.query:
            self.close_query(self.query)
        self.query = PVOID()
        self.usage = PVOID()
        self.memory = PVOID()
        self.sampled_query = False
