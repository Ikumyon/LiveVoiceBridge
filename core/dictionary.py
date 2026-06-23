import csv
import json
from pathlib import Path

from core.app_config import DICT_DIR, DEFAULT_WORD_LIST


def ensure_default_dictionary() -> None:
    """辞書ディレクトリを用意し、辞書ファイルがなければデフォルト辞書を作る。"""
    DICT_DIR.mkdir(parents=True, exist_ok=True)
    json_files = list(DICT_DIR.glob("*.json"))
    if json_files:
        return

    default_file = DICT_DIR / "デフォルト.json"
    with open(default_file, "w", encoding="utf-8") as f:
        json.dump(DEFAULT_WORD_LIST, f, ensure_ascii=False, indent=2)


def load_all_word_dict_data() -> dict[str, list[dict]]:
    """すべての辞書グループファイル（.json）を読み込んで辞書として返す。空の場合はデフォルトデータを返す。"""
    data = {}
    try:
        if DICT_DIR.exists():
            for json_file in DICT_DIR.glob("*.json"):
                group_name = json_file.stem
                try:
                    with open(json_file, "r", encoding="utf-8") as f:
                        data[group_name] = json.load(f)
                except Exception as e:
                    print(f"辞書ファイル {json_file.name} のロード失敗: {e}")
    except Exception as e:
        print(f"辞書ディレクトリ走査失敗: {e}")
    
    if not data:
        data["デフォルト"] = DEFAULT_WORD_LIST.copy()
    return data


def merge_word_dict_data(word_dict_data: dict[str, list[dict]]) -> list[dict]:
    """複数グループの辞書データを読み上げ用の単語リストへ統合する。"""
    merged_list = []
    for group_words in word_dict_data.values():
        merged_list.extend(group_words)
    return merged_list


def load_merged_word_list() -> list[dict]:
    """全辞書ファイルを読み込み、読み上げ用の単語リストとして返す。"""
    return merge_word_dict_data(load_all_word_dict_data())


def restore_word_dict_data(word_dict_data: dict[str, list[dict]]) -> None:
    """辞書ディレクトリの内容を指定データで置き換える。"""
    DICT_DIR.mkdir(parents=True, exist_ok=True)
    for json_file in DICT_DIR.glob("*.json"):
        json_file.unlink()
    save_word_dict_data(word_dict_data)


def save_word_dict_data(word_dict: dict[str, list[dict]]) -> None:
    """与えられたメモリ上の辞書データを、個別のJSONファイルに書き出す。メモリ上に存在しない古い辞書ファイルは削除する。"""
    try:
        DICT_DIR.mkdir(parents=True, exist_ok=True)
        # 現在のメモリ上のグループを個別のJSONファイルに書き出す
        for group_name, words in word_dict.items():
            dest_file = DICT_DIR / f"{group_name}.json"
            with open(dest_file, "w", encoding="utf-8") as f:
                json.dump(words, f, ensure_ascii=False, indent=2)
        
        # メモリ上にない（＝削除された）辞書ファイルを物理削除
        for json_file in DICT_DIR.glob("*.json"):
            if json_file.stem not in word_dict:
                try:
                    json_file.unlink()
                except Exception:
                    pass
    except Exception as exc:
        raise RuntimeError(f"辞書ファイルの保存に失敗しました: {exc}")


def add_word_to_group(group_name: str, word: str, reading: str, pos: str = "名詞", comment: str = "") -> list[dict]:
    """指定された辞書グループファイルに単語を追加（重複は排除）し、更新されたリストを返す。"""
    DICT_DIR.mkdir(parents=True, exist_ok=True)
    dict_file = DICT_DIR / f"{group_name}.json"
    
    if dict_file.exists():
        with open(dict_file, "r", encoding="utf-8") as f:
            words = json.load(f)
    else:
        words = []
        
    # 重複防止：既に同じ単語があれば削除
    words = [w for w in words if w.get("word") != word]
    words.append({
        "word": word,
        "reading": reading,
        "pos": pos,
        "comment": comment
    })
    
    with open(dict_file, "w", encoding="utf-8") as f:
        json.dump(words, f, ensure_ascii=False, indent=2)
    return words


def delete_word_from_group(group_name: str, word: str) -> list[dict] | None:
    """指定された辞書グループファイルから単語を削除し、更新されたリストを返す。見つからない場合は None を返す。"""
    DICT_DIR.mkdir(parents=True, exist_ok=True)
    dict_file = DICT_DIR / f"{group_name}.json"
    
    if not dict_file.exists():
        return None
        
    with open(dict_file, "r", encoding="utf-8") as f:
        words = json.load(f)
        
    new_words = [w for w in words if w.get("word") != word]
    if len(new_words) == len(words):
        return None
        
    with open(dict_file, "w", encoding="utf-8") as f:
        json.dump(new_words, f, ensure_ascii=False, indent=2)
    return new_words


def load_import_word_list(file_path: str) -> list[dict]:
    """JSON / CSV / テキスト辞書から単語リストを読み込む。"""
    path = Path(file_path)
    suffix = path.suffix.lower()

    if suffix == ".json":
        return _load_json_word_list(path)
    if suffix == ".csv":
        return _load_csv_word_list(path)
    if suffix == ".txt":
        return _load_text_word_list(path)
    return []


def _load_json_word_list(path: Path) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    words = []
    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            words.append({
                "reading": item.get("reading", ""),
                "word": item.get("word", ""),
                "pos": item.get("pos", "名詞"),
                "comment": item.get("comment", ""),
            })
    elif isinstance(data, dict):
        for word, reading in data.items():
            words.append({
                "reading": str(reading),
                "word": str(word),
                "pos": "名詞",
                "comment": "",
            })
    return words


def _load_csv_word_list(path: Path) -> list[dict]:
    words = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        for row_data in reader:
            if not row_data:
                continue
            words.append({
                "reading": row_data[0] if len(row_data) > 0 else "",
                "word": row_data[1] if len(row_data) > 1 else "",
                "pos": row_data[2] if len(row_data) > 2 else "名詞",
                "comment": row_data[3] if len(row_data) > 3 else "",
            })
    return words


def _load_text_word_list(path: Path) -> list[dict]:
    words = []
    encoding = _detect_text_dictionary_encoding(path)
    with open(path, "r", encoding=encoding, errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("!") or line.startswith("#"):
                continue

            row_data = line.split("\t")
            if len(row_data) < 2:
                continue

            words.append({
                "reading": row_data[0].strip(),
                "word": row_data[1].strip(),
                "pos": row_data[2].strip() if len(row_data) > 2 else "名詞",
                "comment": row_data[3].strip() if len(row_data) > 3 else "",
            })
    return words


def _detect_text_dictionary_encoding(path: Path) -> str:
    encoding = "shift_jis"
    for candidate in ["shift_jis", "utf-16", "utf-8"]:
        try:
            with open(path, "r", encoding=candidate) as f:
                f.readline()
            encoding = candidate
            break
        except Exception:
            continue
    return encoding
