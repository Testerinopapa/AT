# backtest/walkforward.py
import pandas as pd
import numpy as np
from typing import Dict, Any, Tuple, List
from dataclasses import dataclass
import backtrader as bt
from .backtrader_engine import run_backtrader_with_df, BTConfig, print_enhanced_analysis
from .optimizer import grid_search_optimize   # we keep the lightweight grid-search for in-sample

# --------------------------------------------------------------------------- #
@dataclass
class WFFold:
    """One walk-forward slice."""
    train_df: pd.DataFrame
    test_df:  pd.DataFrame
    train_start: pd.Timestamp
    train_end:   pd.Timestamp
    test_start:  pd.Timestamp
    test_end:    pd.Timestamp

# --------------------------------------------------------------------------- #
def _split_into_folds(df: pd.DataFrame, folds: int) -> List[WFFold]:
    """
    Evenly split a DataFrame into `folds` walk-forward blocks.
    The last fold is used only as a final out-of-sample test.
    """
    if folds < 2:
        raise ValueError("folds must be >= 2")

    n = len(df)
    fold_size = n // folds
    remainder = n % folds

    folds_list = []
    start = 0
    for i in range(folds):
        # distribute remainder evenly
        extra = 1 if i < remainder else 0
        end = start + fold_size + extra

        train_df = df.iloc[:start + fold_size] if i == 0 else df.iloc[:start]
        test_df  = df.iloc[start:end]

        folds_list.append(
            WFFold(
                train_df=train_df.copy(),
                test_df =test_df.copy(),
                train_start=train_df["time"].iloc[0],
                train_end  =train_df["time"].iloc[-1],
                test_start =test_df["time"].iloc[0],
                test_end   =test_df["time"].iloc[-1],
            )
        )
        start = end
    return folds_list


# --------------------------------------------------------------------------- #
def _optimise_on_train(train_df: pd.DataFrame,
                       base_cfg: BTConfig,
                       param_grid: Dict[str, list],
                       metric: str) -> Dict[str, Any]:
    """
    Run a *light* grid-search **only on the training slice**.
    Returns the best parameter dict according to `metric`.
    """
    # reuse the existing lightweight optimizer (it works with BacktestEngine)
    from .optimizer import grid_search_optimize, find_best_parameters

    # Convert BTConfig → BacktestConfig (they share the same fields)
    from .config import BacktestConfig
    cfg = BacktestConfig(
        symbol=base_cfg.symbol,
        days=0,                     # not used
        initial_balance=base_cfg.cash,
        volume=0.1,                 # will be overwritten by grid
        sl_pips=base_cfg.sl_pips,
        tp_pips=base_cfg.tp_pips,
        trail_pips=getattr(base_cfg, "trail_pips", 0.001),
        pip_value=10.0,
        timeframe=1,
    )

    grid_res = grid_search_optimize(train_df, cfg, param_grid, metric=metric)
    best_row = find_best_parameters(grid_res, metric=metric, min_trades=5).iloc[0]

    # build a dict that can overwrite BTConfig fields
    best_params = {k: v for k, v in best_row.items()
                   if k not in ("combination", "total_return", "win_rate",
                                "profit_factor", "total_trades")}
    return best_params


# --------------------------------------------------------------------------- #
def _run_oos_test(test_df: pd.DataFrame,
                  base_cfg: BTConfig,
                  extra_params: Dict[str, Any]) -> Tuple[float, Dict]:
    """
    Execute a single out-of-sample run with the *fixed* parameters.
    Returns (final equity, full analyzer dict)
    """
    # merge extra params into a new config
    cfg_dict = base_cfg.__dict__.copy()
    cfg_dict.update(extra_params)
    cfg = BTConfig(**cfg_dict)

    cerebro, _, analyzers = run_backtrader_with_df(
        df=test_df,
        strategy_name=base_cfg.__dict__.get("strategy_name", "trend_following"),
        strategy_params=base_cfg.__dict__.get("strategy_params", {}),
        config=cfg,
        plot=False,               # we don't want a plot per fold
    )
    final_equity = cerebro.broker.getvalue()
    return final_equity, analyzers


