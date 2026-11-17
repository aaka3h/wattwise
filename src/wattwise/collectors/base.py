"""Shared cross-platform hardware telemetry helpers, NVIDIA SMI bridge, and process attribution."""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

import psutil

from wattwise.models import HardwareComponent, PowerSnapshot, ProcessPower

WIN_NO_WINDOW: int = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def run_cmd_quiet(cmd: list[str], timeout: float = 1.8) -> Optional[str]:
    """Run an external CLI command safely without flashing console windows on Windows."""
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            creationflags=WIN_NO_WINDOW if os.name == "nt" else 0,
        )
        if proc.returncode == 0 and proc.stdout:
            return proc.stdout.strip()
    except Exception:
        return None
    return None


def infer_cpu_tdp_watts(brand: str, logical_cores: int, is_laptop: bool = True) -> float:
    """Infer realistic nominal CPU package TDP (Watts) from CPU brand string and core count."""
    b = (brand or "").upper()

    # Apple Silicon M-series
    if "APPLE M" in b:
        if "ULTRA" in b:
            return 110.0
        if "MAX" in b:
            return 58.0
        if "PRO" in b:
            return 34.0
        return 20.0

    # Intel / AMD mobile & desktop suffixes
    if re.search(r"\b\w+HX\b", b) or "13650HX" in b or "13900HX" in b or "14900HX" in b:
        return 55.0
    if re.search(r"\d{4,5}HK\b", b) or re.search(r"\d{4,5}H\b", b):
        return 45.0
    if re.search(r"\d{4,5}HS\b", b):
        return 35.0
    if re.search(r"\d{4,5}P\b", b):
        return 28.0
    if re.search(r"\d{4,5}U\b", b) or "N100" in b or "N95" in b:
        return 15.0
    if re.search(r"\d{4,5}Y\b", b):
        return 9.0
    if re.search(r"\d{4,5}K[FS]?\b", b) or "THREADRIPPER" in b or "9950X" in b or "7950X" in b:
        return 125.0
    if re.search(r"\d{4,5}X3D\b", b) or re.search(r"\d{4,5}X\b", b):
        return 105.0

    if is_laptop:
        return 45.0 if logical_cores >= 16 else (28.0 if logical_cores >= 12 else 18.0)
    return 95.0 if logical_cores >= 16 else 65.0


def model_cpu_watts(
    tdp_watts: float,
    util_pct: float,
    freq_cur_mhz: Optional[float] = None,
    freq_min_mhz: Optional[float] = None,
    freq_max_mhz: Optional[float] = None,
) -> float:
    """Physics-informed DVFS + utilization model for CPU package power when RAPL/SMC is locked."""
    u = max(0.0, min(100.0, util_pct)) / 100.0
    idle_w = max(2.2, tdp_watts * 0.085)

    # Incorporate frequency scaling (V^2 * f dynamic power relation) when available
    freq_factor = 1.0
    if freq_cur_mhz and freq_max_mhz and freq_max_mhz > 400:
        f_min = freq_min_mhz if (freq_min_mhz and 100 <= freq_min_mhz < freq_max_mhz) else 800.0
        span = max(200.0, freq_max_mhz - f_min)
        norm_f = max(0.15, min(1.25, (freq_cur_mhz - f_min) / span))
        freq_factor = 0.55 + 0.55 * (norm_f ** 1.15)

    dynamic_w = (tdp_watts - idle_w) * (u ** 0.82) * freq_factor
    return round(max(idle_w * 0.8, min(tdp_watts * 1.45, idle_w + dynamic_w)), 2)


@dataclass
class NvidiaGpuReading:
    index: int
    name: str
    watts: float
    util_pct: Optional[float]
    temp_c: Optional[float]


