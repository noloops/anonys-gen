# ANONYS FINITE STATE MACHINE FRAMEWORK
# Copyright (c) 2026 Jan Hofmann <anonys@noloops.ch>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://apache.org

"""Code generator for Anonys C++ FSM framework."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .parser import Declaration, FsmDefinition, State

# C++ indentation: 4 spaces per level
_I1 = "    "
_I2 = _I1 * 2
_I3 = _I1 * 3


@dataclass
class GeneratorConfig:
    """Configuration for a code generation run."""
    fsm_definitions: list[Path]
    anonys_output_dir: Path
    fsm_output_dir: Path
    include_guard_prefix: str


def generate(config: GeneratorConfig) -> None:
    """Run the complete code generation."""
    from .parser import parse_definition

    fsm_defs: list[FsmDefinition] = []
    for path in config.fsm_definitions:
        fsm_defs.append(parse_definition(path))

    # Validate FSM name uniqueness
    seen_fsm: set[str] = set()
    for fsm_def in fsm_defs:
        if fsm_def.name in seen_fsm:
            raise ValueError(f"Duplicate FSM name '{fsm_def.name}'")
        seen_fsm.add(fsm_def.name)

    anonys_dir = config.anonys_output_dir / "anonys"
    fsm_header_dir = anonys_dir / "fsm"
    impl_dir = anonys_dir / "impl"
    fsm_cpp_dir = config.fsm_output_dir

    for d in [anonys_dir, fsm_header_dir, impl_dir, fsm_cpp_dir]:
        d.mkdir(parents=True, exist_ok=True)

    all_events = _collect_unique_events(fsm_defs)
    max_timeouts = _max_timeouts(fsm_defs)
    guard = config.include_guard_prefix

    _write_event_id_h(anonys_dir / "EventId.h", guard, all_events, max_timeouts)
    _write_fsm_id_h(anonys_dir / "FsmId.h", guard, fsm_defs)
    _write_generated_config_h(anonys_dir / "GeneratedConfig.h", guard)
    _write_fsm_pool_h(anonys_dir / "FsmPool.h", guard, fsm_defs)
    _write_fsm_pool_cpp(anonys_dir / "FsmPool.cpp", fsm_defs)

    for fsm_idx, fsm_def in enumerate(fsm_defs):
        _write_terminals_h(impl_dir / f"terminals{fsm_def.name}.h", guard, fsm_idx, fsm_def)
        _write_handlers_h(impl_dir / f"handlers{fsm_def.name}.h", guard, fsm_idx, fsm_def)
        _write_fsm_struct_h(fsm_header_dir / f"{fsm_def.name}.h", guard, fsm_idx, fsm_def)
        _generate_state_cpps(fsm_cpp_dir, fsm_idx, fsm_def)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _collect_unique_events(fsm_defs: list[FsmDefinition]) -> list[Declaration]:
    seen: set[str] = set()
    result: list[Declaration] = []
    for fsm_def in fsm_defs:
        for decl in fsm_def.get_events():
            if decl.namespace_path not in seen:
                seen.add(decl.namespace_path)
                result.append(decl)
    return result


def _max_timeouts(fsm_defs: list[FsmDefinition]) -> int:
    m = 0
    for fsm_def in fsm_defs:
        for s in fsm_def.all_states_flat():
            m = max(m, s.num_timeouts)
    return m


def _state_id_map(fsm_def: FsmDefinition) -> dict[str, int]:
    flat = fsm_def.all_states_flat()
    return {s.name: i + 1 for i, s in enumerate(flat)}


def _ns(fsm_idx: int, state_id: int) -> str:
    return f"anonys_{fsm_idx}_{state_id}"


def _fsm_ns(fsm_idx: int) -> str:
    return f"anonys_{fsm_idx}"


def _write_forward_decls(lines: list[str], decls: list[Declaration]) -> None:
    """Write forward declarations grouped by namespace, multi-line format."""
    ns_groups: dict[str, list[Declaration]] = {}
    for d in decls:
        ns = d.cpp_namespace
        ns_groups.setdefault(ns, []).append(d)

    for ns, group in ns_groups.items():
        if not ns:
            for d in group:
                lines.append(f"{d.kind} {d.cpp_type_name};")
        else:
            lines.append(f"namespace {ns} {{")
            for d in group:
                lines.append(f"{_I1}{d.kind} {d.cpp_type_name};")
            lines.append("}")
    lines.append("")


# ---------------------------------------------------------------------------
# EventId.h
# ---------------------------------------------------------------------------

def _write_event_id_h(path: Path, guard_prefix: str, events: list[Declaration], max_timeouts: int) -> None:
    guard = f"{guard_prefix}_ANONYS_EVENTID_H"
    lines: list[str] = []
    lines.append("// ANONYS - Generated file, do not edit!")
    lines.append(f"#ifndef {guard}")
    lines.append(f"#define {guard}")
    lines.append("")
    lines.append('#include "anonys/Types.h"')
    lines.append("")

    _write_forward_decls(lines, events)

    lines.append("namespace anonys")
    lines.append("{")

    num_timeout_classes = max(max_timeouts, 4)
    for i in range(1, num_timeout_classes + 1):
        lines.append(f"{_I1}class Timeout{i} {{}};")
    lines.append("")

    lines.append(f"{_I1}template <typename T> constexpr EventId getEventId() = delete;")
    for i, ev in enumerate(events):
        lines.append(f"{_I1}template<> constexpr EventId getEventId<{ev.cpp_qualified}>() {{ return {i}; }}")
    lines.append("")

    lines.append(f"{_I1}template <typename T> constexpr EventId getTimeoutEventId() = delete;")
    for i in range(1, num_timeout_classes + 1):
        lines.append(f"{_I1}template<> constexpr EventId getTimeoutEventId<Timeout{i}>() {{ return {60000 + i}; }}")
    lines.append(f"{_I1}static_assert(getTimeoutEventId<Timeout1>().id == MinTimoutEventId.id);")

    lines.append("}")
    lines.append("")
    lines.append(f"#endif // {guard}")
    lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# FsmId.h
# ---------------------------------------------------------------------------

def _write_fsm_id_h(path: Path, guard_prefix: str, fsm_defs: list[FsmDefinition]) -> None:
    guard = f"{guard_prefix}_ANONYSFSMID_H"
    lines: list[str] = []
    lines.append("// ANONYS - Generated file, do not edit!")
    lines.append(f"#ifndef {guard}")
    lines.append(f"#define {guard}")
    lines.append("")
    lines.append("#include <cstdint>")
    lines.append("")
    lines.append("namespace anonys")
    lines.append("{")
    lines.append(f"{_I1}enum class FsmId : uint16_t {{")
    for i, fsm_def in enumerate(fsm_defs):
        lines.append(f"{_I2}{fsm_def.name} = {i},")
    lines.append(f"{_I2}Count_ = {len(fsm_defs)}")
    lines.append(f"{_I1}}};")
    lines.append("}")
    lines.append("")
    lines.append(f"#endif // {guard}")
    lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# GeneratedConfig.h
# ---------------------------------------------------------------------------

def _write_generated_config_h(path: Path, guard_prefix: str) -> None:
    guard = f"{guard_prefix}_ANONYS_GENERATEDCONFIG_H"
    lines: list[str] = []
    lines.append("// ANONYS - Generated file, do not edit!")
    lines.append(f"#ifndef {guard}")
    lines.append(f"#define {guard}")
    lines.append("")
    lines.append("#include <cstdint>")
    lines.append("")
    lines.append("namespace anonys")
    lines.append("{")
    lines.append(f"{_I1}constexpr int32_t MaxNestedStates{{ 8 }};")
    lines.append("}")
    lines.append("")
    lines.append(f"#endif // {guard}")
    lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# terminals*.h
# ---------------------------------------------------------------------------

def _write_terminals_h(path: Path, guard_prefix: str, fsm_idx: int, fsm_def: FsmDefinition) -> None:
    guard = f"{guard_prefix}_ANONYS_TERMINALS_{fsm_def.name.upper()}_H"
    ns = _fsm_ns(fsm_idx)
    terminals = fsm_def.get_terminals()

    lines: list[str] = []
    lines.append("// ANONYS - Generated file, do not edit!")
    lines.append(f"#ifndef {guard}")
    lines.append(f"#define {guard}")
    lines.append("")
    lines.append('#include "anonys/Timer.h"')
    lines.append("")

    _write_forward_decls(lines, terminals)

    lines.append(f"namespace {ns} {{")
    lines.append(f"{_I1}struct Terminals {{")
    lines.append(f"{_I2}anonys::TimerCore* pTimer;")
    for t in terminals:
        lines.append(f"{_I2}{t.cpp_qualified}* {t.ptr_name};")
    lines.append(f"{_I1}}};")
    lines.append("}")
    lines.append("")
    lines.append(f"#endif // {guard}")
    lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# handlers*.h
# ---------------------------------------------------------------------------

def _write_handlers_h(path: Path, guard_prefix: str, fsm_idx: int, fsm_def: FsmDefinition) -> None:
    guard = f"{guard_prefix}_ANONYS_HANDLERS_{fsm_def.name.upper()}_H"
    flat = fsm_def.all_states_flat()
    id_map = _state_id_map(fsm_def)

    lines: list[str] = []
    lines.append("// ANONYS - Generated file, do not edit!")
    lines.append(f"#ifndef {guard}")
    lines.append(f"#define {guard}")
    lines.append("")
    lines.append('#include "anonys/Types.h"')
    lines.append('#include "anonys/Utils.h"')
    lines.append("")
    lines.append(f'#include "terminals{fsm_def.name}.h"')

    for state in flat:
        sid = id_map[state.name]
        ns_name = _ns(fsm_idx, sid)
        lines.append("")
        lines.append(f"namespace {ns_name} {{")
        lines.append(f"{_I1}uint16_t getMembersSize();")
        lines.append(f"{_I1}void liveCycle(bool create, void* pTerminals, void* pMembers);")
        lines.append(f"{_I1}const anonys::StateDef* handleEvent(void* pMembers, anonys::Event& event);")
        lines.append("}")

    lines.append("")
    lines.append(f"#endif // {guard}")
    lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# fsm/FsmName.h (StateDef struct)
# ---------------------------------------------------------------------------

def _write_fsm_struct_h(path: Path, guard_prefix: str, fsm_idx: int, fsm_def: FsmDefinition) -> None:
    guard = f"{guard_prefix}_FSM_{fsm_def.name.upper()}_H"
    flat = fsm_def.all_states_flat()
    id_map = _state_id_map(fsm_def)

    lines: list[str] = []
    lines.append("// ANONYS - Generated file, do not edit!")
    lines.append(f"#ifndef {guard}")
    lines.append(f"#define {guard}")
    lines.append("")
    lines.append(f'#include "anonys/impl/handlers{fsm_def.name}.h"')
    lines.append('#include "anonys/EventId.h"')
    lines.append('#include "anonys/FsmId.h"')
    lines.append("")
    lines.append("namespace anonys::fsm {")
    lines.append(f"{_I1}struct {fsm_def.name} {{")
    lines.append(f"{_I2}static constexpr anonys::FsmId Id{{ anonys::FsmId::{fsm_def.name} }};")

    for state in flat:
        sid = id_map[state.name]
        ns_name = _ns(fsm_idx, sid)
        if state.parent is None:
            parent_ref = "nullptr"
        else:
            parent_ref = f"&{state.parent.name}"
        lines.append(
            f"{_I2}static constexpr anonys::StateDef {state.name} = "
            f"{{ {sid}, anonys::FsmId::{fsm_def.name}, {parent_ref}, "
            f"{ns_name}::getMembersSize, {ns_name}::liveCycle, {ns_name}::handleEvent }};"
        )

    lines.append(f"{_I1}}};")
    lines.append("}")
    lines.append("")
    lines.append(f"#endif // {guard}")
    lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# FsmPool.h
# ---------------------------------------------------------------------------

def _write_fsm_pool_h(path: Path, guard_prefix: str, fsm_defs: list[FsmDefinition]) -> None:
    guard = f"{guard_prefix}_FSM_H"
    lines: list[str] = []
    lines.append("// ANONYS - Generated file, do not edit!")
    lines.append(f"#ifndef {guard}")
    lines.append(f"#define {guard}")
    lines.append("")
    lines.append("#include <type_traits>")
    lines.append("")
    lines.append('#include "anonys/FsmCore.h"')
    lines.append("")

    for i, fsm_def in enumerate(fsm_defs):
        lines.append(f'#include "impl/terminals{fsm_def.name}.h"')

    lines.append("")
    lines.append("namespace anonys")
    lines.append("{")
    lines.append(f"{_I1}class FsmPool {{")
    lines.append(f"{_I1}public:")
    lines.append(f"{_I2}static constexpr uint16_t Count{{ static_cast<uint16_t>(FsmId::Count_)}};")

    for i, fsm_def in enumerate(fsm_defs):
        lines.append(f"{_I2}using Terminals{fsm_def.name} = {_fsm_ns(i)}::Terminals;")

    lines.append("")
    lines.append(f"{_I2}void handleEvent(FsmId fsmId, Event& event);")
    lines.append("")
    lines.append(f"{_I2}void handleTimeoutEvent(FsmId fsmId, int16_t depth, EventId eventId);")
    lines.append("")
    lines.append(f"{_I2}void setTracingService(TracingService* pTracingService = nullptr);")
    lines.append("")
    lines.append(f"{_I2}void setTracingService(FsmId fsmId, TracingService* pTracingService = nullptr);")

    for i, fsm_def in enumerate(fsm_defs):
        params = _get_initialize_params(fsm_def)
        lines.append("")
        lines.append(f"{_I2}void initialize{fsm_def.name}({params});")

    lines.append("")
    lines.append(f"{_I2}void start();")
    lines.append("")
    lines.append(f"{_I1}private:")
    lines.append(f"{_I2}FsmCore m_fsm[Count]{{}};")
    lines.append("")

    for fsm_def in fsm_defs:
        lines.append(f"{_I2}std::aligned_storage_t<BufferSize::{fsm_def.name}, anonys::StdAlign> m_buffer{fsm_def.name}{{}};")

    lines.append("")
    for i, fsm_def in enumerate(fsm_defs):
        lines.append(f"{_I2}Terminals{fsm_def.name} m_terminals{fsm_def.name}{{}};")

    lines.append("")
    lines.append(f"{_I2}bool m_started{{ false }};")
    lines.append(f"{_I1}}};")
    lines.append("}")
    lines.append(f"#endif // {guard}")
    lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def _get_initialize_params(fsm_def: FsmDefinition) -> str:
    params = ["TimerService& timerService"]
    for ext in fsm_def.get_external_terminals():
        params.append(f"{ext.cpp_qualified}& {ext.element_name}")
    return ", ".join(params)


# ---------------------------------------------------------------------------
# FsmPool.cpp
# ---------------------------------------------------------------------------

def _write_fsm_pool_cpp(path: Path, fsm_defs: list[FsmDefinition]) -> None:
    lines: list[str] = []
    lines.append("// ANONYS - Generated file, do not edit!")
    lines.append('#include "FsmPool.h"')
    lines.append('#include "anonys/Utils.h"')
    lines.append("")

    for fsm_def in fsm_defs:
        lines.append(f'#include "fsm/{fsm_def.name}.h"')

    lines.append("")
    lines.append("namespace anonys")
    lines.append("{")

    for fsm_def in fsm_defs:
        lines.append(f'{_I1}static_assert(BufferSize::{fsm_def.name} % anonys::StdAlign == 0, "Buffer size must be a multiple of alignment");')

    lines.append("")

    lines.append(f"{_I1}void FsmPool::handleEvent(FsmId fsmId, Event& event) {{")
    lines.append(f"{_I2}if (fsmId < FsmId::Count_) {{")
    lines.append(f"{_I3}m_fsm[static_cast<uint16_t>(fsmId)].handleEvent(event);")
    lines.append(f"{_I2}}}")
    lines.append(f"{_I1}}}")
    lines.append("")

    lines.append(f"{_I1}void FsmPool::handleTimeoutEvent(FsmId fsmId, int16_t depth, EventId eventId) {{")
    lines.append(f"{_I2}if (fsmId < FsmId::Count_) {{")
    lines.append(f"{_I3}m_fsm[static_cast<uint16_t>(fsmId)].handleTimeoutEvent(depth, eventId);")
    lines.append(f"{_I2}}}")
    lines.append(f"{_I1}}}")
    lines.append("")

    lines.append(f"{_I1}void FsmPool::setTracingService(TracingService* pTracingService) {{")
    lines.append(f"{_I2}for (uint16_t fsmId{{0}}; fsmId < static_cast<uint16_t>(FsmId::Count_); ++fsmId) {{")
    lines.append(f"{_I3}m_fsm[fsmId].setTracingService(pTracingService);")
    lines.append(f"{_I2}}}")
    lines.append(f"{_I1}}}")
    lines.append("")

    lines.append(f"{_I1}void FsmPool::setTracingService(FsmId fsmId, TracingService* pTracingService) {{")
    lines.append(f"{_I2}if (fsmId < FsmId::Count_) {{")
    lines.append(f"{_I3}m_fsm[static_cast<uint16_t>(fsmId)].setTracingService(pTracingService);")
    lines.append(f"{_I2}}}")
    lines.append(f"{_I1}}}")

    for fsm_idx, fsm_def in enumerate(fsm_defs):
        lines.append("")
        params = _get_initialize_params(fsm_def)
        lines.append(f"{_I1}void FsmPool::initialize{fsm_def.name}({params}) {{")
        lines.append(f"{_I2}ANONYS_ASSERT(m_terminals{fsm_def.name}.pTimer == nullptr);")
        lines.append(f"{_I2}FsmCore& fsm{{ m_fsm[static_cast<uint16_t>(FsmId::{fsm_def.name})] }};")
        lines.append(f"{_I2}m_terminals{fsm_def.name}.pTimer = &(fsm.getTimerCore());")

        for ext in fsm_def.get_external_terminals():
            lines.append(f"{_I2}m_terminals{fsm_def.name}.{ext.ptr_name} = &{ext.element_name};")

        lines.append("")
        lines.append(f"{_I2}uint8_t* const pBuffer{{ std::launder(reinterpret_cast<uint8_t*>(&m_buffer{fsm_def.name})) }};")
        lines.append(f"{_I2}fsm.initialize(FsmId::{fsm_def.name}, &m_terminals{fsm_def.name}, pBuffer, sizeof(m_buffer{fsm_def.name}), &timerService);")
        lines.append(f"{_I1}}}")

    lines.append("")
    lines.append(f"{_I1}void FsmPool::start() {{")
    lines.append(f"{_I2}ANONYS_ASSERT(!m_started);")
    lines.append(f"{_I2}m_started = true;")
    for fsm_idx, fsm_def in enumerate(fsm_defs):
        initial = _find_initial_state(fsm_def)
        lines.append(
            f"{_I2}m_fsm[static_cast<uint16_t>(FsmId::{fsm_def.name})].executeTransition(&fsm::{fsm_def.name}::{initial.name});"
        )
    lines.append(f"{_I1}}}")

    lines.append("}")
    lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def _find_initial_state(fsm_def: FsmDefinition) -> State:
    for s in fsm_def.all_states_flat():
        if s.is_initial:
            return s
    raise ValueError(f"No initial state found in FSM '{fsm_def.name}'")


# ---------------------------------------------------------------------------
# Per-state .cpp file generation
# ---------------------------------------------------------------------------

def _generate_state_cpps(fsm_cpp_dir: Path, fsm_idx: int, fsm_def: FsmDefinition) -> None:
    """Generate or update .cpp files for each state."""
    id_map = _state_id_map(fsm_def)

    for state in fsm_def.all_states_flat():
        state_id = id_map[state.name]
        cpp_path = _get_state_cpp_path(fsm_cpp_dir, fsm_def, state)
        cpp_path.parent.mkdir(parents=True, exist_ok=True)

        if cpp_path.exists():
            _update_state_cpp(cpp_path, fsm_idx, state_id, fsm_def, state)
        else:
            _create_state_cpp(cpp_path, fsm_idx, state_id, fsm_def, state)


def _get_state_cpp_path(fsm_cpp_dir: Path, fsm_def: FsmDefinition, state: State) -> Path:
    """Compute the file path for a state's .cpp file, reflecting the hierarchy."""
    # Build path segments from parent chain
    segments: list[str] = []
    current = state
    while current.parent is not None:
        segments.append(current.parent.name)
        current = current.parent

    segments.reverse()
    path = fsm_cpp_dir / fsm_def.name
    for seg in segments:
        path = path / seg
    path = path / f"{state.name}.cpp"
    return path


