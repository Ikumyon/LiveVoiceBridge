from __future__ import annotations

from pathlib import Path

import numpy as np


DEVICE_ID = "openvino_npu_hybrid"
DISPLAY_NAME = "OpenVINO NPU ハイブリッド"


class DynamicNpuSession:
    def __init__(self, model_path: Path):
        import openvino as ov

        self.model_path = model_path
        self.core = ov.Core()
        self.compiled_models = {}

    def run(self, output_names, input_feed):
        shape_key = tuple(
            (name, tuple(value.shape))
            for name, value in sorted(input_feed.items())
        )
        if shape_key not in self.compiled_models:
            model = self.core.read_model(str(self.model_path))
            model.reshape({
                name: list(value.shape)
                for name, value in input_feed.items()
            })
            compiled_model = self.core.compile_model(model, "NPU")
            self.compiled_models[shape_key] = (
                compiled_model,
                list(compiled_model.outputs),
            )

        compiled_model, outputs = self.compiled_models[shape_key]
        result = compiled_model(input_feed)
        return [np.asarray(result[output]) for output in outputs]


class GpuSession:
    def __init__(self, model_path: Path):
        import openvino as ov

        core = ov.Core()
        model = core.read_model(str(model_path))
        self.compiled_model = core.compile_model(model, "GPU")
        self.outputs = list(self.compiled_model.outputs)

    def run(self, output_names, input_feed):
        result = self.compiled_model(input_feed)
        return [np.asarray(result[output]) for output in self.outputs]


def is_available() -> bool:
    try:
        import openvino as ov

        devices = set(ov.Core().available_devices)
        return {"NPU", "GPU"}.issubset(devices)
    except Exception:
        return False


def create_tts(model_dir: Path):
    import supertonic.core as supertonic_core
    import supertonic.loader as supertonic_loader
    from supertonic import TTS

    if not supertonic_loader.has_all_onnx_modules(model_dir):
        supertonic_loader.download_model(model_dir, "supertonic-3")

    model_paths = [
        model_dir / relative_path
        for relative_path in supertonic_loader.get_all_onnx_module_relative_paths()
    ]
    sessions = (
        DynamicNpuSession(model_paths[0]),
        DynamicNpuSession(model_paths[1]),
        GpuSession(model_paths[2]),
        DynamicNpuSession(model_paths[3]),
    )

    original_loader = supertonic_loader.load_onnx_modules
    original_session_type = supertonic_core.ort.InferenceSession
    try:
        supertonic_loader.load_onnx_modules = lambda *args, **kwargs: sessions
        supertonic_core.ort.InferenceSession = (
            original_session_type,
            DynamicNpuSession,
            GpuSession,
        )
        return TTS(
            model="supertonic-3",
            model_dir=model_dir,
            auto_download=False,
        )
    finally:
        supertonic_loader.load_onnx_modules = original_loader
        supertonic_core.ort.InferenceSession = original_session_type