def find_nvidia_smi() -> Optional[str]:
    """Locate nvidia-smi across Linux and Windows standard paths."""
    found = shutil.which("nvidia-smi")
    if found:
        return found
    if os.name == "nt":
        candidates = [
            r"C:\Windows\System32\nvidia-smi.exe",
            r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe",
        ]
        for c in candidates:
            if os.path.isfile(c):
                return c
    return None


def query_nvidia_gpus() -> tuple[list[NvidiaGpuReading], dict[int, float]]:
    """Query NVIDIA GPU power draw (W), utilization (%), temperature (C), and per-PID SM %."""
    smi = find_nvidia_smi()
    if not smi:
        return [], {}

    out = run_cmd_quiet(
        [
            smi,
            "--query-gpu=index,name,power.draw,utilization.gpu,temperature.gpu",
            "--format=csv,noheader,nounits",
        ],
        timeout=1.5,
    )
    gpus: list[NvidiaGpuReading] = []
    if out:
        for line in out.splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 3:
                continue
            try:
                idx = int(parts[0])
                name = parts[1]
                watts_s = parts[2]
                watts = float(watts_s) if watts_s and "N/A" not in watts_s.upper() else 0.0
                util = (
                    float(parts[3])
                    if len(parts) > 3 and parts[3] and "N/A" not in parts[3].upper()
                    else None
                )
                temp = (
                    float(parts[4])
                    if len(parts) > 4 and parts[4] and "N/A" not in parts[4].upper()
                    else None
                )
                gpus.append(
                    NvidiaGpuReading(
                        index=idx,
                        name=name,
                        watts=max(0.0, watts),
                        util_pct=util,
                        temp_c=temp,
                    )
                )
            except ValueError:
                continue

    pid_sm: dict[int, float] = {}
    if gpus:
        pmon = run_cmd_quiet([smi, "pmon", "-c", "1"], timeout=1.5)
        if pmon:
            for line in pmon.splitlines():
                s = line.strip()
                if not s or s.startswith("#"):
                    continue
                cols = s.split()
                # Format: gpu pid type sm mem enc dec jpg ofa command
                if len(cols) >= 5:
                    try:
                        pid = int(cols[1])
                        sm_val = float(cols[3]) if cols[3] != "-" else 0.0
                        mem_val = float(cols[4]) if cols[4] != "-" else 0.0
                        score = sm_val + 0.25 * mem_val
                        if score > 0:
                            pid_sm[pid] = pid_sm.get(pid, 0.0) + score
                    except ValueError:
                        continue

    return gpus, pid_sm


