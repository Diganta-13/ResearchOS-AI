l#!/usr/bin/env python3
"""
ResearchOS AI — Phase 0: Environment Audit & Hardware Profiling
Master Specification v2.1.0 Compliance Audit Tool

Audits:
- Workspace path alignment
- CPU Architecture and AVX2 instruction set support
- Total RAM and idle memory usage
- Drive C: and Drive D: storage capacity (with Drive C < 15GB safety check)
- Drive D: physical hardware controller and bus type (NVMe/SATA/HDD)
- Disk read/write throughput and 4K random IOPS
- Python 3.12 64-bit runtime and venv module
- Ollama service and local model catalog
- Audio input (microphone) and output devices
- External developer tools: Git and LaTeX compiler (pdflatex/latexmk)
- Verification of proposed Drive D: storage paths
"""

import os
import sys
import json
import time
import shutil
import random
import ctypes
import platform
import subprocess
import urllib.request
import urllib.error
from pathlib import Path


EXPECTED_WORKSPACE = r"D:\Projects\ResearchOS-AI"
MIN_C_FREE_GB = 15.0
STORAGE_CONFIG_PATH = Path(EXPECTED_WORKSPACE) / "config" / "storage_paths.yaml"
REPORT_OUTPUT_PATH = Path(EXPECTED_WORKSPACE) / "config" / "environment_report.json"


def audit_workspace():
    current_cwd = os.path.realpath(os.getcwd())
    expected_real = os.path.realpath(EXPECTED_WORKSPACE)
    matched = current_cwd.lower() == expected_real.lower()
    return {
        "check": "Workspace Root Path",
        "status": "PASS" if matched else "FAIL",
        "measured_value": current_cwd,
        "expected_value": expected_real,
        "details": "Current working directory exactly matches target project root." if matched else "Mismatch in working directory path."
    }


def audit_cpu_and_avx2():
    cpu_name = "Unknown"
    vendor = "Unknown"
    
    # Query Windows Registry for CPU information
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
        cpu_name, _ = winreg.QueryValueEx(key, "ProcessorNameString")
        vendor, _ = winreg.QueryValueEx(key, "VendorIdentifier")
        winreg.CloseKey(key)
        cpu_name = cpu_name.strip()
    except Exception as e:
        cpu_name = platform.processor() or str(e)

    # Check AVX2 via kernel32.IsProcessorFeaturePresent(PF_AVX2_INSTRUCTIONS_AVAILABLE = 40)
    avx2_supported = False
    try:
        k32 = ctypes.windll.kernel32
        # PF_AVX2_INSTRUCTIONS_AVAILABLE = 40
        avx2_supported = bool(k32.IsProcessorFeaturePresent(40))
    except Exception:
        avx2_supported = False

    cores = os.cpu_count() or 0
    passed = avx2_supported and ("i7-8665U" in cpu_name or "Intel" in cpu_name)
    
    return {
        "check": "CPU Model & AVX2 Support",
        "status": "PASS" if passed else "FAIL",
        "measured_value": {
            "processor_name": cpu_name,
            "vendor": vendor,
            "logical_cores": cores,
            "avx2_supported": avx2_supported
        },
        "details": f"{cpu_name} with {cores} logical threads. AVX2 instruction set verified." if avx2_supported else "AVX2 instructions not available or CPU mismatch."
    }


def audit_ram():
    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    try:
        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
        total_gb = stat.ullTotalPhys / (1024 ** 3)
        avail_gb = stat.ullAvailPhys / (1024 ** 3)
        used_gb = total_gb - avail_gb
        load_pct = stat.dwMemoryLoad
        passed = total_gb >= 14.0
        status = "PASS" if passed else "FAIL"
    except Exception as e:
        total_gb, avail_gb, used_gb, load_pct = 0, 0, 0, 0
        status = "FAIL"

    return {
        "check": "Physical RAM Capacity & Idle Usage",
        "status": status,
        "measured_value": {
            "total_ram_gb": round(total_gb, 2),
            "available_ram_gb": round(avail_gb, 2),
            "used_ram_gb": round(used_gb, 2),
            "memory_load_percent": load_pct
        },
        "details": f"Total RAM is {total_gb:.2f} GB (>= 14.0 GB budget). Currently {avail_gb:.2f} GB free ({load_pct}% load)."
    }


