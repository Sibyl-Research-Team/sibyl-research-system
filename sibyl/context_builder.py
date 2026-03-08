"""Priority-based context builder for Sibyl agents.

Replaces hard `content[:3000]` truncation with intelligent priority-based
context management that allocates more tokens to higher-priority content.
"""
from dataclasses import dataclass, field


@dataclass
class ContextItem:
    """A piece of context with a priority level."""
    label: str
    content: str
    priority: int = 5  # 1 (lowest) to 10 (highest)
    max_tokens: int | None = None  # optional per-item cap


def estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token for English, ~2 for CJK."""
    return max(1, len(text) // 3)


def truncate_to_tokens(text: str, max_tokens: int) -> str:
    """Truncate text to approximately max_tokens."""
    max_chars = max_tokens * 3
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n... [truncated]"


class ContextBuilder:
    """Builds agent context from multiple sources with priority-based allocation.

    Usage:
        ctx = ContextBuilder(budget=8000)
        ctx.add("Proposal", proposal_text, priority=9)
        ctx.add("Results", results_text, priority=8)
        ctx.add("References", refs_text, priority=3)
        context_str = ctx.build()
    """

    def __init__(self, budget: int = 8000):
        """
        Args:
            budget: Total token budget for the context.
        """
        self.budget = budget
        self.items: list[ContextItem] = []

    def add(self, label: str, content: str, priority: int = 5,
            max_tokens: int | None = None) -> "ContextBuilder":
        """Add a context item. Returns self for chaining."""
        if content and content.strip():
            self.items.append(ContextItem(
                label=label, content=content.strip(),
                priority=priority, max_tokens=max_tokens,
            ))
        return self

    def build(self) -> str:
        """Build the final context string within budget."""
        if not self.items:
            return ""

        # Sort by priority descending
        sorted_items = sorted(self.items, key=lambda x: x.priority, reverse=True)

        # Calculate total tokens needed
        item_tokens = [(item, estimate_tokens(item.content)) for item in sorted_items]
        total_needed = sum(t for _, t in item_tokens)

        if total_needed <= self.budget:
            # Everything fits
            return self._format_items([(item, item.content) for item in sorted_items])

        # Allocate budget proportionally by priority
        total_priority = sum(item.priority for item in sorted_items) or len(sorted_items)
        remaining_budget = self.budget
        allocated: list[tuple[ContextItem, str]] = []

        for item, tokens in item_tokens:
            # Priority-weighted allocation
            share = int(self.budget * (item.priority / total_priority))
            # Apply per-item cap if set
            if item.max_tokens:
                share = min(share, item.max_tokens)
            # Don't exceed what's needed
            share = min(share, tokens)
            # Don't exceed remaining budget
            share = min(share, remaining_budget)

            if share > 0:
                truncated = truncate_to_tokens(item.content, share)
                allocated.append((item, truncated))
                remaining_budget -= share

            if remaining_budget <= 0:
                break

        return self._format_items(allocated)

    def _format_items(self, items: list[tuple[ContextItem, str]]) -> str:
        """Format context items into a single string."""
        parts = []
        for item, content in items:
            parts.append(f"## {item.label}\n{content}")
        return "\n\n".join(parts)