def _create_state_cpp(path: Path, fsm_idx: int, state_id: int, fsm_def: FsmDefinition, state: State) -> None:
    lines: list[str] = []

    lines.append(f'#include "anonys/fsm/{fsm_def.name}.h"')
    lines.append("")

    lines.append("namespace {")
    lines.append(f"{_I1}using Fsm = anonys::fsm::{fsm_def.name};")

    for i in range(1, state.num_timeouts + 1):
        letter = chr(ord("A") + i - 1)
        lines.append(f"{_I1}using Timeout{letter} = anonys::Timeout{i};")

    lines.append("")

    lines.append(f"{_I1}struct Me {{")
    me_members = _get_me_members(fsm_def, state)
    for member in me_members:
        lines.append(f"{_I2}{member};")
    lines.append(f"{_I1}}};")

    if state.has_enter:
        lines.append("")
        lines.append(f"{_I1}void enter(Me& me) {{")
        lines.append(f"{_I1}}}")

    if state.has_exit:
        lines.append("")
        lines.append(f"{_I1}void exit(Me& me) {{")
        lines.append(f"{_I1}}}")

    for ev_name in state.events:
        decl = fsm_def.get_declaration(ev_name)
        lines.append("")
        lines.append(f"{_I1}anonys::State* handle(Me& me, {decl.cpp_qualified}& event) {{")
        lines.append(f"{_I2}return nullptr;")
        lines.append(f"{_I1}}}")

    for i in range(1, state.num_timeouts + 1):
        letter = chr(ord("A") + i - 1)
        lines.append("")
        lines.append(f"{_I1}anonys::State* handle(Me& me, Timeout{letter}& event) {{")
        lines.append(f"{_I2}return nullptr;")
        lines.append(f"{_I1}}}")

    lines.append("}")
    lines.append("")

    lines.append("// Generated code, do not edit:")
    lines.extend(_generate_state_section(fsm_idx, state_id, fsm_def, state))

    path.write_text("\n".join(lines), encoding="utf-8")