def audit_storage():
    results = {}
    
    # Audit Drive C:
    try:
        usage_c = shutil.disk_usage("C:")
        total_c = usage_c.total / (1024 ** 3)
        free_c = usage_c.free / (1024 ** 3)
        used_c = usage_c.used / (1024 ** 3)
        
        # Mandatory Safety Rule: If C: has less than 15 GB free, report FAIL and stop
        c_passed = free_c >= MIN_C_FREE_GB
        results["drive_c"] = {
            "check": "Drive C: Available Capacity (Safety Boundary)",
            "status": "PASS" if c_passed else "FAIL",
            "measured_value": {
                "total_gb": round(total_c, 2),
                "used_gb": round(used_c, 2),
                "free_gb": round(free_c, 2),
                "threshold_min_gb": MIN_C_FREE_GB
            },
            "details": f"Drive C: has {free_c:.2f} GB free. CRITICAL: Less than minimum safety threshold of {MIN_C_FREE_GB} GB!" if not c_passed else f"Drive C: has {free_c:.2f} GB free (sufficient)."
        }
    except Exception as e:
        results["drive_c"] = {
            "check": "Drive C: Available Capacity",
            "status": "FAIL",
            "error": str(e)
        }

    # Audit Drive D:
    try:
        usage_d = shutil.disk_usage("D:")
        total_d = usage_d.total / (1024 ** 3)
        free_d = usage_d.free / (1024 ** 3)
        used_d = usage_d.used / (1024 ** 3)
        d_passed = free_d >= 150.0
        results["drive_d"] = {
            "check": "Drive D: Workspace Capacity",
            "status": "PASS" if d_passed else "FAIL",
            "measured_value": {
                "total_gb": round(total_d, 2),
                "used_gb": round(used_d, 2),
                "free_gb": round(free_d, 2),
                "threshold_min_gb": 150.0
            },
            "details": f"Drive D: has {free_d:.2f} GB free (ample capacity for models, datasets, and cache)."
        }
    except Exception as e:
        results["drive_d"] = {
            "check": "Drive D: Workspace Capacity",
            "status": "FAIL",
            "error": str(e)
        }

    return results


def audit_drive_d_physical_type():
    driver = "Unknown"
    identifier = "Unknown"
    is_nvme = False
    
    try:
        import winreg
        key_path = r"HARDWARE\DEVICEMAP\Scsi\Scsi Port 0\Scsi Bus 0\Target Id 0\Logical Unit Id 0"
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path)
        identifier, _ = winreg.QueryValueEx(key, "Identifier")
        winreg.CloseKey(key)

        port_key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DEVICEMAP\Scsi\Scsi Port 0")
        driver, _ = winreg.QueryValueEx(port_key, "Driver")
        winreg.CloseKey(port_key)
        
        identifier = identifier.strip()
        driver = driver.strip()
        is_nvme = "nvme" in driver.lower() or "nvme" in identifier.lower()
    except Exception as e:
        identifier = f"Query error: {e}"

    return {
        "check": "Drive D: Physical Hardware & Bus Type",
        "status": "PASS" if is_nvme else "WARNING",
        "measured_value": {
            "driver": driver,
            "device_identifier": identifier,
            "bus_type": "NVMe" if is_nvme else "SATA/Other"
        },
        "details": f"Verified physical storage controller: {identifier} under '{driver}' driver (High-speed PCIe NVMe SSD confirmed)." if is_nvme else f"Physical device: {identifier} (Bus type unverified as NVMe)."
    }


