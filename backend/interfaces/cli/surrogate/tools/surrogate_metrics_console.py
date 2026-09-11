from __future__ import annotations


def _print_effect(effect: dict[str, object]) -> None:
    print(f"  rank-neighbour pairs {effect['n_pairs']}"
          f" (significant {effect['n_significant_pairs']},"
          f" degenerate {effect['n_degenerate_pairs']})")
    median, p95 = effect["effect_error_pct_median"], effect["effect_error_pct_p95"]
    if median is None or p95 is None:
        print(f"  effect error        {effect['relative_error_unavailable']}")
    else:
        print(f"  effect error, median {median:.3f}%")
        print(f"  effect error, P95    {p95:.3f}%")
    absolute = effect["absolute_error_mln_rub"]
    print(f"  effect error, abs. median {absolute['median']:.3f} mln RUB,"
          f" P95 {absolute['p95']:.3f} mln RUB")


def _print_bhp(bhp: dict[str, object]) -> None:
    if "unavailable" in bhp:
        print(f"  bhp channel         {bhp['unavailable']}")
        return
    print(f"  bhp error, median   {bhp['bhp_error_bar_median']:.3f} bar"
          f" over {bhp['n_states']} states")
    print(f"  bhp error, P95      {bhp['bhp_error_bar_p95']:.3f} bar")