class ProcessAttributionTracker:
    """Tracks per-process CPU time, GPU SM %, and Disk I/O deltas to apportion active Watts."""

    def __init__(self) -> None:
        self._prev_ts: float = 0.0
        self._prev_cpu: dict[int, float] = {}
        self._prev_io: dict[int, int] = {}
        self._energy_by_app: dict[str, float] = {}

    @staticmethod
    def _clean_app_name(raw_name: str) -> str:
        name = (raw_name or "system").strip()
        for suffix in (".exe", ".bin", "-bin"):
            if name.lower().endswith(suffix) and len(name) > len(suffix):
                name = name[: -len(suffix)]
        return name[:42]

    def sample_processes(
        self,
        now_ts: float,
        cpu_total_watts: float,
        gpu_total_watts: float,
        storage_active_watts: float,
        gpu_pid_scores: Optional[dict[int, float]] = None,
        top_n: int = 18,
    ) -> list[ProcessPower]:
        dt_sec = (now_ts - self._prev_ts) if self._prev_ts > 0 else 0.0
        valid_dt = 0.1 <= dt_sec <= 15.0
        logical_cpus = max(1, psutil.cpu_count(logical=True) or 1)
        gpu_pid_scores = gpu_pid_scores or {}

        cur_cpu: dict[int, float] = {}
        cur_io: dict[int, int] = {}

        # Aggregated per-app buckets
        apps: dict[str, dict[str, float | int]] = {}

        for proc in psutil.process_iter(["pid", "name", "memory_info"]):
            try:
                info = proc.info
                pid = int(info["pid"])
                if pid == 0:
                    continue
                ct = proc.cpu_times()
                c_total = float(ct.user + ct.system)
                cur_cpu[pid] = c_total

                io_bytes = 0
                try:
                    ioc = proc.io_counters()
                    if ioc:
                        io_bytes = int(ioc.read_bytes + ioc.write_bytes)
                        cur_io[pid] = io_bytes
                except (psutil.AccessDenied, AttributeError, OSError):
                    pass

                cpu_delta = max(0.0, c_total - self._prev_cpu.get(pid, c_total)) if valid_dt else 0.0
                io_delta = max(0, io_bytes - self._prev_io.get(pid, io_bytes)) if (valid_dt and pid in self._prev_io) else 0

                cpu_pct_norm = (cpu_delta / dt_sec) * 100.0 / logical_cpus if valid_dt else 0.0
                io_mbps = (io_delta / (1024.0 * 1024.0)) / dt_sec if valid_dt else 0.0
                gpu_score = float(gpu_pid_scores.get(pid, 0.0))
                mem_info = info.get("memory_info")
                mem_mb = float(mem_info.rss) / (1024.0 * 1024.0) if mem_info else 0.0

                if cpu_pct_norm < 0.02 and gpu_score <= 0.0 and io_mbps < 0.05 and mem_mb < 80.0:
                    continue

                app = self._clean_app_name(info.get("name") or f"pid-{pid}")
                entry = apps.get(app)
                if entry is None:
                    apps[app] = {
                        "primary_pid": pid,
                        "pid_count": 1,
                        "cpu_pct": cpu_pct_norm,
                        "gpu_score": gpu_score,
                        "mem_mb": mem_mb,
                        "io_mbps": io_mbps,
                        "best_weight": cpu_pct_norm + gpu_score,
                    }
                else:
                    entry["pid_count"] = int(entry["pid_count"]) + 1
                    entry["cpu_pct"] = float(entry["cpu_pct"]) + cpu_pct_norm
                    entry["gpu_score"] = float(entry["gpu_score"]) + gpu_score
                    entry["mem_mb"] = float(entry["mem_mb"]) + mem_mb
                    entry["io_mbps"] = float(entry["io_mbps"]) + io_mbps
                    if (cpu_pct_norm + gpu_score) > float(entry["best_weight"]):
                        entry["best_weight"] = cpu_pct_norm + gpu_score
                        entry["primary_pid"] = pid
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, ValueError):
                continue

        self._prev_cpu = cur_cpu
        self._prev_io = cur_io
        self._prev_ts = now_ts

        total_cpu_pct = sum(float(v["cpu_pct"]) for v in apps.values())
        total_gpu_score = sum(float(v["gpu_score"]) for v in apps.values())
        total_io_mbps = sum(float(v["io_mbps"]) for v in apps.values())

        # Active dynamic pool (~78% of CPU watts + ~65% of GPU watts when GPU active + storage active watts)
        attributable_cpu_w = max(0.0, cpu_total_watts * 0.80)
        attributable_gpu_w = max(0.0, gpu_total_watts * 0.70) if total_gpu_score > 0 else 0.0
        attributable_io_w = max(0.0, storage_active_watts) if total_io_mbps > 0.1 else 0.0

        results: list[ProcessPower] = []
        for app_name, v in apps.items():
            c_pct = float(v["cpu_pct"])
            g_sc = float(v["gpu_score"])
            io_m = float(v["io_mbps"])

            w_cpu = (
                attributable_cpu_w * (c_pct / max(total_cpu_pct, 100.0))
                if total_cpu_pct > 0
                else 0.0
            )
            # If total_cpu_pct > 15%, scale up toward full active CPU pool proportionally
            if total_cpu_pct > 5.0:
                busy_ratio = min(1.0, total_cpu_pct / 35.0)
                w_cpu = attributable_cpu_w * busy_ratio * (c_pct / total_cpu_pct)

            w_gpu = (
                attributable_gpu_w * (g_sc / max(total_gpu_score, 40.0))
                if total_gpu_score > 0
                else 0.0
            )
            w_io = (
                attributable_io_w * (io_m / total_io_mbps)
                if total_io_mbps > 0.1
                else 0.0
            )
            # Small DRAM refresh/active allocation proportional to RSS footprint (~0.08 W / GB)
            w_mem = (float(v["mem_mb"]) / 1024.0) * 0.075

            app_watts = round(max(0.0, w_cpu + w_gpu + w_io + w_mem), 3)
            if valid_dt and app_watts > 0:
                self._energy_by_app[app_name] = (
                    self._energy_by_app.get(app_name, 0.0) + app_watts * (dt_sec / 3600.0)
                )

            results.append(
                ProcessPower(
                    app_name=app_name,
                    primary_pid=int(v["primary_pid"]),
                    pid_count=int(v["pid_count"]),
                    cpu_pct=round(c_pct * logical_cpus, 1),
                    gpu_pct=round(min(100.0, g_sc), 1),
                    memory_mb=round(float(v["mem_mb"]), 1),
                    io_mbps=round(io_m, 2),
                    watts=app_watts,
                    energy_wh=round(self._energy_by_app.get(app_name, 0.0), 5),
                )
            )

        results.sort(key=lambda p: (p.watts, p.energy_wh, p.memory_mb), reverse=True)
        return results[:top_n]