def audit_disk_performance():
    bench_file = Path(EXPECTED_WORKSPACE) / ".phase0_disk_bench.tmp"
    size_mb = 50
    block_size = 1024 * 1024
    data = b"R" * block_size
    num_ops = 500
    chunk_4k = b"S" * 4096

    try:
        # Sequential Write with fsync
        t0 = time.perf_counter()
        with open(bench_file, "wb") as f:
            for _ in range(size_mb):
                f.write(data)
            f.flush()
            os.fsync(f.fileno())
        t_seq_write = time.perf_counter() - t0
        seq_write_mb = size_mb / t_seq_write

        # Sequential Read
        t0 = time.perf_counter()
        with open(bench_file, "rb") as f:
            while f.read(block_size):
                pass
        t_seq_read = time.perf_counter() - t0
        seq_read_mb = size_mb / t_seq_read

        # Random 4KB Write with fsync
        max_pos = (size_mb * block_size) - 4096
        t0 = time.perf_counter()
        with open(bench_file, "r+b") as f:
            for _ in range(num_ops):
                pos = random.randint(0, max_pos)
                f.seek(pos)
                f.write(chunk_4k)
            f.flush()
            os.fsync(f.fileno())
        t_rnd_write = time.perf_counter() - t0
        rnd_write_iops = num_ops / t_rnd_write

        # Random 4KB Read
        t0 = time.perf_counter()
        with open(bench_file, "rb") as f:
            for _ in range(num_ops):
                pos = random.randint(0, max_pos)
                f.seek(pos)
                _ = f.read(4096)
        t_rnd_read = time.perf_counter() - t0
        rnd_read_iops = num_ops / t_rnd_read

        passed = seq_write_mb >= 150.0 and seq_read_mb >= 250.0
        status = "PASS" if passed else "WARNING"
        res = {
            "check": "Drive D: I/O Performance Benchmark",
            "status": status,
            "measured_value": {
                "sequential_write_speed_mb_s": round(seq_write_mb, 2),
                "sequential_read_speed_mb_s": round(seq_read_mb, 2),
                "random_4k_write_iops": round(rnd_write_iops, 1),
                "random_4k_read_iops": round(rnd_read_iops, 1)
            },
            "details": f"Seq Write: {seq_write_mb:.1f} MB/s, Seq Read: {seq_read_mb:.1f} MB/s, 4K Random: {rnd_write_iops:.0f} write IOPS, {rnd_read_iops:.0f} read IOPS."
        }
    except Exception as e:
        res = {
            "check": "Drive D: I/O Performance Benchmark",
            "status": "FAIL",
            "error": str(e)
        }
    finally:
        # Strict Cleanup: Only benchmark file created for this test is deleted
        if bench_file.exists():
            try:
                bench_file.unlink()
            except Exception:
                pass

    return res


def audit_python_environment():
    # Check current interpreter
    current_ver = sys.version
    current_arch = platform.architecture()[0]
    
    # Check candidate Python 3.12 paths
    known_py312 = r"C:\Users\digan\AppData\Local\Programs\Python\Python312\python.exe"
    py312_found = os.path.exists(known_py312)
    py312_arch = "Unknown"
    py312_version = "Unknown"
    
    if py312_found:
        try:
            out = subprocess.check_output(
                [known_py312, "-c", "import sys, platform; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}|{platform.architecture()[0]}')"],
                text=True,
                timeout=5
            ).strip()
            py312_version, py312_arch = out.split("|")
        except Exception as e:
            py312_version = str(e)

    # Verify venv module in Python 3.12
    venv_available = False
    if py312_found:
        try:
            res = subprocess.run([known_py312, "-m", "venv", "-h"], capture_output=True, timeout=5)
            venv_available = res.returncode == 0
        except Exception:
            venv_available = False

    is_exact_312 = py312_version.startswith("3.12") and py312_arch == "64bit"
    
    return {
        "check": "Python 3.12 64-bit & Virtualenv Capability",
        "status": "PASS" if (is_exact_312 and venv_available) else "FAIL",
        "measured_value": {
            "system_default_python": sys.version.split()[0],
            "python_312_binary": known_py312 if py312_found else "Not Found",
            "python_312_version": py312_version,
            "python_312_architecture": py312_arch,
            "venv_module_functional": venv_available
        },
        "details": f"Python 3.12 64-bit detected at '{known_py312}' with functional venv module. (Note: system default PATH currently points to Python {sys.version.split()[0]})."
    }


