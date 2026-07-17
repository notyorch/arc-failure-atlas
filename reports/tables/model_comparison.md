# Model comparison (local pilots / smokes)

All rows are `local_pilot_partial` unless noted. `task_solved_rate` is ARC-official task granularity (Decision 21).

| model                       | benchmark   |   n_tasks |   n_items | task_solved_rate   | solved_rate   | parse_error_rate   | avg_latency_ms   | experiment_id                  | run_id                                         |
|:----------------------------|:------------|----------:|----------:|:-------------------|:--------------|:-------------------|:-----------------|:-------------------------------|:-----------------------------------------------|
| glm-5.2                     | ARC-AGI-1   |        20 |        20 | 30.0%              | 30.0%         | 40.0%              | 56.2s            | pilot-glm52-agi1-n20-v2        | 20260716T050606Z_opencode-glm-5.2_2343e8c5     |
| glm-5.2                     | ARC-AGI-2   |       120 |       167 | 0.0%               | 0.0%          | 79.0%              | 63.9s            | pilot-glm52-agi2-n120          | 20260716T155616Z_opencode-glm-5.2_15691f67     |
| kimi-k2.6                   | ARC-AGI-2   |         5 |         5 | 0.0%               | 0.0%          | 0.0%               | 2.8s             | pilot-kimi-k26-agi2-n5-nothink | 20260716T032633Z_kimi-k2.6_b997534f            |
| glm-5.2                     | ARC-AGI-2   |         5 |         7 | 0.0%               | 0.0%          | 85.7%              | 107.9s           | smoke-glm52-agi2-n5            | 20260716T053528Z_opencode-glm-5.2_83788fd6     |
| qwen3.7-max                 | ARC-AGI-2   |         5 |         7 | 0.0%               | 0.0%          | 0.0%               | 20.4s            | smoke-qwen37max-agi2-n5        | 20260716T062140Z_opencode-qwen3.7-max_2c9e97c4 |
| z-ai/glm-5.2                | unknown     |        26 |        26 | 30.8%              | 30.8%         | 0.0%               | 15.3s            | real-glm52                     | 20260715T172307Z_openai_z-ai-glm-5.2_8f9cf828  |
| deepseek-ai/deepseek-v4-pro | unknown     |         5 |         5 | 20.0%              | 20.0%         | 0.0%               | 165.0s           | pilot-nim-dsv4pro              | 20260716T010504Z_nim-deepseek-v4-pro_76a8317f  |
