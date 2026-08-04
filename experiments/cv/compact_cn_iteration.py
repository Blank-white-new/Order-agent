from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from docx import Document

from experiments.common.metadata import ROOT
from experiments.cv.update_external_cvs import CN_AFTER, CN_AFTER_V1, CN_FILE


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cv-dir", type=Path, required=True)
    parser.add_argument("--audit", type=Path, default=ROOT / "experiments" / "results" / "cv_update.json")
    args = parser.parse_args()
    path = args.cv_dir / CN_FILE
    document = Document(path)
    matches = [paragraph for paragraph in document.paragraphs if paragraph.text == CN_AFTER_V1]
    if len(matches) != 1 or len(matches[0].runs) != 1:
        raise ValueError("expected exactly one first-render Chinese metric paragraph")
    matches[0].runs[0].text = CN_AFTER
    document.save(path)
    audit = json.loads(args.audit.read_text(encoding="utf-8"))
    cn_update = next(item for item in audit["updates"] if item["path"].endswith(CN_FILE))
    cn_update["after"] = CN_AFTER
    cn_update["after_sha256"] = sha256(path)
    audit["render_iterations"] = [
        {"language": "English", "iteration": 1, "pages": 1, "result": "accepted"},
        {"language": "Chinese", "iteration": 1, "pages": 2, "result": "rejected_overflow"},
        {"language": "Chinese", "iteration": 2, "result": "pending_render"}
    ]
    args.audit.write_text(json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"compacted {path}")


if __name__ == "__main__":
    main()