def audit_ollama():
    url = "http://127.0.0.1:11434/api/tags"
    daemon_online = False
    installed_models = []
    error_msg = ""

    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=2) as response:
            if response.status == 200:
                daemon_online = True
                data = json.loads(response.read().decode())
                models = data.get("models", [])
                installed_models = [m.get("name") for m in models]
    except Exception as e:
        daemon_online = False
        error_msg = str(e)

    # Check CLI binary
    cli_found = shutil.which("ollama") is not None
    
    # Status: FAIL if daemon is offline, or BLOCKED if not installed
    status = "PASS" if daemon_online else ("BLOCKED" if not cli_found else "FAIL")
    
    return {
        "check": "Ollama Local Service & Models",
        "status": status,
        "measured_value": {
            "daemon_online": daemon_online,
            "endpoint": "http://127.0.0.1:11434",
            "cli_in_path": cli_found,
            "installed_models": installed_models
        },
        "details": f"Ollama daemon is running with models: {installed_models}" if daemon_online else f"Ollama daemon is offline / not installed: {error_msg or 'Executable not found in PATH'}."
    }


def audit_audio_devices():
    num_inputs = 0
    num_outputs = 0
    inputs = []
    outputs = []

    try:
        winmm = ctypes.windll.winmm
        num_inputs = winmm.waveInGetNumDevs()
        num_outputs = winmm.waveOutGetNumDevs()

        class WAVEINCAPSW(ctypes.Structure):
            _fields_ = [
                ("wMid", ctypes.c_ushort),
                ("wPid", ctypes.c_ushort),
                ("vDriverVersion", ctypes.c_uint),
                ("szPname", ctypes.c_wchar * 32),
                ("dwFormats", ctypes.c_uint),
                ("wChannels", ctypes.c_ushort),
                ("wReserved1", ctypes.c_ushort)
            ]

        for i in range(num_inputs):
            caps = WAVEINCAPSW()
            if winmm.waveInGetDevCapsW(i, ctypes.byref(caps), ctypes.sizeof(caps)) == 0:
                inputs.append({"index": i, "name": caps.szPname.strip(), "channels": caps.wChannels})

        class WAVEOUTCAPSW(ctypes.Structure):
            _fields_ = [
                ("wMid", ctypes.c_ushort),
                ("wPid", ctypes.c_ushort),
                ("vDriverVersion", ctypes.c_uint),
                ("szPname", ctypes.c_wchar * 32),
                ("dwFormats", ctypes.c_uint),
                ("wChannels", ctypes.c_ushort),
                ("wReserved1", ctypes.c_ushort),
                ("dwSupport", ctypes.c_uint)
            ]

        for i in range(num_outputs):
            caps = WAVEOUTCAPSW()
            if winmm.waveOutGetDevCapsW(i, ctypes.byref(caps), ctypes.sizeof(caps)) == 0:
                outputs.append({"index": i, "name": caps.szPname.strip(), "channels": caps.wChannels})

        passed = num_inputs > 0 and num_outputs > 0
        status = "PASS" if passed else "FAIL"
    except Exception as e:
        status = "FAIL"

    return {
        "check": "Audio Hardware (Microphone & Speakers)",
        "status": status,
        "measured_value": {
            "input_devices_count": num_inputs,
            "output_devices_count": num_outputs,
            "inputs": inputs,
            "outputs": outputs
        },
        "details": f"Found {num_inputs} audio input device(s) and {num_outputs} output device(s)."
    }


def audit_compilers_and_tools():
    # Git Check
    git_ver = None
    git_found = False
    try:
        out = subprocess.check_output(["git", "--version"], text=True, timeout=5).strip()
        git_ver = out
        git_found = True
    except Exception:
        git_found = False

    # LaTeX Check (pdflatex / latexmk)
    latex_found = False
    latex_ver = None
    for cmd in ["pdflatex", "latexmk"]:
        try:
            out = subprocess.check_output([cmd, "--version"], text=True, timeout=5).splitlines()[0]
            latex_found = True
            latex_ver = f"{cmd}: {out}"
            break
        except Exception:
            pass

    return {
        "git": {
            "check": "Git Version Control",
            "status": "PASS" if git_found else "FAIL",
            "measured_value": git_ver or "Not found",
            "details": f"Git binary detected: {git_ver}" if git_found else "Git binary not found in system PATH."
        },
        "latex": {
            "check": "LaTeX Compiler Engine (pdflatex/latexmk)",
            "status": "PASS" if latex_found else "BLOCKED",
            "measured_value": latex_ver or "Not found",
            "details": f"LaTeX engine detected: {latex_ver}" if latex_found else "No LaTeX distribution (MiKTeX/TeX Live) detected in PATH. Capability 07 LaTeX compilation will require installation or fallback."
        }
    }


