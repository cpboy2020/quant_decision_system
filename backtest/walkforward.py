import logging
import pandas as pd
logger = logging.getLogger(__name__)

class WalkForwardValidator:
    def __init__(self, train_len=252, test_len=63, step_len=21, embargo_len=5):
        self.train_len, self.test_len, self.step_len, self.embargo_len = train_len, test_len, step_len, embargo_len
    def validate(self, full_data, model_train_fn, engine_factory, context_provider):
        all_eq, start = [], 0
        while start+self.train_len+self.embargo_len+self.test_len <= len(full_data):
            tr_end = start+self.train_len; te_start = tr_end+self.embargo_len; te_end = te_start+self.test_len
            train_df, test_df = full_data.iloc[start:tr_end], full_data.iloc[te_start:te_end]
            model = model_train_fn(train_df)
            engine = engine_factory(model)
            all_eq.append(engine.run(test_df, context_provider))
            start += self.step_len
        combined = pd.concat(all_eq); combined = combined[~combined.index.duplicated(keep='last')]
        logger.info(f"✅ Walk-Forward 完成 | 最终净值: {combined.iloc[-1,0]:.2f}")
        return combined
