from __future__ import annotations

from pathlib import Path


DEVICE_ID = "directml_gpu"
DISPLAY_NAME = "DirectML GPU"
PROVIDER = "DmlExecutionProvider"


def is_available() -> bool:
    try:
        import onnxruntime as ort

        return PROVIDER in ort.get_available_providers()
    except Exception:
        return False


def _create_session(model_path: Path):
    import onnxruntime as ort

    options = ort.SessionOptions()
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    options.enable_mem_pattern = False

    return ort.InferenceSession(
        str(model_path),
        sess_options=options,
        providers=[
            (PROVIDER, {"device_id": 0}),
            "CPUExecutionProvider",
        ],
    )


def create_tts(model_dir: Path):
    import supertonic.loader as supertonic_loader
    from supertonic import TTS

    if not supertonic_loader.has_all_onnx_modules(model_dir):
        supertonic_loader.download_model(model_dir, "supertonic-3")

    sessions = tuple(
        _create_session(model_dir / relative_path)
        for relative_path in supertonic_loader.get_all_onnx_module_relative_paths()
    )

    original_loader = supertonic_loader.load_onnx_modules
    try:
        supertonic_loader.load_onnx_modules = lambda *args, **kwargs: sessions
        return TTS(
            model="supertonic-3",
            model_dir=model_dir,
            auto_download=False,
        )
    finally:
        supertonic_loader.load_onnx_modules = original_loader