class BasePlatformCollector(ABC):
    """Abstract base class for OS-specific power telemetry collectors."""

    def __init__(self) -> None:
        self._proc_tracker = ProcessAttributionTracker()
        self._prev_disk_bytes: Optional[int] = None
        self._prev_net_bytes: Optional[int] = None
        self._prev_io_ts: float = 0.0
        # Prime psutil cpu_percent non-blocking baseline
        psutil.cpu_percent(interval=None)

    def _sample_io_rates(self, now_ts: float) -> tuple[float, float]:
        """Return (disk_mb_per_sec, net_mb_per_sec) since previous sample."""
        dt_sec = now_ts - self._prev_io_ts if self._prev_io_ts > 0 else 0.0
        disk_mbps = 0.0
        net_mbps = 0.0

        try:
            dio = psutil.disk_io_counters()
            if dio:
                cur_d = int(dio.read_bytes + dio.write_bytes)
                if self._prev_disk_bytes is not None and 0.1 <= dt_sec <= 30.0:
                    disk_mbps = max(0.0, (cur_d - self._prev_disk_bytes) / (1024.0 * 1024.0) / dt_sec)
                self._prev_disk_bytes = cur_d
        except Exception:
            pass

        try:
            nio = psutil.net_io_counters()
            if nio:
                cur_n = int(nio.bytes_sent + nio.bytes_recv)
                if self._prev_net_bytes is not None and 0.1 <= dt_sec <= 30.0:
                    net_mbps = max(0.0, (cur_n - self._prev_net_bytes) / (1024.0 * 1024.0) / dt_sec)
                self._prev_net_bytes = cur_n
        except Exception:
            pass

        self._prev_io_ts = now_ts
        return disk_mbps, net_mbps

    @staticmethod
    def host_platform_banner() -> str:
        sys_name = platform.system()
        mach = platform.machine()
        if sys_name == "Darwin":
            if mach in ("arm64", "aarch64"):
                return "macOS Apple Silicon (M-Series arm64)"
            return f"macOS Intel ({mach})"
        if sys_name == "Windows":
            rel = platform.release()
            return f"Windows {rel} ({mach})"
        return f"{sys_name} ({mach})"

    @abstractmethod
    def collect(self) -> PowerSnapshot:
        """Collect a complete instantaneous PowerSnapshot."""
