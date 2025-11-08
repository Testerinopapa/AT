"""Environment agent for orchestrating strategy signals and optional LLM reasoning.

The agent keeps lightweight in-memory context buffers for different time horizons
(short-, mid-, long-term plus a reflection layer) and uses them to either
produce prompts for an LLM backend or to aggregate strategy signals directly
when no model is available.
"""
from __future__ import annotations

from collections import Counter
from numbers import Number
from typing import Any, Dict, Iterable, List, Optional, Tuple


class EnvironmentAgent:
    """Coordinate observations, memories, and trading decisions.

    Parameters
    ----------
    strategy_manager:
        The :class:`~strategies.strategy_manager.StrategyManager` instance that
        provides individual strategy signals.
    symbol:
        Trading symbol that will be passed to the strategy manager when
        gathering signals.
    trade_logger:
        Optional :class:`~trade_logger.TradeLogger` instance. When supplied it
        can be queried (if it exposes helper methods) for realized P/L to feed
        back into the reflection memory.
    llm_executor:
        Optional callable or object with a ``run(prompt: str)`` method. When
        present, the agent will build prompts from its memory layers and use
        the LLM output to decide trades. When ``None`` the agent falls back to
        majority voting across strategies so live trading can continue without
        an LLM backend.
    memory_limits:
        Optional overrides for the maximum number of entries to keep per layer.
        Keys: ``"short"``, ``"mid"``, ``"long"``, ``"reflection"``.
    feedback_gain:
        Multiplier applied when adjusting memory weights from feedback.
    feedback_cap:
        Absolute cap (in the same units as profit/loss) used when normalising
        feedback before applying it to memory weights.
    """

    DEFAULT_LIMITS: Dict[str, int] = {
        "short": 32,
        "mid": 24,
        "long": 16,
        "reflection": 12,
    }

    def __init__(
        self,
        strategy_manager,
        symbol: str,
        trade_logger: Optional[Any] = None,
        llm_executor: Optional[Any] = None,
        memory_limits: Optional[Dict[str, int]] = None,
        feedback_gain: float = 0.05,
        feedback_cap: float = 5.0,
    ) -> None:
        self.strategy_manager = strategy_manager
        self.symbol = symbol
        self.trade_logger = trade_logger
        self.llm_executor = llm_executor
        self.feedback_gain = feedback_gain
        self.feedback_cap = abs(feedback_cap)

        limits = dict(self.DEFAULT_LIMITS)
        if memory_limits:
            limits.update({k: max(1, int(v)) for k, v in memory_limits.items()})
        self.memory_limits = limits

        self.short_term: List[Dict[str, Any]] = []
        self.mid_term: List[Dict[str, Any]] = []
        self.long_term: List[Dict[str, Any]] = []
        self.reflections: List[Dict[str, Any]] = []

        self.last_prompt: Optional[str] = None
        self.last_llm_output: Optional[Any] = None
        self.last_signal_error: Optional[str] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def step(
        self,
        date: str,
        price: Optional[float],
        filing_k: Optional[Iterable[str]],
        filing_q: Optional[Iterable[str]],
        news: Optional[Iterable[str]],
        future_return: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Process a new environment observation.

        The method appends incoming information to the appropriate memory
        layers, prunes them to their configured lengths, and then either builds
        a prompt for the LLM backend or performs a majority vote over the
        available strategy signals.

        Parameters
        ----------
        date:
            Timestamp associated with the observation.
        price:
            Latest trade price; stored in the short-term memory if provided.
        filing_k / filing_q:
            Collections (or single strings) representing 10-K / 10-Q filings.
            They are stored in the long- and mid-term memory respectively.
        news:
            Headlines or bullet points for the short-term memory.
        future_return:
            Optional simulated return used when backtesting. When provided it is
            routed through :meth:`apply_feedback` so the agent can adjust the
            weight of recent memories without relying on external vector
            databases.

        Returns
        -------
        dict
            Includes the individual strategy signals, the derived decision, and
            any LLM output if applicable.
        """

        self._append_short_term(date, price, news)
        self._append_mid_term(date, filing_q)
        self._append_long_term(date, filing_k)

        feedback_value: Optional[float] = None
        if future_return is not None:
            reflection_text = f"{date} | Simulated future return: {future_return:+.2%}"
            self._add_memory(self.reflections, reflection_text, layer="reflection")
            feedback_value = future_return
        else:
            feedback_value = self._pull_trade_feedback()
            if feedback_value is not None:
                reflection_text = f"{date} | Realised P/L: {feedback_value:+.2f}"
                self._add_memory(self.reflections, reflection_text, layer="reflection")

        if feedback_value is not None:
            self.apply_feedback(feedback_value)

        signals = self._gather_strategy_signals()

        decision: str
        rationale: str
        llm_output: Optional[Any] = None

        if self.llm_executor:
            prompt = self._build_prompt(date, price, signals)
            llm_output = self._run_llm(prompt)
            decision, rationale = self._parse_llm_output(llm_output, signals)
            self.last_prompt = prompt
            self.last_llm_output = llm_output
        else:
            decision, rationale = self._decide_from_signals(signals)
            self.last_prompt = None
            self.last_llm_output = None

        result = {
            "date": date,
            "price": price,
            "signals": signals,
            "decision": decision,
            "rationale": rationale,
        }
        if llm_output is not None:
            result["llm_output"] = llm_output
            result["prompt"] = self.last_prompt

        return result

    # ------------------------------------------------------------------
    # Feedback loop
    # ------------------------------------------------------------------
    def apply_feedback(self, realized_pl: float) -> None:
        """Adjust memory weights based on realised performance.

        The hook can be called with simulated ``future_return`` values (as done
        during backtests) or wired to :class:`~trade_logger.TradeLogger` events
        that yield realised profit/loss figures. Positive feedback boosts the
        weight of recent memories while negative feedback down-weights them,
        allowing the agent to re-balance importance without maintaining an
        external vector store.
        """

        if not self.short_term and not self.mid_term and not self.long_term:
            return

        clipped = max(-self.feedback_cap, min(self.feedback_cap, realized_pl))
        adjustment = clipped * self.feedback_gain

        for buffer, layer_name in (
            (self.short_term, "short"),
            (self.mid_term, "mid"),
            (self.long_term, "long"),
            (self.reflections, "reflection"),
        ):
            limit = self.memory_limits.get(layer_name, len(buffer))
            for entry in buffer[-limit:]:
                entry["weight"] = max(0.1, entry.get("weight", 1.0) + adjustment)

    # ------------------------------------------------------------------
    # Helpers: memory management
    # ------------------------------------------------------------------
    def _append_short_term(
        self,
        date: str,
        price: Optional[float],
        news: Optional[Iterable[str]],
    ) -> None:
        if isinstance(price, Number):
            price_text = f"{date} | Price tick: {float(price):.5f}"
            self._add_memory(self.short_term, price_text, layer="short")
        elif price is not None:
            self._add_memory(self.short_term, f"{date} | Price tick: {price}", layer="short")

        for item in self._ensure_iterable(news):
            if item:
                self._add_memory(self.short_term, f"{date} | News: {item}", layer="short")

    def _append_mid_term(self, date: str, filing_q: Optional[Iterable[str]]) -> None:
        for item in self._ensure_iterable(filing_q):
            if item:
                self._add_memory(self.mid_term, f"{date} | 10-Q excerpt: {item}", layer="mid")

    def _append_long_term(self, date: str, filing_k: Optional[Iterable[str]]) -> None:
        for item in self._ensure_iterable(filing_k):
            if item:
                self._add_memory(self.long_term, f"{date} | 10-K excerpt: {item}", layer="long")

    def _add_memory(
        self,
        buffer: List[Dict[str, Any]],
        content: str,
        *,
        layer: str,
        weight: float = 1.0,
    ) -> None:
        entry = {"content": content.strip(), "weight": float(weight)}
        buffer.append(entry)
        self._prune_buffer(buffer, self.memory_limits[layer])

    def _prune_buffer(self, buffer: List[Dict[str, Any]], max_len: int) -> None:
        overflow = len(buffer) - max_len
        if overflow > 0:
            del buffer[:overflow]

    # ------------------------------------------------------------------
    # Helpers: strategy / decision logic
    # ------------------------------------------------------------------
    def _gather_strategy_signals(self) -> Dict[str, str]:
        self.last_signal_error = None
        if not self.strategy_manager:
            self.last_signal_error = "Strategy manager not configured."
            return {}
        try:
            signals = self.strategy_manager.get_individual_signals(self.symbol)
        except Exception as exc:  # pragma: no cover - defensive logging
            self.last_signal_error = f"Failed to gather signals: {exc}"
            return {}
        return signals

    def _decide_from_signals(self, signals: Dict[str, str]) -> Tuple[str, str]:
        if not signals:
            if self.last_signal_error:
                return "NONE", self.last_signal_error
        
            return "NONE", "No strategy signals available."

        counter = Counter(signal for signal in signals.values() if signal != "NONE")
        if not counter:
            return "NONE", "All enabled strategies returned NONE."

        most_common = counter.most_common(1)[0]
        signal, count = most_common
        total = sum(counter.values())

        if count > total / 2:
            rationale = f"Majority vote from strategies ({count}/{total}) favours {signal}."
            return signal, rationale

        return "NONE", "No majority agreement among strategies."

    # ------------------------------------------------------------------
    # Helpers: LLM integration
    # ------------------------------------------------------------------
    def _build_prompt(self, date: str, price: Optional[float], signals: Dict[str, str]) -> str:
        sections = [
            ("Short-term context", self.short_term),
            ("Mid-term context", self.mid_term),
            ("Long-term context", self.long_term),
            ("Reflections", self.reflections),
        ]

        formatted_sections = []
        for title, items in sections:
            if not items:
                continue
            bullets = "\n".join(
                f"- ({entry.get('weight', 1.0):.2f}) {entry['content']}" for entry in items
            )
            formatted_sections.append(f"{title}:\n{bullets}")

        signals_lines = "\n".join(f"- {name}: {value}" for name, value in signals.items())

        context_block = "\n\n".join(formatted_sections) if formatted_sections else "No stored context."

        price_line = f"Latest price: {price}" if price is not None else "Price unavailable."

        prompt = (
            f"Date: {date}\n{price_line}\n\n"
            f"Strategy signals:\n{signals_lines or 'None'}\n\n"
            f"Context:\n{context_block}\n\n"
            "Decide whether to BUY, SELL, or take NONE action. "
            "Respond with a JSON object containing 'decision' and 'rationale'."
        )
        return prompt

    def _run_llm(self, prompt: str) -> Any:
        executor = self.llm_executor
        if executor is None:
            return None
        if callable(executor):
            return executor(prompt)
        run_method = getattr(executor, "run", None)
        if callable(run_method):
            return run_method(prompt)
        raise TypeError("llm_executor must be callable or expose a run(prompt) method")

    def _parse_llm_output(self, output: Any, signals: Dict[str, str]) -> Tuple[str, str]:
        decision = "NONE"
        rationale = "LLM output unavailable."

        if isinstance(output, dict):
            decision = str(output.get("decision", "NONE")).upper()
            rationale = str(output.get("rationale", output.get("reason", "")))
        elif output is not None:
            text = str(output)
            upper_text = text.upper()
            if "SELL" in upper_text and "BUY" not in upper_text:
                decision = "SELL"
            elif "BUY" in upper_text and "SELL" not in upper_text:
                decision = "BUY"
            elif "NONE" in upper_text or "HOLD" in upper_text:
                decision = "NONE"
            rationale = text

        if decision not in {"BUY", "SELL", "NONE"}:
            decision = "NONE"

        if not rationale:
            rationale = "LLM did not provide rationale."

        if decision == "NONE" and (not signals or all(v == "NONE" for v in signals.values())):
            rationale += " Strategies reported no actionable signals."
        elif decision == "NONE":
            rationale += " Falling back to neutral position."

        return decision, rationale

    # ------------------------------------------------------------------
    # Helpers: misc utilities
    # ------------------------------------------------------------------
    def _pull_trade_feedback(self) -> Optional[float]:
        if not self.trade_logger:
            return None

        for attr in ("get_recent_performance", "get_latest_profit", "get_last_pl"):
            hook = getattr(self.trade_logger, attr, None)
            if callable(hook):
                try:
                    return hook()
                except TypeError:
                    continue
        return None

    @staticmethod
    def _ensure_iterable(value: Optional[Iterable[str]]) -> List[str]:
        if value is None:
            return []
        if isinstance(value, (str, bytes)):
            return [value]
        return [str(v) for v in value if v is not None]

