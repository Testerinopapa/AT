#!/bin/bash
# ==============================================
# TraderBot Roadmap - GitHub-style Checklists
# ==============================================

# TraderBot - Roadmap

A roadmap to build a full-featured AI trading bot with MetaTrader 5 in Python.

## Milestone 1 – Core Bot Foundation
- [x] Split logic into main.py and strategy.py
- [x] Connect to MT5 and log account info
- [x] Send BUY/SELL trades with proper rounding and SL/TP
- [x] Log executed trades to logs/trades.log
- [x] Fix type_filling to supported mode (FOK or IOC)
- [x] Add safe handling for "no signal" (do nothing)

## Milestone 2 – Continuous Trading Loop
- [x] Add a scheduler loop in main.py (check every 1–5 minutes)
- [x] Avoid duplicate trades: track open positions with mt5.positions_get()
- [x] Configurable trade interval in config/settings.json
- [x] Graceful shutdown handling (CTRL+C)

## Milestone 3 – Multiple Strategies
- [x] Move SimpleStrategy into a class in strategy.py
- [x] Add new strategies:
  - Moving Average Crossover
  - RSI threshold
  - MACD signals
- [x] Strategy manager: combine multiple strategies to decide overall BUY/SELL/NONE
- [ ] Unit tests for each strategy (tests/test_strategy.py)

## Milestone 4 – AI / ML Integration
- [ ] Create ai_module.py:
  - ML models (LSTM, XGBoost, or pretrained)
  - Train on historical MT5 data
  - Return BUY, SELL, NONE
- [ ] Add confidence threshold to avoid low-confidence trades
- [ ] Integrate AI signals into strategy manager

## Milestone 5 – Risk Management
- [ ] Dynamic lot sizing based on balance & risk percentage
- [ ] Stop-loss & take-profit automatically calculated
- [ ] Max concurrent trades limit
- [ ] Daily loss/profit limit (auto-disable trading)
- [ ] Logging P/L for analysis

## Milestone 6 – Logging & Analytics
- [x] Save trades in logs/trades.log with timestamps, action, price, SL, TP
- [ ] Optional: store logs in CSV/SQLite for analysis
- [ ] Generate performance reports:
  - Win rate
  - Average P/L
  - Strategy effectiveness

## Milestone 7 – Deployment & Automation
- [ ] Make main.py runnable as a service (Windows Task Scheduler / Linux systemd)
- [ ] Add configuration via config/settings.json for symbols, intervals, risk
- [ ] Auto-update strategies or AI models (optional)
- [ ] Add GitHub Actions for unit tests

## Milestone 8 – Optional Enhancements
- [ ] Web dashboard to view real-time trades
- [ ] Slack/Telegram alerts for executed trades
- [ ] Backtesting framework using historical MT5 data
- [ ] Multi-broker support (switch between demo/real or multiple accounts)
EOF
