#!/usr/bin/env python3
import os, json, argparse, logging, pandas as pd, numpy as np
from itertools import product
from datetime import datetime
from strategies.momentum import MomentumStrategy
from backtest.engine import BacktestEngine
from backtest.rules import AshareRule
from backtest.execution import SlippageModel
from core.interfaces import MarketType
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

def gen_data(n=300):
    np.random.seed(42)
    idx = pd.date_range(end=datetime.utcnow(), periods=n, freq="B")
    return pd.DataFrame({"close": 10*np.cumprod(1+np.random.normal(0.001, 0.02, n)), "volume": np.random.randint(1e5, 5e5, n)}, index=idx)

def calc_metrics(eq):
    ret = eq.pct_change().dropna()
    if len(ret)<10: return {"AnnRet":0,"Vol":0,"Sharpe":0,"MaxDD":0,"Calmar":0}
    ann = (1+ret.mean())**252-1; vol = ret.std()*np.sqrt(252); dd = (eq/eq.cummax()-1).min()
    return {"AnnRet":round(ann,4), "Vol":round(vol,4), "Sharpe":round((ann-0.02)/vol,2), "MaxDD":round(dd,4), "Calmar":round(ann/abs(dd),2) if dd!=0 else 0}

def run_bt(p, data):
    s = MomentumStrategy(params=p)
    e = BacktestEngine(s, AshareRule(), SlippageModel())
    eq = e.run(data, lambda: type("C",(),{"market":MarketType.A_SHARE})())
    return eq["equity"], calc_metrics(eq["equity"])

def monte_carlo(eq, n=1000):
    ret = eq.pct_change().dropna()
    orig = calc_metrics(eq)["Sharpe"]
    better = sum(1 for _ in range(n) if calc_metrics(pd.Series(np.random.permutation(ret)).cumsum()+1)["Sharpe"] >= orig)
    return {"p_value": round(better/n, 3), "significant": better/n < 0.05, "original_sharpe": round(orig, 3)}

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["grid","mc"], default="mc")
    ap.add_argument("--days", type=int, default=300)
    args = ap.parse_args()
    d = gen_data(args.days)
    logging.info(f"📊 数据加载: {len(d)} Bar")
    if args.mode == "mc":
        eq, met = run_bt({"fast_window":5, "slow_window":20, "threshold":0.6}, d)
        rpt = {"mode":"monte_carlo", "metrics":met, "monte_carlo":monte_carlo(eq)}
        os.makedirs("results", exist_ok=True)
        rpt["generated_at"] = datetime.utcnow().isoformat()
        with open("results/backtest_report.json", "w") as f: json.dump(rpt, f, indent=2, default=str)
        logging.info("📝 报告已保存至 results/backtest_report.json")
