"""Finalize the blind result into auditable JSON and a human model report."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from surrogate.npv_block_head import load_direct_npv_head


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blind-report", type=Path, required=True)
    parser.add_argument("--comparison", type=Path, required=True)
    parser.add_argument("--decision", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--economics-lock", type=Path, required=True)
    parser.add_argument("--production-manifest", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-markdown", type=Path, required=True)
    return parser


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, text: str) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite final blind report: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def _verify(
    blind: dict[str, Any],
    comparison: dict[str, Any],
    decision: dict[str, Any],
    protocol: dict[str, Any],
    production: dict[str, Any],
    *,
    blind_report_sha256: str,
    comparison_sha256: str,
    protocol_sha256: str,
    economics_lock_sha256: str,
    production_manifest_sha256: str,
    manifest_root: Path,
) -> dict[str, bool]:
    promoted = decision.get("promoted") is True
    expected_version = (
        protocol["candidate"]["model_version"]
        if promoted
        else protocol["baseline"]["model_version"]
    )
    active_head_path = manifest_root / production["npv_head"]
    active_head = load_direct_npv_head(active_head_path)
    return {
        "blind_complete_81": (
            blind.get("n_scenarios") == protocol["plan"]["expected_scenarios"] == 81
            and blind.get("n_failed") == 0
            and blind.get("n_skipped") == 0
            and len(blind.get("scenario_identity", ())) == 81
        ),
        "plan_hash_matches": (
            blind.get("plan_hash")
            == comparison.get("blind_plan_hash")
            == protocol["plan"]["plan_hash"]
        ),
        "comparison_hash_matches_decision": (
            decision.get("comparison_sha256") == comparison_sha256
        ),
        "blind_report_hash_matches": (
            comparison.get("blind_report_sha256")
            == decision.get("blind_report_sha256")
            == blind_report_sha256
        ),
        "protocol_hash_matches": (
            comparison.get("protocol_sha256")
            == decision.get("protocol_sha256")
            == protocol_sha256
        ),
        "economics_lock_hash_matches": (
            comparison.get("economics_lock_sha256")
            == decision.get("economics_lock_sha256")
            == economics_lock_sha256
        ),
        "historical_test_not_read": comparison.get("historical_test_read") is False,
        "comparison_population_complete": (
            comparison.get("raw_row_count") == 81
            and comparison.get("unique_schedule_count", 0) > 1
        ),
        "decision_matches_comparison": (
            decision.get("promoted") is comparison.get("promote_candidate")
            and decision.get("promotion_gates") == comparison.get("promotion_gates")
        ),
        "production_manifest_hash_matches_decision": (
            decision.get(
                "production_manifest_sha256_after"
                if promoted
                else "production_manifest_sha256_before"
            )
            == production_manifest_sha256
        ),
        "production_version_matches_decision": (
            production.get("active_economic_model_version")
            == active_head.version
            == expected_version
            and production.get("active_economic_target_provenance_hash", "")
            == active_head.target_provenance_hash
        ),
    }


def _markdown(
    comparison: dict[str, Any],
    decision: dict[str, Any],
    checks: dict[str, bool],
) -> str:
    baseline = comparison["baseline"]["metrics"]
    candidate = comparison["candidate"]["metrics"]
    baseline_version = comparison["baseline"]["version"]
    candidate_version = comparison["candidate"]["version"]
    bootstrap = comparison["bootstrap"]
    mae_ci = bootstrap["mae_improvement_v2_minus_v3_rub"]
    rho_ci = bootstrap["spearman_difference_v3_minus_v2"]
    promoted = decision["promoted"]
    lines = [
        "# Финальный blind-результат NPV",
        "",
        (
            "**Вердикт: кандидат прошёл frozen promotion gate и включён "
            "в production.**"
            if promoted
            else (
                "**Вердикт: кандидат отвергнут; production остаётся "
                "на baseline.**"
            )
        ),
        "",
        (
            "Исторический test не использовался. Blind-набор после этого отчёта "
            "считается раскрытым и не может повторно служить holdout для "
            "следующего кандидата."
        ),
        "",
        "## Primary metrics — уникальные schedule hashes",
        "",
        "| Модель | MAE, млн ₽ | Spearman | Место истинного champion |",
        "|---|---:|---:|---:|",
        (
            f"| baseline (`{baseline_version[:12]}`) | "
            f"{baseline['mae_rub'] / 1e6:.3f} | "
            f"{baseline['ranking']['spearman_rank_correlation']:.4f} | "
            f"{baseline['rank_of_true_best']} |"
        ),
        (
            f"| candidate (`{candidate_version[:12]}`) | "
            f"{candidate['mae_rub'] / 1e6:.3f} | "
            f"{candidate['ranking']['spearman_rank_correlation']:.4f} | "
            f"{candidate['rank_of_true_best']} |"
        ),
        "",
        (
            f"Paired MAE improvement `baseline-candidate`: median "
            f"{mae_ci['median'] / 1e6:.3f} млн ₽, 95% CI "
            f"[{mae_ci['ci95_low'] / 1e6:.3f}; "
            f"{mae_ci['ci95_high'] / 1e6:.3f}] млн ₽."
        ),
        (
            f"Spearman difference `candidate-baseline`: median "
            f"{rho_ci['median']:.4f}, "
            f"95% CI [{rho_ci['ci95_low']:.4f}; {rho_ci['ci95_high']:.4f}]."
        ),
        "",
        "## Promotion gates",
        "",
        "| Gate | Результат |",
        "|---|---:|",
    ]
    lines.extend(
        f"| `{name}` | {'PASS' if value else 'FAIL'} |"
        for name, value in comparison["promotion_gates"].items()
    )
    lines.extend(
        [
            "",
            "## Ограничения",
            "",
            (
                "- 81 сценарий относится только к одной Model_Z и не является "
                "geological holdout."
            ),
            (
                "- Adaptive optimizer всё ещё способен эксплуатировать ошибку "
                "surrogate; финальный shortlist требует OPM Flow."
            ),
            (
                "- Физическая компонента использует зафиксированный trajectory "
                "ensemble; переносимость за пределы обучающего месторождения "
                "не доказана."
            ),
            (
                "- Этот blind теперь раскрыт; любая следующая селекция или "
                "калибровка требует нового untouched blind."
            ),
            (
                "- Promotion подтверждает улучшение на 80 уникальных "
                "непересекающихся schedules одной модели, но не покрывает "
                "геологическую неопределённость и production field shift."
            ),
            "",
            "## Completion checks",
            "",
        ]
    )
    lines.extend(
        f"- `{name}`: {'PASS' if value else 'FAIL'}" for name, value in checks.items()
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    args = _parser().parse_args()
    blind = json.loads(args.blind_report.read_text(encoding="utf-8"))
    comparison = json.loads(args.comparison.read_text(encoding="utf-8"))
    decision = json.loads(args.decision.read_text(encoding="utf-8"))
    protocol = json.loads(args.protocol.read_text(encoding="utf-8"))
    production = json.loads(args.production_manifest.read_text(encoding="utf-8"))
    checks = _verify(
        blind,
        comparison,
        decision,
        protocol,
        production,
        blind_report_sha256=_sha256(args.blind_report),
        comparison_sha256=_sha256(args.comparison),
        protocol_sha256=_sha256(args.protocol),
        economics_lock_sha256=_sha256(args.economics_lock),
        production_manifest_sha256=_sha256(args.production_manifest),
        manifest_root=args.production_manifest.parent,
    )
    if not all(checks.values()):
        failed = [name for name, value in checks.items() if not value]
        raise RuntimeError(f"final blind audit failed: {failed}")
    audit = {
        "format": "aios.surrogate-blind-final-audit.v1",
        "checks": checks,
        "all_checks_pass": True,
        "candidate_promoted": decision["promoted"],
        "objective_achieved": bool(decision["promoted"]),
        "known_target_defect": None,
        "target_audit": (
            "reference parity exact; PROD->SHUT->INJ contains a factual SHUT step"
        ),
        "next_action": (
            "monitor the production composite on OPM-verified optimizer "
            "shortlists; any further model selection requires a new untouched blind"
            if decision["promoted"]
            else (
                "refit only on disclosed schedules and use a new untouched blind "
                "before promotion"
            )
        ),
        "blind_report_sha256": _sha256(args.blind_report),
        "comparison_sha256": _sha256(args.comparison),
        "decision_sha256": _sha256(args.decision),
        "protocol_sha256": _sha256(args.protocol),
        "economics_lock_sha256": _sha256(args.economics_lock),
        "production_manifest_sha256": _sha256(args.production_manifest),
    }
    _write(
        args.output_json,
        json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    _write(args.output_markdown, _markdown(comparison, decision, checks))
    print(f"final blind report written; promoted={decision['promoted']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