def _update_state_cpp(path: Path, fsm_idx: int, state_id: int, fsm_def: FsmDefinition, state: State) -> None:
    content = path.read_text(encoding="utf-8")
    marker = "// Generated code, do not edit:"
    idx = content.find(marker)
    if idx == -1:
        return

    user_section = content[:idx + len(marker)]
    gen_lines = _generate_state_section(fsm_idx, state_id, fsm_def, state)
    new_content = user_section + "\n" + "\n".join(gen_lines)

    path.write_text(new_content, encoding="utf-8")


def _generate_state_section(fsm_idx: int, state_id: int, fsm_def: FsmDefinition, state: State) -> list[str]:
    ns = _ns(fsm_idx, state_id)
    fsm_term_ns = _fsm_ns(fsm_idx)
    lines: list[str] = []

    lines.append(f"namespace {ns} {{")

    has_any_handler = bool(state.events) or state.num_timeouts > 0

    if not has_any_handler:
        lines.append(f"{_I1}anonys::State* handleEvent(void* pMembers, anonys::Event& event) {{")
        lines.append(f"{_I2}return &anonys::DummyStates::Unhandled;")
        lines.append(f"{_I1}}}")
    else:
        lines.append(f"{_I1}anonys::State* handleEvent(void* pMembers, anonys::Event& event) {{")
        lines.append(f"{_I2}Me& me{{ *static_cast<Me*>(pMembers) }};")
        lines.append(f"{_I2}switch (event.eventId.id) {{")

        for ev_name in state.events:
            decl = fsm_def.get_declaration(ev_name)
            lines.append(f"{_I2}case anonys::getEventId<{decl.cpp_qualified}>().id:")
            lines.append(f"{_I3}return handle(me, *static_cast<{decl.cpp_qualified}*>(event.pData));")

        for i in range(1, state.num_timeouts + 1):
            lines.append(f"{_I2}case anonys::getTimeoutEventId<anonys::Timeout{i}>().id:")
            lines.append(f"{_I3}return handle(me, *static_cast<anonys::Timeout{i}*>(event.pData));")

        lines.append(f"{_I2}default:")
        lines.append(f"{_I3}return &anonys::DummyStates::Unhandled;")
        lines.append(f"{_I2}}}")
        lines.append(f"{_I1}}}")

    lines.append("")

    lines.append(f"{_I1}void liveCycle(bool create, void* pTerminals, void* pMembers) {{")

    has_published = bool(state.published)

    is_halted = (not has_any_handler and not state.has_enter and not state.has_exit
                 and not has_published)

    if is_halted:
        lines.append(f"{_I2}if (create) {{")
        lines.append(f"{_I3}::new (pMembers) Me{{}};")
        lines.append(f"{_I2}}}")
        lines.append(f"{_I2}else {{")
        lines.append(f"{_I3}Me& me{{ *static_cast<Me*>(pMembers) }};")
        lines.append(f"{_I3}me.~Me();")
        lines.append(f"{_I2}}}")
    else:
        lines.append(f"{_I2}auto& terminals{{ *static_cast<{fsm_term_ns}::Terminals*>(pTerminals) }};")
        ctor_args = _get_ctor_args(fsm_def, state)
        me_init = f"Me{{ {ctor_args} }}" if ctor_args else "Me{}"

        lines.append(f"{_I2}if (create) {{")

        if state.has_enter or has_published:
            lines.append(f"{_I3}Me& me{{ *::new (pMembers) {me_init} }};")
        else:
            lines.append(f"{_I3}::new (pMembers) {me_init};")

        for pub_name in state.published:
            decl = fsm_def.get_declaration(pub_name)
            lines.append(f"{_I3}terminals.{decl.ptr_name} = &me.{pub_name};")

        if state.has_enter:
            lines.append(f"{_I3}enter(me);")

        lines.append(f"{_I2}}}")
        lines.append(f"{_I2}else {{")

        lines.append(f"{_I3}Me& me{{ *static_cast<Me*>(pMembers) }};")

        if state.has_exit:
            lines.append(f"{_I3}exit(me);")

        lines.append(f"{_I3}me.~Me();")

        for pub_name in state.published:
            decl = fsm_def.get_declaration(pub_name)
            lines.append(f"{_I3}terminals.{decl.ptr_name} = nullptr;")

        lines.append(f"{_I2}}}")

    lines.append(f"{_I1}}}")
    lines.append("")

    lines.append(f"{_I1}uint16_t getMembersSize() {{")
    lines.append(f"{_I2}return anonys::getAlignedSize<Me>();")
    lines.append(f"{_I1}}}")

    lines.append("}")
    lines.append("")

    return lines


def _get_me_members(fsm_def: FsmDefinition, state: State) -> list[str]:
    members: list[str] = []

    if _state_needs_timer(state):
        members.append("anonys::Timer timer")

    for ref_name in state.referenced:
        decl = fsm_def.get_declaration(ref_name)
        members.append(f"{decl.cpp_qualified}& {ref_name}")

    for pub_name in state.published:
        decl = fsm_def.get_declaration(pub_name)
        members.append(f"{decl.cpp_qualified} {pub_name}{{}}")

    return members


def _state_needs_timer(state: State) -> bool:
    return state.num_timeouts > 0


def _get_ctor_args(fsm_def: FsmDefinition, state: State) -> str:
    args: list[str] = []

    if _state_needs_timer(state):
        args.append("*terminals.pTimer")

    for ref_name in state.referenced:
        decl = fsm_def.get_declaration(ref_name)
        args.append(f"*terminals.{decl.ptr_name}")

    return ", ".join(args)
