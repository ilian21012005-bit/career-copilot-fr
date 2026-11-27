"""Local Fedora hardware snapshot used by Mission Control."""

from __future__ import annotations

import os
from pathlib import Path

def _get_hardware_telemetry() -> dict:
    telemetry = {
        "cpu_usage": 0,
        "ram_total_mb": 0,
        "ram_used_mb": 0,
        "ram_avail_mb": 0,
        "ram_percent": 0.0,
        "disk_total_gb": 0.0,
        "disk_used_gb": 0.0,
        "disk_percent": 0.0,
        "temp_c": 0,
        "battery_pct": 0,
        "battery_status": "N/A",
        "uptime": "N/A"
    }

    try:
        with open("/proc/meminfo", "r") as f:
            lines = f.readlines()
        mem = {}
        for line in lines:
            parts = line.split(":")
            if len(parts) == 2:
                key = parts[0].strip()
                val = parts[1].strip().split()[0]
                mem[key] = int(val)
        total = mem.get("MemTotal", 0) // 1024
        avail = mem.get("MemAvailable", 0) // 1024
        used = total - avail
        telemetry["ram_total_mb"] = total
        telemetry["ram_avail_mb"] = avail
        telemetry["ram_used_mb"] = used
        telemetry["ram_percent"] = round((used / total * 100), 1) if total > 0 else 0
    except Exception:
        pass

    try:
        st = os.statvfs("/")
        total_b = st.f_blocks * st.f_frsize
        free_b = st.f_bavail * st.f_frsize
        used_b = total_b - free_b
        telemetry["disk_total_gb"] = round(total_b / (1024**3), 1)
        telemetry["disk_used_gb"] = round(used_b / (1024**3), 1)
        telemetry["disk_percent"] = round((used_b / total_b * 100), 1) if total_b > 0 else 0
    except Exception:
        pass

    try:
        with open("/proc/uptime", "r") as f:
            up_s = float(f.readline().split()[0])
            h = int(up_s // 3600)
            m = int((up_s % 3600) // 60)
            telemetry["uptime"] = f"{h}h {m}m"
    except Exception:
        pass

    try:
        for p in Path("/sys/class/thermal").glob("thermal_zone*"):
            t_file = p / "temp"
            if t_file.exists():
                c = int(t_file.read_text().strip()) // 1000
                if 20 <= c <= 105:
                    telemetry["temp_c"] = c
                    break
    except Exception:
        pass

    try:
        bat_dir = Path("/sys/class/power_supply/BAT0")
        if bat_dir.exists():
            cap = bat_dir / "capacity"
            stat = bat_dir / "status"
            if cap.exists():
                telemetry["battery_pct"] = int(cap.read_text().strip())
            if stat.exists():
                telemetry["battery_status"] = stat.read_text().strip()
    except Exception:
        pass

    return telemetry