# --------------------------------------------------------------------------- #
def walk_forward_backtrader(df: pd.DataFrame,
                            config: BTConfig,
                            param_grid: Dict[str, list],
                            folds: int = 5,
                            metric: str = "sharpe") -> pd.DataFrame:
    """
    Full Walk-Forward pipeline **native to Backtrader**.

    Parameters
    ----------
    df : pd.DataFrame
        Must contain at least ``time, open, high, low, close, volume``.
    config : BTConfig
        Base Backtrader configuration (stake, cash, sl_pips, …).
    param_grid : dict
        Same format as ``grid_search_optimize`` (e.g. ``{'sl_pips': [...], 'tp_pips': [...]}``).
    folds : int
        Number of walk-forward windows (minimum 2).
    metric : str
        Metric used for in-sample optimisation.
        Supported: ``sharpe``, ``total_return``, ``calmar``, ``sqn``.

    Returns
    -------
    pd.DataFrame
        One row per fold with OOS performance + best in-sample params.
    """
    if "time" not in df.columns:
        raise ValueError("DataFrame must contain a `time` column")

    folds_list = _split_into_folds(df, folds)
    results = []

    print(f"\nWalk-Forward ({folds} folds) – metric: {metric.upper()}")
    print("=" * 70)

    for idx, fold in enumerate(folds_list[:-1], start=1):   # last slice = pure OOS
        print(f"\nFold {idx}/{folds-1}")
        print(f"  Train: {fold.train_start.date()} → {fold.train_end.date()} "
              f"({len(fold.train_df)} bars)")
        print(f"  Test : {fold.test_start.date()} → {fold.test_end.date()} "
              f"({len(fold.test_df)} bars)")

        # ---- 1. In-sample optimisation ---------------------------------
        best_params = _optimise_on_train(fold.train_df, config, param_grid, metric)
        print(f"  → Best in-sample params: {best_params}")

        # ---- 2. Out-of-sample run --------------------------------------
        final_eq, analyzers = _run_oos_test(fold.test_df, config, best_params)

        # ---- 3. Gather metrics -----------------------------------------
        total_ret = (final_eq - config.cash) / config.cash * 100
        sharpe = analyzers.get("sharpe", {}).get("sharperatio", np.nan)
        calmar = analyzers.get("calmar", {}).get("calmarratio", np.nan)
        sqn    = analyzers.get("sqn", {}).get("sqn", np.nan)
        maxdd  = analyzers.get("drawdown", {}).get("max", {}).get("drawdown", np.nan)

        results.append({
            "fold": idx,
            "train_start": fold.train_start,
            "train_end":   fold.train_end,
            "test_start":  fold.test_start,
            "test_end":    fold.test_end,
            "oos_return_%": total_ret,
            "oos_sharpe": sharpe,
            "oos_calmar": calmar,
            "oos_sqn":    sqn,
            "oos_maxdd_%": maxdd,
            **best_params
        })

        print(f"  OOS → Return: {total_ret:+.2f}% | Sharpe: {sharpe:.2f} | "
              f"MaxDD: {maxdd:.2f}%")

    # --------------------- Final pure OOS (last fold) --------------------
    final_fold = folds_list[-1]
    print(f"\nFinal pure OOS (no re-optimisation)")
    print(f"  Period: {final_fold.test_start.date()} → {final_fold.test_end.date()}")

    # use the parameters from the *previous* fold (standard WF practice)
    last_params = {k: v for k, v in results[-1].items() if k not in
                   ("fold", "train_start", "train_end", "test_start", "test_end",
                    "oos_return_%", "oos_sharpe", "oos_calmar", "oos_sqn", "oos_maxdd_%")}

    final_eq, final_analyzers = _run_oos_test(final_fold.test_df, config, last_params)
    final_ret = (final_eq - config.cash) / config.cash * 100
    final_sharpe = final_analyzers.get("sharpe", {}).get("sharperatio", np.nan)
    final_maxdd  = final_analyzers.get("drawdown", {}).get("max", {}).get("drawdown", np.nan)

    results.append({
        "fold": "FINAL_OOS",
        "train_start": folds_list[-2].train_end,      # last training end
        "train_end":   folds_list[-2].train_end,
        "test_start":  final_fold.test_start,
        "test_end":    final_fold.test_end,
        "oos_return_%": final_ret,
        "oos_sharpe": final_sharpe,
        "oos_calmar": np.nan,
        "oos_sqn":    np.nan,
        "oos_maxdd_%": final_maxdd,
        **last_params
    })
    print(f"  FINAL OOS → Return: {final_ret:+.2f}% | Sharpe: {final_sharpe:.2f}")

    # ------------------------------------------------------------------- #
    out_df = pd.DataFrame(results)
    print("\nWalk-Forward summary")
    print(out_df[[c for c in out_df.columns if not c.startswith("oos_")] +
                ["oos_return_%", "oos_sharpe", "oos_maxdd_%"]])
    return out_dfs