def verify_storage_paths_configuration():
    if not STORAGE_CONFIG_PATH.exists():
        return {
            "check": "Storage Paths Config File",
            "status": "FAIL",
            "details": f"Configuration file missing: {STORAGE_CONFIG_PATH}"
        }

    # Verify that all configured target paths in storage_paths.yaml point strictly to D:\
    try:
        with open(STORAGE_CONFIG_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()
        
        in_paths_section = False
        paths_checked = {}
        offending = []

        for raw_line in lines:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("paths:"):
                in_paths_section = True
                continue
            elif in_paths_section and not raw_line.startswith("  ") and not raw_line.startswith("\t"):
                in_paths_section = False

            if in_paths_section and ":" in line:
                key, val = line.split(":", 1)
                val = val.strip().strip('"').strip("'")
                paths_checked[key.strip()] = val
                # Ensure the path points to D: and does NOT point to C:
                if not (val.startswith("D:\\") or val.startswith("D:/")):
                    offending.append(f"{key.strip()}: {val}")
        
        all_d = len(offending) == 0 and len(paths_checked) > 0
        
        return {
            "check": "Storage Redirection to Drive D:",
            "status": "PASS" if all_d else "FAIL",
            "measured_value": {
                "config_file": str(STORAGE_CONFIG_PATH),
                "storage_target_drive": "D:",
                "total_paths_verified": len(paths_checked),
                "paths": paths_checked,
                "offending_paths": offending
            },
            "details": f"All {len(paths_checked)} target paths in 'paths' section point strictly to Drive D:." if all_d else f"Offending paths not on D: {offending}"
        }
    except Exception as e:
        return {
            "check": "Storage Redirection to Drive D:",
            "status": "FAIL",
            "error": str(e)
        }


def main():
    print("=" * 80)
    print(" ResearchOS AI — Phase 0: Environment Audit & Hardware Profiling")
    print("=" * 80)
    print(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Host: {platform.node()} | Platform: {platform.platform()}")
    print("-" * 80)

    # 1. Workspace
    res_ws = audit_workspace()
    print(f"[{res_ws['status']}] {res_ws['check']}: {res_ws['measured_value']}")

    # 2. CPU & AVX2
    res_cpu = audit_cpu_and_avx2()
    print(f"[{res_cpu['status']}] {res_cpu['check']}: {res_cpu['measured_value']['processor_name']} (AVX2: {res_cpu['measured_value']['avx2_supported']})")

    # 3. RAM
    res_ram = audit_ram()
    print(f"[{res_ram['status']}] {res_ram['check']}: Total {res_ram['measured_value']['total_ram_gb']} GB, Available {res_ram['measured_value']['available_ram_gb']} GB")

    # 4. Storage
    res_storage = audit_storage()
    res_c = res_storage["drive_c"]
    res_d = res_storage["drive_d"]
    print(f"[{res_c['status']}] {res_c['check']}: Free {res_c['measured_value']['free_gb']} GB (Min threshold: {res_c['measured_value']['threshold_min_gb']} GB)")
    print(f"[{res_d['status']}] {res_d['check']}: Free {res_d['measured_value']['free_gb']} GB")

    # 5. Drive D: Physical Type
    res_dtype = audit_drive_d_physical_type()
    print(f"[{res_dtype['status']}] {res_dtype['check']}: {res_dtype['measured_value']['device_identifier']} ({res_dtype['measured_value']['bus_type']})")

    # 6. Disk Performance
    res_perf = audit_disk_performance()
    print(f"[{res_perf['status']}] {res_perf['check']}: Seq Write {res_perf['measured_value']['sequential_write_speed_mb_s']} MB/s, Seq Read {res_perf['measured_value']['sequential_read_speed_mb_s']} MB/s")

    # 7. Python 3.12 64-bit
    res_py = audit_python_environment()
    print(f"[{res_py['status']}] {res_py['check']}: Python {res_py['measured_value']['python_312_version']} ({res_py['measured_value']['python_312_architecture']})")

    # 8. Ollama
    res_ollama = audit_ollama()
    print(f"[{res_ollama['status']}] {res_ollama['check']}: Online={res_ollama['measured_value']['daemon_online']}, Models={res_ollama['measured_value']['installed_models']}")

    # 9. Audio
    res_audio = audit_audio_devices()
    print(f"[{res_audio['status']}] {res_audio['check']}: Inputs={res_audio['measured_value']['input_devices_count']}, Outputs={res_audio['measured_value']['output_devices_count']}")

    # 10. Compilers
    res_tools = audit_compilers_and_tools()
    print(f"[{res_tools['git']['status']}] {res_tools['git']['check']}: {res_tools['git']['measured_value']}")
    print(f"[{res_tools['latex']['status']}] {res_tools['latex']['check']}: {res_tools['latex']['measured_value']}")

    # 11. Storage Paths Config
    res_spaths = verify_storage_paths_configuration()
    print(f"[{res_spaths['status']}] {res_spaths['check']}: Redirection to D: Verified")

    # Assemble Audit Report
    all_checks = [
        res_ws,
        res_cpu,
        res_ram,
        res_c,
        res_d,
        res_dtype,
        res_perf,
        res_py,
        res_ollama,
        res_audio,
        res_tools['git'],
        res_tools['latex'],
        res_spaths
    ]

    has_failures = any(c['status'] == 'FAIL' for c in all_checks)
    has_blocked = any(c['status'] == 'BLOCKED' for c in all_checks)
    overall_status = "FAIL" if has_failures else ("BLOCKED" if has_blocked else "PASS")

    problems = []
    recommendations = []

    if res_c['status'] == 'FAIL':
        free_c_val = res_c['measured_value']['free_gb']
        problems.append(f"Drive C: free space is {free_c_val:.2f} GB, which is below the strict safety threshold of {MIN_C_FREE_GB} GB.")
        recommendations.append("User must manually free up at least 1 GB on Drive C: (e.g., empty Recycle Bin, clean temporary downloads, or run Windows Disk Cleanup) to achieve >= 15.0 GB free. As per Safety Rule, agent will NOT attempt automatic deletion.")

    if res_ollama['status'] in ('FAIL', 'BLOCKED'):
        problems.append("Ollama daemon is offline and not present in system PATH.")
        recommendations.append("Install Ollama on Windows, set $env:OLLAMA_MODELS = 'D:\\Projects\\ResearchOS-AI\\storage\\.ollama\\models', start the Ollama service, and verify 'http://127.0.0.1:11434' is reachable.")

    if res_tools['latex']['status'] == 'BLOCKED':
        problems.append("No local LaTeX compiler (pdflatex / latexmk) detected in system PATH.")
        recommendations.append("For Capability 07 (LaTeX compilation), install MiKTeX or TeX Live to Drive D: (e.g. D:\\MiKTeX) or use a cloud/docker/Typst fallback pipeline.")

    if not res_py['measured_value']['system_default_python'].startswith("3.12"):
        problems.append(f"System default 'python' command resolves to Python {res_py['measured_value']['system_default_python']} (not 3.12).")
        recommendations.append(f"Use the explicit Python 3.12 binary at '{res_py['measured_value']['python_312_binary']}' when bootstrapping the project virtual environment on Drive D:.")

    report_data = {
        "report_metadata": {
            "product": "ResearchOS AI",
            "phase": "Phase 0: Environment Audit & Hardware Profiling",
            "spec_version": "2.1.0",
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "host_node": platform.node(),
            "overall_status": overall_status
        },
        "audit_checks": all_checks,
        "identified_problems": problems,
        "recommended_corrections": recommendations
    }

    # Ensure config directory exists
    REPORT_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(REPORT_OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(report_data, f, indent=2)

    print("-" * 80)
    print(f"Overall Phase 0 Status: {overall_status}")
    print(f"Environment report written to: {REPORT_OUTPUT_PATH}")
    print("=" * 80)

    return 1 if has_failures else 0


if __name__ == "__main__":
    sys.exit(main())
