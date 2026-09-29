"""S3-compatible, immutable processed-run handoff between publisher and API.

NOAA acquisition runs only in the publisher. The web process reads already
processed artifacts, validates their hashes, and retains its last valid run
if the object store is temporarily unavailable.
"""

from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile


class CurrentObjectStore:
    def __init__(self, bucket: str, prefix: str = "yuki/v2/current", endpoint_url: str | None = None):
        if not bucket or not prefix.strip("/"):
            raise ValueError("Object bucket and prefix are required")
        import boto3
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self.client = boto3.client("s3", endpoint_url=endpoint_url or None)

    @classmethod
    def from_environment(cls) -> CurrentObjectStore | None:
        bucket = os.environ.get("FORECAST_BUST_OBJECT_BUCKET")
        if not bucket:
            return None
        return cls(bucket, os.environ.get("FORECAST_BUST_OBJECT_PREFIX", "yuki/v2/current"),
                   os.environ.get("FORECAST_BUST_OBJECT_ENDPOINT"))

    def _key(self, suffix: str) -> str:
        return f"{self.prefix}/{suffix}"

    @staticmethod
    def _hash(path: Path) -> str:
        hasher = sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    @staticmethod
    def _atomic_download(client, bucket: str, key: str, target: Path, expected: str) -> None:
        if target.is_file() and CurrentObjectStore._hash(target) == expected:
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(dir=target.parent, prefix=f".{target.name}.", suffix=".part", delete=False) as temp:
            partial = Path(temp.name)
        try:
            client.download_file(bucket, key, str(partial))
            if CurrentObjectStore._hash(partial) != expected:
                raise ValueError("Object-store artifact checksum mismatch")
            partial.replace(target)
        finally:
            partial.unlink(missing_ok=True)

    def publish(self, processed_root: Path, identifier: str) -> None:
        """Upload validated immutable run objects, then commit latest pointer last."""
        run_root = processed_root / "runs" / identifier
        manifest_path = run_root / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("status") != "complete" or manifest.get("run_id") != identifier:
            raise ValueError("Cannot publish an incomplete processed run")
        for name in ("features.csv.gz", "predictions.json.gz"):
            path = run_root / name
            if self._hash(path) != manifest["artifacts"][name]["sha256"]:
                raise ValueError("Cannot publish a processed run with an invalid artifact hash")
        for name in ("features.csv.gz", "predictions.json.gz", "manifest.json"):
            path = run_root / name
            key = self._key(f"runs/{identifier}/{name}")
            expected = self._hash(path)
            try:
                remote = self.client.head_object(Bucket=self.bucket, Key=key)
            except Exception as error:
                response = getattr(error, "response", {})
                if response.get("Error", {}).get("Code") not in {"NoSuchKey", "NotFound", "404"}:
                    raise
                self.client.upload_file(str(path), self.bucket, key,
                                        ExtraArgs={"Metadata": {"sha256": expected}})
            else:
                if remote.get("Metadata", {}).get("sha256") != expected:
                    raise ValueError("Existing immutable processed-run object has a different checksum")
        pointer = {"run_id": identifier, "manifest_sha256": self._hash(manifest_path)}
        self.client.put_object(Bucket=self.bucket, Key=self._key("latest.json"),
                               Body=json.dumps(pointer, separators=(",", ":")).encode("utf-8"),
                               ContentType="application/json")

    def sync_latest(self, processed_root: Path) -> str | None:
        """Mirror a complete latest run locally; never change local pointer on failure."""
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=self._key("latest.json"))
        except Exception as error:
            response_data = getattr(error, "response", {})
            if response_data.get("Error", {}).get("Code") in {"NoSuchKey", "404"}:
                return None
            raise
        pointer = json.loads(response["Body"].read())
        identifier = pointer["run_id"]
        if not isinstance(identifier, str) or len(identifier) != 10 or not identifier.isdigit():
            raise ValueError("Object-store current pointer has an invalid run ID")
        run_root = processed_root / "runs" / identifier
        manifest_key = self._key(f"runs/{identifier}/manifest.json")
        self._atomic_download(self.client, self.bucket, manifest_key, run_root / "manifest.json",
                              pointer["manifest_sha256"])
        manifest = json.loads((run_root / "manifest.json").read_text(encoding="utf-8"))
        if manifest.get("status") != "complete" or manifest.get("run_id") != identifier:
            raise ValueError("Object-store current manifest is not complete")
        for name in ("features.csv.gz", "predictions.json.gz"):
            self._atomic_download(self.client, self.bucket, self._key(f"runs/{identifier}/{name}"),
                                  run_root / name, manifest["artifacts"][name]["sha256"])
        processed_root.mkdir(parents=True, exist_ok=True)
        partial = processed_root / "latest.json.part"
        partial.write_text(json.dumps(pointer), encoding="utf-8")
        partial.replace(processed_root / "latest.json")
        return identifier
