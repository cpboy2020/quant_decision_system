import logging
import pandas as pd
from core.interfaces import MarketContext
from backtest.execution import Portfolio
logger = logging.getLogger(__name__)

class BacktestEngine:
    def __init__(self, strategy, market_rule, slippage, initial_capital=1_000_000.0, target_horizon=5):
        self.strategy, self.rule, self.slippage = strategy, market_rule, slippage
        self.portfolio = Portfolio(cash=initial_capital)
        self.equity_curve = [initial_capital]
    def run(self, df, context_provider):
        for i in range(len(df)):
            dt = df.index[i]; bar = df.iloc[i]
            ctx = MarketContext(market=context_provider().market, current_dt=dt, trading_calendar=[],
                                contract_specs={f"{bar.get('symbol','UNK')}_prev_close": df.iloc[i-1].get('close',bar['close']) if i>0 else bar['close'], f"{bar.get('symbol','UNK')}_close": bar['close']})
            if i>0 and df.index[i].date()!=df.index[i-1].date(): self.portfolio.update_t_plus_1(True)
            for sig in self.strategy.on_bar(ctx, bar.to_dict()): self._process(sig, ctx, bar)
            self.equity_curve.append(self.portfolio.cash + sum(p*bar.get('close',0) for p in self.portfolio.positions.values()))
        return pd.Series(self.equity_curve, index=pd.Index([pd.NaT]+list(df.index)), name="equity").dropna().to_frame()
    def _process(self, sig, ctx, bar):
        sym, dir_, qty = sig.symbol, sig.direction, int(sig.strength*1000)
        if qty<=0: return
        order = {"target_qty": qty}
        self.rule.adjust_order(order, ctx)
        eq = order["target_qty"]
        if eq<=0: return
        if dir_=="LONG":
            if not self.rule.is_tradable(sym, ctx.current_dt, ctx) or not self.portfolio.check_buy(sym, eq): return
            ep = self.slippage.get_exec_price(bar['close'], "BUY", eq, bar.get('volume',1))
            self.portfolio.execute_trade(sym, "BUY", ep, eq, self.rule.calculate_commission(sym,ep,eq), 0.0, ctx.current_dt)
        else:
            avail = self.portfolio.available_qty.get(sym,0)
            eq = min(eq, avail)
            if eq<=0 or not self.rule.is_tradable(sym, ctx.current_dt, ctx): return
            ep = self.slippage.get_exec_price(bar['close'], "SELL", eq, bar.get('volume',1))
            self.portfolio.execute_trade(sym, "SELL", ep, eq, self.rule.calculate_commission(sym,ep,eq), 0.0, ctx.current_dt)
            self.portfolio.available_qty[sym] = self.portfolio.available_qty.get(sym,0)-eq
