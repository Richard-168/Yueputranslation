"""One offline, fail-closed model redistribution check for both packaging tools."""

import argparse
import hashlib
import json
import sys
from pathlib import Path

REGISTRY_PATH = Path(__file__).resolve().parents[1] / "licenses/models/registry.json"


def verify_artifacts(model, directory, *, files=None):
    directory = Path(directory).resolve()
    for name, expected in model.get("artifact_sha256", {}).items():
        path = Path(files[name]) if files is not None else directory / name
        if not path.resolve().is_relative_to(directory) or path.is_symlink() or not path.is_file():
            raise ValueError("Missing or unsafe reviewed model artifact: " + name)
        with path.open("rb") as stream:
            observed = hashlib.file_digest(stream, "sha256").hexdigest()
        if observed != expected:
            raise ValueError("Changed reviewed model artifact: " + name)


def review(profile, model_ids, *, private_development=False):
    raw = REGISTRY_PATH.read_bytes()
    registry = json.loads(raw)
    expected = registry["profiles"].get(profile)
    if (
        registry["format"] != 1
        or not expected
        or len(model_ids) != len(set(model_ids))
        or set(expected) != set(model_ids)
    ):
        raise ValueError("Unknown or mismatched model redistribution profile")
    models = {}
    blockers = []
    for model_id in expected:
        model = registry["models"][model_id]
        if model["status"] not in {"approved", "unresolved"} or not model["evidence"]:
            raise ValueError("Invalid model permission evidence: " + model_id)
        for evidence in model["evidence"]:
            path = REGISTRY_PATH.parent / evidence["file"]
            if (
                not path.resolve().is_relative_to(REGISTRY_PATH.parent.resolve())
                or path.is_symlink()
                or not path.is_file()
                or hashlib.sha256(path.read_bytes()).hexdigest() != evidence["sha256"]
            ):
                raise ValueError("Missing or changed model permission evidence: " + model_id)
        models[model_id] = model
        if model["status"] != "approved":
            blockers.append(model_id + ": " + model["reason"])
    if blockers and not private_development:
        raise ValueError("Public model redistribution blocked:\n- " + "\n- ".join(blockers))
    return dict(
        format=1,
        profile=profile,
        mode="private-development" if private_development else "public",
        public_redistribution=not private_development and not blockers,
        registry_sha256=hashlib.sha256(raw).hexdigest(),
        models=models,
        blockers=blockers,
        disclaimer="Model permission evidence only, not full software release approval. Private development is not a grant of rights.",
    )


def verify_payload(record, profile, model_ids, *, private_development=False):
    previous = record.get("model_licenses")
    if not isinstance(previous, dict) or previous.get("format") != 1:
        raise ValueError("Payload lacks model redistribution evidence; rebuild it")
    current = review(profile, model_ids, private_development=private_development)
    if (
        previous.get("profile") != profile
        or previous.get("registry_sha256") != current["registry_sha256"]
        or previous.get("models") != current["models"]
    ):
        raise ValueError("Payload model redistribution evidence is stale; rebuild it")
    if not private_development and not previous.get("public_redistribution"):
        raise ValueError("Private payload cannot be promoted to public model redistribution")
    return current


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", choices=["windows", "android"])
    parser.add_argument("--private-development", action="store_true")
    args = parser.parse_args()
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    try:
        result = review(
            args.profile,
            registry["profiles"][args.profile],
            private_development=args.private_development,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
