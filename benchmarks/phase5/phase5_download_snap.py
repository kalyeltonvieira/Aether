#!/usr/bin/env python3
"""Download selected SNAP archives from the reviewed manifest and record SHA-256."""
from __future__ import annotations

from benchmarks._paths import phase5_manifest_path, repository_root

import argparse
import json
from pathlib import Path

from benchmarks.phase5.phase5_bench import download_dataset, sha256_file


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=str(phase5_manifest_path()))
    parser.add_argument("--data-dir", default="data/phase5_snap")
    parser.add_argument(
        "--datasets",
        default="email-eu-core,wiki-vote,soc-epinions1,web-google,sx-askubuntu",
        help="lista separada por vírgulas de IDs existentes no manifesto",
    )
    args = parser.parse_args()
    root = repository_root()
    manifest_path = Path(args.manifest)
    if not manifest_path.is_absolute():
        manifest_path = root / manifest_path
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = {item["id"]: item for item in manifest["datasets"]}
    ids = [value.strip() for value in args.datasets.split(",") if value.strip()]
    if not ids or len(ids) != len(set(ids)):
        parser.error("dataset IDs devem ser não vazios e sem duplicatas")
    unknown = sorted(set(ids) - set(entries))
    if unknown:
        parser.error(f"dataset IDs não registrados no manifesto: {unknown}")
    data_dir = Path(args.data_dir)
    if not data_dir.is_absolute():
        data_dir = root / data_dir

    for dataset_id in ids:
        entry = entries[dataset_id]
        required = ("snap_page", "download_url", "license_or_terms", "nodes", "edges", "directed")
        missing = [field for field in required if field not in entry]
        if missing:
            raise ValueError(f"{dataset_id} lacks provenance/conditions fields: {missing}")
        terms = entry["license_or_terms"].lower()
        if "não foi localizada" in terms or "not located" in terms or "unknown" in terms:
            print(f"NOTICE {dataset_id}: dataset-specific terms not located; no software license is inferred")
        destination = download_dataset(entry, data_dir)
        actual_sha = sha256_file(destination)
        if entry.get("sha256") and entry["sha256"].lower() != actual_sha.lower():
            raise ValueError(
                f"SHA-256 mismatch for {dataset_id}: manifest={entry['sha256']} downloaded={actual_sha}"
            )
        entry["sha256"] = actual_sha
        entry["file_size_bytes"] = destination.stat().st_size
        entry["local_archive_excluded_from_git"] = True
        print(
            f"downloaded {dataset_id}: {destination} bytes={entry['file_size_bytes']} sha256={actual_sha}",
            flush=True,
        )
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
