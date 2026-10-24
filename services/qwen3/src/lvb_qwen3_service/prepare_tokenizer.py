"""Export and verify the text tokenizer required by OpenVINO GenAI."""

import argparse
from pathlib import Path


def main() -> None:
    import openvino as ov
    from openvino_tokenizers import convert_tokenizer
    from transformers import AutoTokenizer

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", type=Path)
    args = parser.parse_args()
    tokenizer = AutoTokenizer.from_pretrained(str(args.model), local_files_only=True)
    encoder, decoder = convert_tokenizer(tokenizer, with_detokenizer=True)
    compiled = ov.Core().compile_model(encoder, "CPU")
    for text in ("こんにちは。", "コメントありがとうございます！", "Hello, 123。"):
        actual = compiled({0: [text]})["input_ids"][0].tolist()
        expected = tokenizer.encode(text)
        if actual != expected:
            raise RuntimeError(f"Tokenizer verification failed: {text!r}")
    ov.save_model(encoder, args.model / "openvino_tokenizer.xml")
    ov.save_model(decoder, args.model / "openvino_detokenizer.xml")
    print("Tokenizer exported and verified.")


if __name__ == "__main__":
    main()
