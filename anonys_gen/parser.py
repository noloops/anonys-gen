# ANONYS FINITE STATE MACHINE FRAMEWORK
# Copyright (c) 2026 Jan Hofmann <anonys@noloops.ch>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://apache.org

"""Parser for FSM definition files (.txt)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Declaration:
    """A declared type (event or terminal object)."""
    kind: str              # "struct" or "class"
    namespace_path: str    # e.g. "events.PowerOn" or "signals.alert.Emergency"
    element_name: str      # e.g. "powerOn" or "emergency"

    @property
    def cpp_qualified(self) -> str:
        """Full C++ qualified name, e.g. 'signals::alert::Emergency'."""
        return self.namespace_path.replace(".", "::")

    @property
    def cpp_namespace(self) -> str:
        """C++ namespace only (empty string if no namespace)."""
        parts = self.namespace_path.split(".")
        if len(parts) <= 1:
            return ""
        return "::".join(parts[:-1])

    @property
    def cpp_type_name(self) -> str:
        """Unqualified type name, e.g. 'Emergency'."""
        return self.namespace_path.split(".")[-1]

    @property
    def ptr_name(self) -> str:
        """Pointer member name in Terminals struct, e.g. 'pEmergency'."""
        return "p" + self.cpp_type_name


@dataclass
class State:
    """A parsed state definition."""
    name: str
    is_initial: bool = False
    has_enter: bool = False
    has_exit: bool = False
    num_timeouts: int = 0
    events: list[str] = field(default_factory=list)        # element names of handled events
    referenced: list[str] = field(default_factory=list)     # element names of referenced terminals (type-1)
    published: list[str] = field(default_factory=list)      # element names of published terminals (type-2)
    children: list[State] = field(default_factory=list)
    parent: State | None = field(default=None, repr=False)
    depth: int = 0  # nesting depth (0 = top-level)


@dataclass
class FsmDefinition:
    """Complete parsed FSM definition."""
    name: str                                    # FSM name from file name
    declarations: list[Declaration] = field(default_factory=list)
    states: list[State] = field(default_factory=list)  # top-level states only

    def all_states_flat(self) -> list[State]:
        """Return all states in definition order (depth-first)."""
        result: list[State] = []
        def _walk(states: list[State]) -> None:
            for s in states:
                result.append(s)
                _walk(s.children)
        _walk(self.states)
        return result

    def get_declaration(self, element_name: str) -> Declaration:
        """Look up a declaration by element name."""
        for d in self.declarations:
            if d.element_name == element_name:
                return d
        raise KeyError(f"No declaration found for element name '{element_name}'")

    def get_events(self) -> list[Declaration]:
        """Return declarations that are used as events (appear in any state's events list)."""
        event_names: set[str] = set()
        for s in self.all_states_flat():
            event_names.update(s.events)
        return [d for d in self.declarations if d.element_name in event_names]

    def get_terminals(self) -> list[Declaration]:
        """Return declarations that are used as terminals (appear in referenced or published)."""
        terminal_names: set[str] = set()
        for s in self.all_states_flat():
            terminal_names.update(s.referenced)
            terminal_names.update(s.published)
        return [d for d in self.declarations if d.element_name in terminal_names]

    def get_external_terminals(self) -> list[Declaration]:
        """Return terminal declarations that are only ever referenced, never published.
        These become parameters of the initialize function."""
        published_names: set[str] = set()
        referenced_names: set[str] = set()
        for s in self.all_states_flat():
            published_names.update(s.published)
            referenced_names.update(s.referenced)
        # External = referenced somewhere but never published anywhere
        external_names = referenced_names - published_names
        return [d for d in self.declarations if d.element_name in external_names]

    def get_published_terminals(self) -> list[Declaration]:
        """Return terminal declarations that are published by some state."""
        published_names: set[str] = set()
        for s in self.all_states_flat():
            published_names.update(s.published)
        return [d for d in self.declarations if d.element_name in published_names]


def _validate_whitespace(raw_line: str, line_num: int, filepath: Path, is_state_line: bool) -> None:
    """Validate whitespace rules for a definition line.
    - State lines: only tabs allowed at beginning (for indentation), no tabs elsewhere
    - Declaration lines: no leading whitespace, no tabs anywhere
    """
    if is_state_line:
        # Count leading tabs, then check no spaces in leading whitespace
        i = 0
        while i < len(raw_line) and raw_line[i] == '\t':
            i += 1
        leading = raw_line[:i]
        if i < len(raw_line) and raw_line[i] == ' ' and not raw_line[:i+1].strip():
            # Space in leading whitespace area (before any non-whitespace)
            leading_ws = ""
            for ch in raw_line:
                if ch in ' \t':
                    leading_ws += ch
                else:
                    break
            if ' ' in leading_ws:
                raise ValueError(
                    f"{filepath.name}:{line_num}: spaces not allowed for indentation "
                    f"in state definition lines (use tabs only)"
                )
        # Check no tabs after the leading indentation
        rest = raw_line[i:]
        if '\t' in rest:
            raise ValueError(
                f"{filepath.name}:{line_num}: tabs not allowed except for indentation "
                f"at the beginning of state definition lines"
            )
    else:
        # Declaration lines: no leading whitespace allowed
        if raw_line and raw_line[0] in ' \t':
            raise ValueError(
                f"{filepath.name}:{line_num}: declaration lines must not have "
                f"leading whitespace"
            )
        # No tabs allowed at all
        if '\t' in raw_line:
            raise ValueError(
                f"{filepath.name}:{line_num}: tabs not allowed in declaration lines "
                f"(use spaces for separation)"
            )


def _parse_state_line(line: str) -> State:
    """Parse a single state definition line (without leading tabs).

    Tolerant of whitespace variations around !, +, -, digits, ( and ).
    All of these are equivalent:
      !Idle +-1 start (floorTracker speedRegulator) display panel
      ! Idle + - 1 start(floorTracker speedRegulator) display panel
      !Idle +- 1 start (floorTracker speedRegulator )display panel
    """
    rest = line.strip()

    # Initial state prefix — may have space after !
    is_initial = rest.startswith("!")
    if is_initial:
        rest = rest[1:].lstrip()

    # Normalize: ensure spaces around ( and ) so tokenization works
    rest = rest.replace("(", " ( ").replace(")", " ) ")
    tokens = rest.split()

    if not tokens:
        raise ValueError(f"Empty state definition line")

    # State name is always first
    name = tokens[0]
    tokens = tokens[1:]

    # Parse flags: consume tokens that are made of +, -, and digits only
    has_enter = False
    has_exit = False
    num_timeouts = 0
    flag_chars: list[str] = []

    while tokens:
        t = tokens[0]
        # A flag token is composed entirely of +, -, and digits
        if all(ch in "+-0123456789" for ch in t) and t[0] in "+-":
            flag_chars.extend(t)
            tokens = tokens[1:]
        # Also handle a standalone digit right after flag tokens
        elif t.isdigit() and flag_chars and not any(ch.isdigit() for ch in flag_chars):
            flag_chars.extend(t)
            tokens = tokens[1:]
        else:
            break

    for ch in flag_chars:
        if ch == "+":
            has_enter = True
        elif ch == "-":
            has_exit = True
        elif ch.isdigit():
            num_timeouts = int(ch)

    # Now tokens contain: events... ( referenced... ) published...
    events: list[str] = []
    referenced: list[str] = []
    published: list[str] = []

    if "(" in tokens:
        paren_open = tokens.index("(")
        events = tokens[:paren_open]
        rest_tokens = tokens[paren_open + 1:]
        if ")" in rest_tokens:
            paren_close = rest_tokens.index(")")
            referenced = rest_tokens[:paren_close]
            published = rest_tokens[paren_close + 1:]
        else:
            referenced = rest_tokens
    else:
        events = tokens

    return State(
        name=name,
        is_initial=is_initial,
        has_enter=has_enter,
        has_exit=has_exit,
        num_timeouts=num_timeouts,
        events=events,
        referenced=referenced,
        published=published,
    )


def parse_definition(filepath: Path) -> FsmDefinition:
    """Parse an FSM definition file and return the structured definition."""
    fsm_name = filepath.stem
    lines = filepath.read_text(encoding="utf-8").splitlines()

    declarations: list[Declaration] = []
    state_lines: list[tuple[int, str]] = []  # (indent_level, line)

    for line_num_0, raw_line in enumerate(lines):
        line_num = line_num_0 + 1

        # Comment footer: stop parsing at first line starting with #
        if raw_line.startswith("#"):
            break

        stripped = raw_line.strip()
        if not stripped:
            continue

        if stripped.startswith("struct ") or stripped.startswith("class "):
            _validate_whitespace(raw_line, line_num, filepath, is_state_line=False)
            parts = stripped.split()
            kind = parts[0]
            namespace_path = parts[1]
            element_name = parts[2]
            declarations.append(Declaration(kind, namespace_path, element_name))
        else:
            _validate_whitespace(raw_line, line_num, filepath, is_state_line=True)
            # Count leading tabs for indent
            indent = 0
            for ch in raw_line:
                if ch == "\t":
                    indent += 1
                else:
                    break
            state_lines.append((indent, stripped))

    # Validate element name uniqueness
    seen_names: dict[str, str] = {}  # element_name -> namespace_path
    for decl in declarations:
        if decl.element_name in seen_names:
            raise ValueError(
                f"{filepath.name}: duplicate element name '{decl.element_name}' "
                f"(used by both '{seen_names[decl.element_name]}' and '{decl.namespace_path}')"
            )
        seen_names[decl.element_name] = decl.namespace_path

    # Build state tree
    top_level_states: list[State] = []
    stack: list[tuple[int, State]] = []

    for indent, line in state_lines:
        state = _parse_state_line(line)
        state.depth = indent

        # Find parent: pop stack until we find a state at indent - 1
        while stack and stack[-1][0] >= indent:
            stack.pop()

        if stack:
            parent = stack[-1][1]
            state.parent = parent
            parent.children.append(state)
        else:
            top_level_states.append(state)

        stack.append((indent, state))

    # Validate state name uniqueness within this FSM
    seen_states: set[str] = set()
    for s in _walk_states(top_level_states):
        if s.name in seen_states:
            raise ValueError(
                f"{filepath.name}: duplicate state name '{s.name}'"
            )
        seen_states.add(s.name)

    return FsmDefinition(
        name=fsm_name,
        declarations=declarations,
        states=top_level_states,
    )


def _walk_states(states: list[State]):
    for s in states:
        yield s
        yield from _walk_states(s.children)
