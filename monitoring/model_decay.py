import logging
import numpy as np
logger = logging.getLogger(__name__)

class ModelDecayMonitor:
    def __init__(self, ic_thr=0.03, psi_thr=0.25, window=60):
        self.ic_thr, self.psi_thr, self.window = ic_thr, psi_thr, window
        self.pred, self.actual = [], []
    def update(self, p, a):
        self.pred.append(p); self.actual.append(a)
        if len(self.pred)>self.window*2: self.pred.pop(0); self.actual.pop(0)
    def compute_psi(self):
        if len(self.pred)<30: return 0.0
        tr, rec = self.pred[:self.window], self.pred[self.window:]
        bins = np.percentile(tr, np.linspace(0,100,11)); bins[-1]=np.inf
        tc, rc = np.histogram(tr, bins=bins)[0]+1e-5, np.histogram(rec, bins=bins)[0]+1e-5
        tp, rp = tc/tc.sum(), rc/rc.sum()
        return float(np.sum((rp-tp)*np.log(rp/tp)))
    def compute_rolling_ic(self):
        if len(self.pred)<10: return 0.0
        return float(np.corrcoef(self.pred[-self.window:], self.actual[-self.window:])[0,1])
    def check_health(self):
        ic, psi = self.compute_rolling_ic(), self.compute_psi()
        status, alert = "healthy", None
        if abs(ic)<self.ic_thr: alert=f"IC衰减: {ic:.4f}"; status="degraded"
        if psi>self.psi_thr: alert=f"PSI漂移: {psi:.4f}"; status="critical" if psi>0.5 else "degraded"
        return {"IC":ic, "PSI":psi, "status":status, "alert":alert}
