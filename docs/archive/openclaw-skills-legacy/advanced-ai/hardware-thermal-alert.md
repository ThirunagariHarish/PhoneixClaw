# Hardware Thermal Alert

## Purpose
Stop trading if server CPU/GPU temperature exceeds safe threshold to prevent hardware damage and throttling.

## Category
advanced-ai

## Triggers
- On periodic health check (e.g., every 30 seconds)
- Before executing high-frequency or compute-intensive strategies
- When user enables thermal monitoring
- When GPU is used for local LLM or inference

## Inputs
- `cpu_threshold_c`: number — Max CPU temp in Celsius (default: 85)
- `gpu_threshold_c`: number — Max GPU temp in Celsius (default: 90)
- `sensors`: string[] — Which to check: ["cpu", "gpu"] (default: both)
- `cooldown_minutes`: number — Minutes to wait after breach before resuming (default: 5)

## Outputs
- `status`: string — "OK" | "CPU_OVER" | "GPU_OVER" | "COOLING"
- `temperatures`: object — {cpu_c: number, gpu_c: number}
- `trading_paused`: boolean — True if trading should be halted
- `resume_at`: string — ISO timestamp when cooldown ends (if COOLING)

## Steps
1. Query system for CPU temp (e.g., psutil, /sys/class/thermal, or vendor SDK)
2. Query GPU temp if applicable (nvidia-smi, AMD, etc.)
3. Compare to thresholds; set status (OK, CPU_OVER, GPU_OVER)
4. If over: set trading_paused=true; start cooldown timer
5. During cooldown: status=COOLING; resume_at = now + cooldown_minutes
6. After cooldown: recheck; if OK, set trading_paused=false
7. Return status, temperatures, trading_paused, resume_at
8. Orchestrator uses trading_paused to block order submission

## Example
```
Input: cpu_threshold_c=85, gpu_threshold_c=90, sensors=["cpu","gpu"]
Output: {
  status: "GPU_OVER",
  temperatures: {cpu_c: 72, gpu_c: 93},
  trading_paused: true,
  resume_at: "2025-03-03T15:35:00Z"
}
```

## Notes
- Thresholds vary by hardware; conservative defaults for longevity
- Consider ambient temp and cooling; cloud instances may report differently
- Integrate with sleep-mode-optimizer: thermal load lower during sleep
