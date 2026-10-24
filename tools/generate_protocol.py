"""Print an apply_patch diff for build-time protobuf regeneration.

Run from the repository root. Review and apply the printed diff with apply_patch.
The application itself never generates Python source or alters sys.path.
"""

import difflib
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> None:
    package = Path(__file__).resolve().parents[1] / "src/livevoicebridge/integrations/youtube/generated"
    print("*** Begin Patch")
    with tempfile.TemporaryDirectory() as directory:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "grpc_tools.protoc",
                f"-I{package}",
                f"--python_out={directory}",
                f"--grpc_python_out={directory}",
                str(package / "stream_list.proto"),
            ],
            check=True,
        )
        for filename in ("stream_list_pb2.py", "stream_list_pb2_grpc.py"):
            source = package / filename
            generated = (Path(directory) / filename).read_text(encoding="utf-8")
            generated = generated.replace("import stream_list_pb2 as", "from . import stream_list_pb2 as")
            previous = source.read_text(encoding="utf-8") if source.exists() else ""
            if previous == generated:
                continue
            if not source.exists():
                print(f"*** Add File: {source.as_posix()}")
                for line in generated.splitlines():
                    print("+" + line)
                continue
            print(f"*** Update File: {source.as_posix()}")
            for line in list(difflib.unified_diff(previous.splitlines(), generated.splitlines()))[2:]:
                print("@@" if line.startswith("@@") else line)
    print("*** End Patch")


if __name__ == "__main__":
    main()
