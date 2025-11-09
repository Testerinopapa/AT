# Agents-Live Command Variations

The base command for invoking the live agent integration harness is:

```bash
python main.py --agents-live --symbol SYMBOL --start YYYY-MM-DD --end YYYY-MM-DD [--model MODEL] [--no-llm] [--verbose]
```

Below are curated Markdown lists of practical variations you can mix and match depending on the market, testing window, model preferences, or local time-zone needs.

## Forex Symbol Combinations
- `python main.py --agents-live --symbol EURUSD --start 2024-02-01 --end 2024-02-07 --model minimax/minimax-m2:free --verbose`
- `python main.py --agents-live --symbol GBPUSD --start 2024-03-04 --end 2024-03-08 --model gpt-4o-mini --verbose`
- `python main.py --agents-live --symbol USDJPY --start 2024-01-15 --end 2024-01-19 --no-llm`
- `python main.py --agents-live --symbol AUDCAD --start 2024-04-01 --end 2024-04-05 --model @preset/tradebot`

## Cross-Asset Examples
- `python main.py --agents-live --symbol XAUUSD --start 2024-05-06 --end 2024-05-10 --model deepseek/deepseek-chat --verbose`
- `python main.py --agents-live --symbol SPX500 --start 2024-01-08 --end 2024-01-12 --model openai/gpt-4o --verbose`
- `python main.py --agents-live --symbol BTCUSD --start 2024-02-12 --end 2024-02-16 --model anthropic/claude-3-haiku`

## Time-Zone & Session Focused Runs
- `TZ=UTC python main.py --agents-live --symbol EURUSD --start 2024-02-01 --end 2024-02-07 --model minimax/minimax-m2:free`
- `TZ=America/New_York python main.py --agents-live --symbol GBPJPY --start 2024-03-11 --end 2024-03-15 --verbose`
- `TZ=Asia/Tokyo python main.py --agents-live --symbol USDJPY --start 2024-04-08 --end 2024-04-12 --no-llm`

## Model & Verbosity Tweaks
- `python main.py --agents-live --symbol EURUSD --start 2024-02-01 --end 2024-02-07 --model openrouter/llama-3-8b`
- `python main.py --agents-live --symbol EURUSD --start 2024-02-01 --end 2024-02-07 --model minimax/minimax-m2:free --no-llm`
- `python main.py --agents-live --symbol EURUSD --start 2024-02-01 --end 2024-02-07 --model minimax/minimax-m2:free --verbose`
- `python main.py --agents-live --symbol EURUSD --start 2024-02-01 --end 2024-02-07 --model minimax/minimax-m2:free --no-llm --verbose`

## Troubleshooting & Sanity Checks
- `python main.py --agents-live --symbol EURUSD --start 2024-02-01 --end 2024-02-01 --no-llm` *(single-day smoke test)*
- `python main.py --agents-live --symbol EURUSD --start 2024-02-01 --end 2024-02-07 --model @preset/tradebot` *(use default preset without editing flags)*
- `TZ=UTC python main.py --agents-live --symbol EURUSD --start 2024-02-01 --end 2024-02-07 --model minimax/minimax-m2:free --no-llm --verbose` *(max verbosity, deterministic execution)*

Each command follows the same structure showcased by the CLI usage message:

```
usage: main.py [-h] --symbol SYMBOL --start START --end END [--model MODEL] [--no-llm] [--verbose]
```

Replace the placeholders with your desired parameters to explore other combinations.
