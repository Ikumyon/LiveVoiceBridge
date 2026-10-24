import io

import requests


def load_avatar(url: str) -> bytes:
    with requests.get(url, timeout=(2, 3), stream=True) as response:
        response.raise_for_status()
        with io.BytesIO() as data:
            for chunk in response.iter_content(16384):
                if data.tell() + len(chunk) > 512 * 1024:
                    raise ValueError("アバター画像が512KiBの取得上限を超えました。")
                data.write(chunk)
            return data.getvalue()
