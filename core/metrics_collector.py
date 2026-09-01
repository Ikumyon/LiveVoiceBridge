import time
import os
import sys
import psutil
import warnings

# NVIDIA NVML
with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    try:
        import pynvml
        pynvml.nvmlInit()
        HAS_NVML = True
    except Exception:
        HAS_NVML = False

class MetricsCollector:
    """CPU, 各GPU/VRAM, NPU, RAM, Network メトリクス収集クラス"""

    def __init__(self):
        self.last_time = time.time()
        self.last_net = psutil.net_io_counters()
        self.has_npu = False
        self._init_npu_check()

    def _init_npu_check(self):
        """NPUの検出試行 (Windows PnP / Performance Counters等)"""
        if sys.platform == 'win32':
            import subprocess
            import json
            try:
                ps_pnp = "Get-CimInstance Win32_PnPEntity | Where-Object { $_.Name -like '*AI Boost*' -or $_.Name -like '*Intel*NPU*' -or $_.Name -like '*AMD*IPU*' -or $_.Name -like '*Hexagon*' -or $_.Name -like '*Neural Processing Unit*' } | Select-Object Name | ConvertTo-Json"
                res_pnp = subprocess.run(["powershell", "-NoProfile", "-Command", ps_pnp], capture_output=True, text=True, timeout=2)
                if res_pnp.returncode == 0 and res_pnp.stdout.strip():
                    data = json.loads(res_pnp.stdout)
                    if isinstance(data, dict):
                        data = [data]
                    if data:
                        self.has_npu = True
                        self.npu_name = data[0].get("Name", "NPU")
            except Exception:
                pass

    def _collect_npu_percent(self) -> float:
        """NPUの利用率 (%) 取得"""
        if not self.has_npu or sys.platform != 'win32':
            return 0.0

        import subprocess
        import json
        try:
            # engtype_NPU または NPU 関連エンジンの利用率
            ps_perf = "Get-CimInstance Win32_PerfFormattedData_GPUPerformanceCounters_GPUEngine | Where-Object { $_.Name -like '*engtype_NPU*' -or $_.Name -like '*engtype_Compute*' } | Select-Object UtilizationPercentage | ConvertTo-Json"
            res_perf = subprocess.run(["powershell", "-NoProfile", "-Command", ps_perf], capture_output=True, text=True, timeout=2)
            if res_perf.returncode == 0 and res_perf.stdout.strip():
                pdata = json.loads(res_perf.stdout)
                if isinstance(pdata, dict):
                    pdata = [pdata]
                utils = [float(item.get("UtilizationPercentage", 0) or 0) for item in pdata]
                if utils:
                    return min(100.0, round(max(utils), 1))
        except Exception:
            pass
        return 0.0

    def _collect_gpus(self) -> list[dict]:
        gpus = []

        # 1. NVIDIA NVML経由
        if HAS_NVML:
            try:
                device_count = pynvml.nvmlDeviceGetCount()
                for i in range(device_count):
                    handle = pynvml.nvmlDeviceGetHandleByIndex(i)
                    name = pynvml.nvmlDeviceGetName(handle)
                    if isinstance(name, bytes):
                        name = name.decode('utf-8', errors='ignore')
                    
                    util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                    gpu_percent = float(util.gpu)

                    mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
                    vram_used_gb = mem_info.used / (1024 ** 3)
                    vram_total_gb = mem_info.total / (1024 ** 3)
                    vram_percent = (vram_used_gb / vram_total_gb * 100.0) if vram_total_gb > 0 else 0.0

                    gpus.append({
                        "id": f"nvidia_{i}",
                        "name": f"GPU {i} ({name})",
                        "gpu_percent": gpu_percent,
                        "vram_used_gb": vram_used_gb,
                        "vram_total_gb": vram_total_gb,
                        "vram_percent": vram_percent,
                        "has_vram": vram_total_gb > 0
                    })
            except Exception:
                pass

        # 他のGPU (Intel iGPU / AMD Radeon 等) があり NVML で取れない場合、あるいは汎用Windows GPUフォールバック
        if sys.platform == 'win32':
            try:
                # Windows標準のGPU情報およびパフォーマンスカウンターから取得
                win_gpus = self._collect_win32_gpus()
                if win_gpus:
                    # nvmlと重複しないようIDチェック、またはNVMLで取得できなかった場合に採用
                    existing_names = {g.get("name", "") for g in gpus}
                    for wg in win_gpus:
                        if wg["name"] not in existing_names:
                            gpus.append(wg)
            except Exception:
                pass

        return gpus

    def _collect_win32_gpus(self) -> list[dict]:
        """Windows標準機能 (Win32_VideoController & PerfCounter) を用いた汎用GPUメトリクス取得"""
        import subprocess
        import json

        now = time.time()
        # GPUメタ情報（名前、メモリ容量）は30秒毎にキャッシュ更新
        if not hasattr(self, "_win32_gpu_meta_cache") or (now - getattr(self, "_win32_gpu_meta_last", 0)) > 30:
            self._win32_gpu_meta_cache = []
            self._win32_gpu_meta_last = now
            try:
                ps_gpu_cmd = "Get-CimInstance Win32_VideoController | Select-Object Name, AdapterRAM | ConvertTo-Json"
                res = subprocess.run(["powershell", "-NoProfile", "-Command", ps_gpu_cmd], capture_output=True, text=True, timeout=2)
                if res.returncode == 0 and res.stdout.strip():
                    data = json.loads(res.stdout)
                    if isinstance(data, dict):
                        data = [data]
                    for idx, d in enumerate(data):
                        name = d.get("Name", f"GPU {idx}")
                        vram_bytes = d.get("AdapterRAM", 0) or 0
                        self._win32_gpu_meta_cache.append({
                            "id": f"win_gpu_{idx}",
                            "name": name,
                            "vram_bytes": vram_bytes
                        })
            except Exception:
                pass

        if not getattr(self, "_win32_gpu_meta_cache", []):
            return []

        # 1. GPU利用率 (UtilizationPercentage)
        by_luid_util = {}
        try:
            ps_perf_cmd = "Get-CimInstance Win32_PerfFormattedData_GPUPerformanceCounters_GPUEngine | Select-Object Name, UtilizationPercentage | ConvertTo-Json"
            res_perf = subprocess.run(["powershell", "-NoProfile", "-Command", ps_perf_cmd], capture_output=True, text=True, timeout=2)
            if res_perf.returncode == 0 and res_perf.stdout.strip():
                pdata = json.loads(res_perf.stdout)
                if isinstance(pdata, dict):
                    pdata = [pdata]
                for item in pdata:
                    name = item.get("Name", "")
                    util = float(item.get("UtilizationPercentage", 0) or 0)
                    if "luid_" in name:
                        parts = name.split("luid_")
                        luid = parts[1].split("_")[0] + "_" + parts[1].split("_")[1]
                        by_luid_util[luid] = by_luid_util.get(luid, 0.0) + util
        except Exception:
            pass

        # 2. VRAM使用量 (DedicatedUsage / SharedUsage)
        by_luid_mem = {}
        try:
            ps_mem_cmd = "Get-CimInstance Win32_PerfFormattedData_GPUPerformanceCounters_GPUAdapterMemory | Select-Object Name, DedicatedUsage, SharedUsage | ConvertTo-Json"
            res_mem = subprocess.run(["powershell", "-NoProfile", "-Command", ps_mem_cmd], capture_output=True, text=True, timeout=2)
            if res_mem.returncode == 0 and res_mem.stdout.strip():
                mdata = json.loads(res_mem.stdout)
                if isinstance(mdata, dict):
                    mdata = [mdata]
                for item in mdata:
                    name = item.get("Name", "")
                    ded = float(item.get("DedicatedUsage", 0) or 0)
                    shared = float(item.get("SharedUsage", 0) or 0)
                    if "luid_" in name:
                        parts = name.split("luid_")
                        luid = parts[1].split("_")[0] + "_" + parts[1].split("_")[1]
                        by_luid_mem[luid] = by_luid_mem.get(luid, 0.0) + (ded + shared)
        except Exception:
            pass

        luid_utils = list(by_luid_util.values())
        luid_mems = list(by_luid_mem.values())

        win_gpus = []
        for idx, meta in enumerate(self._win32_gpu_meta_cache):
            # GPU利用率
            gpu_percent = min(100.0, luid_utils[idx]) if idx < len(luid_utils) else 0.0
            if not luid_utils and by_luid_util:
                gpu_percent = min(100.0, max(by_luid_util.values()))

            # VRAM使用量 (GB)
            vram_used_bytes = luid_mems[idx] if idx < len(luid_mems) else (max(by_luid_mem.values()) if by_luid_mem else 0.0)
            vram_used_gb = vram_used_bytes / (1024 ** 3)

            # VRAM総量
            vram_total_gb = meta["vram_bytes"] / (1024 ** 3)
            # 総量が取得できていないか極端に小さい場合 (内蔵GPU共有メモリ等)、システムRAMから推定またはデフォルト値
            if vram_total_gb <= 0.1:
                mem = psutil.virtual_memory()
                vram_total_gb = (mem.total / (1024 ** 3)) * 0.5  # システムRAMの半数をVRAM枠として扱う
            
            vram_percent = min(100.0, (vram_used_gb / vram_total_gb * 100.0)) if vram_total_gb > 0 else 0.0

            win_gpus.append({
                "id": meta["id"],
                "name": f"GPU {idx} ({meta['name']})",
                "gpu_percent": round(gpu_percent, 1),
                "vram_used_gb": round(vram_used_gb, 2),
                "vram_total_gb": round(vram_total_gb, 1),
                "vram_percent": round(vram_percent, 1),
                "has_vram": True
            })

        return win_gpus

    def collect(self) -> dict:
        now = time.time()
        dt = max(now - self.last_time, 0.001)
        self.last_time = now

        # CPU
        cpu_percent = psutil.cpu_percent(interval=None)

        # RAM
        mem = psutil.virtual_memory()
        ram_percent = mem.percent
        ram_used_gb = mem.used / (1024 ** 3)
        ram_total_gb = mem.total / (1024 ** 3)

        # Network
        net = psutil.net_io_counters()
        bytes_sent_diff = max(0, net.bytes_sent - self.last_net.bytes_sent)
        bytes_recv_diff = max(0, net.bytes_recv - self.last_net.bytes_recv)
        self.last_net = net

        net_send_speed_kb = (bytes_sent_diff / dt) / 1024.0
        net_recv_speed_kb = (bytes_recv_diff / dt) / 1024.0
        net_total_speed_kb = net_send_speed_kb + net_recv_speed_kb

        # GPUs
        gpus = self._collect_gpus()

        # NPU
        npu_percent = self._collect_npu_percent()
        has_npu = self.has_npu

        return {
            "cpu_percent": cpu_percent,
            "ram_percent": ram_percent,
            "ram_used_gb": ram_used_gb,
            "ram_total_gb": ram_total_gb,
            "net_send_speed_kb": net_send_speed_kb,
            "net_recv_speed_kb": net_recv_speed_kb,
            "net_total_speed_kb": net_total_speed_kb,
            "gpus": gpus,
            "has_npu": has_npu,
            "npu_percent": npu_percent,
        }


try:
    from PySide6.QtCore import QThread, Signal

    class MetricsWorker(QThread):
        """バックグラウンドでシステムメトリクスを並列収集するワーカー"""
        metrics_collected = Signal(dict)

        def __init__(self, interval_sec: float = 1.0, parent=None):
            super().__init__(parent)
            self.interval_sec = interval_sec
            self.collector = MetricsCollector()
            self.running = True

        def run(self):
            while self.running:
                try:
                    data = self.collector.collect()
                    self.metrics_collected.emit(data)
                except Exception:
                    pass
                self.msleep(int(self.interval_sec * 1000))

        def stop(self):
            self.running = False
            self.wait()

except ImportError:
    pass

