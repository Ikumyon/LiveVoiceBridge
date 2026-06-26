from __future__ import annotations

from pathlib import Path

import numpy as np


DEVICE_ID = "openvino_gpu"
DISPLAY_NAME = "OpenVINO GPU"
OPENVINO_DEVICE = "GPU"


class OpenVinoSession:
    def __init__(self, model_path: Path, device: str):
        import openvino as ov

        core = ov.Core()
        model = core.read_model(str(model_path))
        self.compiled_model = core.compile_model(model, device)
        self.outputs = list(self.compiled_model.outputs)

    def run(self, output_names, input_feed):
        result = self.compiled_model(input_feed)
        return [np.asarray(result[output]) for output in self.outputs]


def is_available() -> bool:
    try:
        import openvino as ov

        return OPENVINO_DEVICE in ov.Core().available_devices
    except Exception:
        return False


def create_tts(model_dir: Path):
    import supertonic.core as supertonic_core
    import supertonic.loader as supertonic_loader
    from supertonic import TTS

    if not supertonic_loader.has_all_onnx_modules(model_dir):
        raise FileNotFoundError(f"SUPERTONIC 3 model files are missing: {model_dir}")

    sessions = tuple(
        OpenVinoSession(model_dir / relative_path, OPENVINO_DEVICE)
        for relative_path in supertonic_loader.get_all_onnx_module_relative_paths()
    )

    original_loader = supertonic_loader.load_onnx_modules
    original_session_type = supertonic_core.ort.InferenceSession
    try:
        supertonic_loader.load_onnx_modules = lambda *args, **kwargs: sessions
        supertonic_core.ort.InferenceSession = (
            original_session_type,
            OpenVinoSession,
        )
        return TTS(
            model="supertonic-3",
            model_dir=model_dir,
            auto_download=False,
        )
    finally:
        supertonic_loader.load_onnx_modules = original_loader
        supertonic_core.ort.InferenceSession = original_session_type
