from __future__ import annotations

from typing import Optional
import re
import sys


class AgentRunner:
    def __init__(self, args: object, extract_agent_text, print_progress) -> None:
        self._args = args
        self._extract_agent_text = extract_agent_text
        self._print_progress = print_progress
        self._summary_only_labels = {
            "Writer Draft",
            "Writer Draft (retry)",
            "Writer Finalizer",
            "Writer Finalizer (retry)",
            "Structural Repair",
            "Structural Repair (final)",
        }

    def _coerce_stream_text(self, value: object) -> str:
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            parts = []
            for item in value:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    text = item.get("text") or item.get("content") or item.get("value")
                    if text:
                        parts.append(str(text))
            return "".join(parts)
        return ""

    def _unpack_stream_chunk(self, chunk: object) -> tuple[Optional[str], object]:
        if isinstance(chunk, tuple):
            if len(chunk) == 2:
                return chunk[0], chunk[1]
            if len(chunk) >= 3:
                return chunk[1], chunk[2]
        return None, None

    def _sanitize_console_text(self, text: str) -> str:
        if not text:
            return text
        output_format = getattr(self._args, "output_format", "")
        if output_format != "html":
            return text
        cleaned = re.sub(r"(?is)<br\s*/?>", "\n", text)
        cleaned = re.sub(r"(?is)</(p|div|section|article|h[1-6])>", "\n\n", cleaned)
        cleaned = re.sub(r"(?is)<[^>]+>", "", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned

    def run(self, label: str, agent, payload: dict, show_progress: bool = True) -> str:
        args = self._args
        if not args.stream or label in self._summary_only_labels:
            result = agent.invoke(payload)
            text = self._extract_agent_text(result)
            if show_progress:
                self._print_progress(label, self._sanitize_console_text(text), args.progress, args.progress_chars)
            return text
        print(f"\n[{label}]\n", end="", flush=True)
        final_state = None
        streamed_parts: list[str] = []
        printed_any = False
        message_events = 0
        value_events = 0
        debug_samples = 0
        try:
            for chunk in agent.stream(payload, stream_mode=["messages", "values"], subgraphs=True):
                mode, data = self._unpack_stream_chunk(chunk)
                if mode == "messages":
                    message_events += 1
                    if isinstance(data, tuple) and data:
                        message = data[0]
                    else:
                        message = data
                    msg_type = getattr(message, "type", None) or getattr(message, "role", None)
                    msg_type_label = str(msg_type).lower() if msg_type is not None else ""
                    if args.stream_debug and debug_samples < 3:
                        debug_samples += 1
                        print(
                            f"[stream-debug] {label}: mode=messages type={msg_type_label}",
                            file=sys.stderr,
                        )
                    if msg_type_label and msg_type_label not in ("ai", "assistant") and not msg_type_label.startswith("ai"):
                        continue
                    content = getattr(message, "content", None)
                    text = self._coerce_stream_text(content)
                    if text:
                        streamed_parts.append(text)
                        printed_any = True
                        sys.stdout.write(self._sanitize_console_text(text))
                        sys.stdout.flush()
                elif mode == "values":
                    value_events += 1
                    final_state = data
        except Exception as exc:
            print(f"\n[warn] streaming failed for {label}: {exc}", file=sys.stderr)
            result = agent.invoke(payload)
            text = self._extract_agent_text(result)
            if show_progress:
                self._print_progress(label, text, args.progress, args.progress_chars)
            return text
        if args.stream_debug:
            print(
                f"[stream-debug] {label}: messages={message_events} values={value_events} printed={printed_any}",
                file=sys.stderr,
            )
        if not printed_any and final_state is not None:
            fallback_text = self._extract_agent_text(final_state).strip()
            if fallback_text:
                sys.stdout.write(self._sanitize_console_text(fallback_text))
                sys.stdout.flush()
        print("\n")
        if final_state is not None:
            return self._extract_agent_text(final_state)
        return "".join(streamed_parts).strip()
