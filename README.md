# anonys_gen

Code generator for the [Anonys](https://github.com/anonys) C++ finite state machine framework. It reads FSM definition files and generates all the C++ boilerplate needed by the Anonys runtime.

## Installation

Requires Python 3.10 or later.

This package is designed to be consumed as a git submodule. Installation is performed from the consuming project by pointing `pip` at the submodule directory:

```bash
pip install path/to/anonys_gen
```

The package must be installed before any generation script is run. This only needs to be done once, or again after updating the submodule.

The `-e` flag (editable mode) installs the package so that any changes to its source take effect immediately without reinstalling — useful when developing the generator itself:

```bash
pip install -e path/to/anonys_gen
```

## Usage

Generation is configured and triggered by a Python script in the consuming project, outside this package:

```python
from pathlib import Path
from anonys_gen.generator import GeneratorConfig, generate

config = GeneratorConfig(
    fsm_definitions=[
        Path("fsmDef/Elevator.txt"),
        Path("fsmDef/TrafficLight.txt"),
    ],
    anonys_output_dir=Path("src"),
    fsm_output_dir=Path("src/Fsm"),
    include_guard_prefix="MYPROJECT",
    header=Path("header.txt"),
    additional_fsm_ids=["RemoteFsm"],
)
generate(config)
```

The `header` and `additional_fsm_ids` parameters are optional and can be omitted. Errors during generation are reported as exceptions and should be caught by the calling script.

## Configuration

The following table lists the configuration possibilities:

| Parameter | Required | Description |
|---|---|---|
| `fsm_definitions` | yes | List of paths to FSM definition files (`.txt`). |
| `anonys_output_dir` | yes | Output directory for the generated `anonys/` headers and sources. |
| `fsm_output_dir` | yes | Output directory for the per-state `.cpp` files. |
| `include_guard_prefix` | yes | Prefix for `#ifndef` include guards (e.g. `"MYPROJECT"`). |
| `header` | no | Path to a text file whose content is prepended to every generated file (e.g. a license header). |
| `additional_fsm_ids` | no | Extra entries to add to the `FsmId` enum (for FSMs defined elsewhere). |

### Generated output

The output directories are fully configurable via `anonys_output_dir` and `fsm_output_dir`. The table below lists all generated files using `src` as `anonys_output_dir` and `Fsm` as `fsm_output_dir`:

| File | Content |
|---|---|
| `Fsm/<Name>/<State>.cpp` | Generated implementation file for all handlers of a single state. The user-editable section at the beginning of this file is written only once — it will not be overwritten on subsequent generator runs. Nested states are placed in subdirectories. |
| `src/anonys/EventId.h` | Maps each event type to a unique numeric identifier. Also defines the identifiers for timeout events. |
| `src/anonys/FsmId.h` | Contains an `enum class FsmId` with one enumerator per state machine. |
| `src/anonys/FsmPool.h` / `.cpp` | Generated wrapper class which manages the FsmCore-instances of all generated state machines. |
| `src/anonys/GeneratedConfig.h` | Contains runtime constants derived from the set of generated state machines. |
| `src/anonys/fsm/<Name>.h` | Contains all state definitions — used as return values to trigger state transitions — for a generated state machine. |
| `src/anonys/impl/handlers<Name>.h` | Contains implementation details for each state machine. |
| `src/anonys/impl/terminals<Name>.h` | Contains the Terminals struct for each state machine. A terminal is an object — such as a hardware driver or service — that states can interact with during their lifetime. |

## FSM Definition File Syntax

Each FSM is defined in a plain-text `.txt` file. The file name (without extension) becomes the FSM name (e.g. `Elevator.txt` → FSM **Elevator**). Blank lines are ignored. A line starting with `#` ends parsing (can be used for comments at the bottom).

A definition file has two sections: **declarations** at the top, followed by **state definitions**.

### Declarations

Each declaration is a single line with three space-separated tokens:

```
type namespace.path.TypeName elementName
```

| Token | Description |
|---|---|
| `type` | `struct` or `class` — determines whether event data is passed as `const&` or `&`. |
| `namespace.path.TypeName` | Dot-separated path that maps to a C++ qualified name. `events.PowerOn` becomes `events::PowerOn` in C++. |
| `elementName` | A camelCase identifier used to reference this declaration in state lines. Must start with a lowercase letter. |

Declarations define both **events** and **terminal objects**. The generator determines which is which based on how they are referenced in the state definitions.

**Rules:**
- No leading whitespace.
- No tabs (use spaces for separation).
- Element names must be unique across the file.

**Example:**

```
struct events.PowerOn powerOn
struct events.InsertCoin insertCoin
class events.ConfigureAutoPause configureAutoPause
struct terminals.Std std
class terminals.Counter counter
```

### State Definitions

Each state is defined on a single line. Tab indentation defines the parent–child hierarchy (one tab per nesting level).

```
[!]StateName [+][-][N] events... (referenced...) published...
```

| Element | Description |
|---|---|
| `!` | Marks the **initial state** (prefix before the name). |
| `StateName` | Name of the state, must be unique for the FSM. Must start with an uppercase letter. |
| `+` | State has an **enter** handler. |
| `-` | State has an **exit** handler. |
| `N` | Single digit — number of **timeouts** (0 if omitted). |
| `events...` | Space-separated list of handled event element names. Prefix `&` for mutable reference (passes the event's `class` data as non-const). |
| `(referenced...)` | Terminal objects **referenced** from this state (defined by a superstate or from outside the FSM). |
| `published...` | Terminal objects **published** by this state, can be referenced by its substates. |

The three lists are separated by parentheses `(` `)`. The parentheses are always present in practice, even when the referenced list is empty.

**Rules:**
- Only tabs for indentation (no spaces).
- State names must be unique within a file.
- The `+`, `-`, and digit must appear as a single token in that order (e.g. `+-1`, `+2`, `-`, `+`).

### Terminal object semantics

- **Referenced:** Terminal objects defined by a superstate or from outside the FSM. These appear between `(` and `)`. If a terminal is only ever referenced and never published, it becomes a parameter of the FSM's `initialize` function (an external dependency such as a hardware driver).
- **Published:** The state owns the terminal as a value and exposes it to descendant states. These appear after `)`.

### Complete example

Below is the definition for a Jukebox FSM (from the main [Anonys](https://github.com/anonys) repository):

```
struct events.PowerOn powerOn
struct events.PowerOff powerOff
struct events.InsertCoin insertCoin
struct events.Play play
struct events.Pause pause
struct events.Skip skip
struct events.Eject eject
struct events.Diagnostic diagnostic
struct events.Malfunction malfunction
struct events.Reset reset
struct events.AutoPause autoPause
class events.ConfigureAutoPause configureAutoPause
struct terminals.Std std
class terminals.Counter counter
class terminals.Mixer mixer
class terminals.Countdown countdown

!Off +- powerOn (std)
On +- powerOff malfunction (std)
	Idle +-1 insertCoin malfunction diagnostic (std)
	Playing +- eject autoPause (std) counter mixer
		Normal +-1 pause skip (std counter mixer)
		Paused +- play &configureAutoPause (std mixer) countdown
			AutoPause +-1 pause (std countdown)
Error +-1 reset (std)
```

**Reading the state lines:**

| Line | Meaning |
|---|---|
| `!Off +- powerOn (std)` | Initial state, enter + exit handlers, handles `powerOn`, references terminal `std` |
| `On +- powerOff malfunction (std)` | Enter + exit, handles `powerOff` and `malfunction`, references `std` |
| `⇥Idle +-1 insertCoin malfunction diagnostic (std)` | Child of `On`, enter + exit + 1 timeout, handles three events |
| `⇥Playing +- eject autoPause (std) counter mixer` | Child of `On`, references `std`, publishes `counter` and `mixer` |
| `⇥⇥Normal +-1 pause skip (std counter mixer)` | Child of `Playing`, references `std`, `counter`, and `mixer` |
| `⇥⇥Paused +- play &configureAutoPause (std mixer) countdown` | Handles `configureAutoPause` by mutable reference (`&`), publishes `countdown` |
| `⇥⇥⇥AutoPause +-1 pause (std countdown)` | Child of `Paused`, references `countdown` from parent |
| `Error +-1 reset (std)` | Top-level state, 1 timeout |

## Examples

The main [Anonys](https://github.com/anonys) repository contains complete working examples with FSM definitions, generation scripts, and the generated C++ code:

- **Example1** — single FSM (Jukebox)
- **Example2** — multiple FSMs (Elevator, TrafficLight, Washer) with external dependencies and `additional_fsm_ids`

## License

Apache License 2.0 — see [LICENSE](LICENSE).
