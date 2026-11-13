"""Fetch one public Apple preview for local diagnosis only; not a release asset."""

import hashlib
import json
import urllib.parse
import urllib.request
from pathlib import Path


def main():
    root = Path(__file__).resolve().parent / "outputs/song-diagnostics"
    root.mkdir(exist_ok=True)
    lookup = "https://itunes.apple.com/lookup?id=1443274396&country=hk"
    with urllib.request.urlopen(lookup, timeout=30) as response:
        data = json.load(response)
    item = next(row for row in data["results"] if row.get("trackId") == 1443274396)
    assert item["trackName"] == "一生不變" and item["artistName"] == "李克勤"
    url = item["previewUrl"]
    assert urllib.parse.urlparse(url).hostname == "audio-ssl.itunes.apple.com"
    path = root / "apple-preview.m4a"
    with urllib.request.urlopen(url, timeout=30) as response:
        content = response.read(8 * 1024 * 1024 + 1)
    if len(content) > 8 * 1024 * 1024:
        raise RuntimeError("Preview size limit exceeded")
    path.write_bytes(content)
    # Imports after the public-source download so the decoding process does not
    # need any third-party network behavior or external media executables.
    import av
    import numpy as np
    import soundfile as sf

    chunks = []
    resampler = av.AudioResampler(format="fltp", layout="mono", rate=16000)
    with av.open(str(path)) as container:
        for frame in container.decode(audio=0):
            for converted in resampler.resample(frame):
                chunks.append(converted.to_ndarray().reshape(-1))
            if sum(len(x) for x in chunks) > 100 * 16000:
                raise RuntimeError("Preview duration limit exceeded")
        for converted in resampler.resample(None):
            chunks.append(converted.to_ndarray().reshape(-1))
    audio = np.concatenate(chunks).astype(np.float32)
    assert 5 < len(audio) / 16000 <= 100 and np.isfinite(audio).all()
    sf.write(str(root / "apple-preview.wav"), audio, 16000, subtype="PCM_16")
    manifest = dict(
        track_id=item["trackId"],
        artist=item["artistName"],
        album=item["collectionName"],
        title=item["trackName"],
        lookup=lookup,
        page=item["trackViewUrl"],
        preview_url=url,
        preview_sha256=hashlib.sha256(content).hexdigest(),
        audio_seconds=len(audio) / 16000,
        intended_use="Local diagnosis of public preview only; do not bundle or redistribute",
        same_version_as_user="unverified",
    )
    (root / "sample-source.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "prepared": True,
                "seconds": len(audio) / 16000,
                "source": "Apple public preview",
                "user_version_match": "unverified",
            }
        )
    )


if __name__ == "__main__":
    main()
