import json
from core.workers import DICT_DIR, DEFAULT_WORD_LIST

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
