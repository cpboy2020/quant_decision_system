# 替换原 ppo_controller.py 中的 env 初始化:
# from safe_action_wrapper import SafeLimiterWrapper
# env = PrometheusBackpressureEnv(PROM_URL)
# env = SafeLimiterWrapper(env, max_delta_pct=0.08, min_cooldown_sec=30.0)
# algo = PPOConfig().environment(env=env).build()
