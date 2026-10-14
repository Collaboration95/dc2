"""Retain inspectable test/package receipts without environment, logs or raw failures."""

import hashlib
import json
from xml.etree import ElementTree as ET

from scripts.aws.transport import OperationError


def retained_reports(trivy_bytes, junit_bytes, *, source, config_id):
    report = json.loads(trivy_bytes)
    if report.get("Metadata", {}).get("ImageID") != config_id:
        raise OperationError("Retained scan must match the exact artifact")
    results = []
    for result in report.get("Results", []):
        results.append(
            {
                "Class": result.get("Class"),
                "Type": result.get("Type"),
                "Packages": [
                    {k: p[k] for k in ("Name", "Version", "Release", "Arch") if k in p}
                    for p in result.get("Packages", [])
                ],
                "Vulnerabilities": [
                    {
                        k: v[k]
                        for k in (
                            "VulnerabilityID",
                            "PkgName",
                            "InstalledVersion",
                            "FixedVersion",
                            "Severity",
                            "Status",
                        )
                        if k in v
                    }
                    for v in result.get("Vulnerabilities", [])
                ],
            }
        )
    selected_scan = {
        "ArtifactName": config_id,
        "ArtifactType": "container_image",
        "Metadata": {"ImageID": config_id},
        "Results": results,
        "SourceSHA": source,
        "RawReportSHA256": hashlib.sha256(trivy_bytes).hexdigest(),
    }
    root = ET.fromstring(junit_bytes)
    cases = []
    for case in root.iter("testcase"):
        if case.find("failure") is not None or case.find("error") is not None:
            raise OperationError("Failed source tests cannot become passing artifact evidence")
        cases.append(
            {
                "name": case.get("name", "").split("[", 1)[0],
                "class": case.get("classname", ""),
                "seconds": float(case.get("time", "0")),
                "status": "SKIPPED" if case.find("skipped") is not None else "PASS",
            }
        )
    if not any(c["status"] == "PASS" for c in cases):
        raise OperationError("Executed source cases are required")
    selected_tests = {
        "source_sha": source,
        "config_id": config_id,
        "cases": cases,
        "passed": sum(c["status"] == "PASS" for c in cases),
        "raw_report_sha256": hashlib.sha256(junit_bytes).hexdigest(),
    }
    return (
        json.dumps(selected_scan, sort_keys=True).encode(),
        json.dumps(selected_tests, sort_keys=True).encode(),
    )
