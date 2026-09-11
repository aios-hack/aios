from pathlib import Path
import argparse
import hashlib
import json
import tarfile


def install(destination: Path) -> None:
    bundle = Path(__file__).resolve().parents[1] / "artifacts/surrogate-20260906"
    metadata = json.loads((bundle / "manifest.json").read_text())
    archive = bundle / "runtime.tar.gz"
    if hashlib.sha256(archive.read_bytes()).hexdigest() != metadata["archive_sha256"]:
        raise ValueError("Archive checksum mismatch")
    pending = []
    with tarfile.open(archive, "r:gz") as source:
        members = source.getmembers()
        if len(members) != len(metadata["files_sha256"]) or {m.name for m in members} != set(metadata["files_sha256"]):
            raise ValueError("Archive inventory mismatch")
        for member in members:
            relative = Path(member.name)
            if not member.isfile() or relative.is_absolute() or ".." in relative.parts:
                raise ValueError(f"Unsafe archive entry: {member.name}")
            content = source.extractfile(member).read()
            if hashlib.sha256(content).hexdigest() != metadata["files_sha256"][member.name]:
                raise ValueError(f"File checksum mismatch: {member.name}")
            target = destination / relative
            if target.exists():
                if target.read_bytes() != content:
                    raise FileExistsError(f"Preserving changed local file: {target}")
            else:
                pending.append((target, content))
    for target, content in pending:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as output:
            output.write(content)
    print(f"Runtime verified: {len(members)} files; installed {len(pending)} in {destination}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, default=Path(__file__).resolve().parents[1])
    install(parser.parse_args().destination.resolve())
