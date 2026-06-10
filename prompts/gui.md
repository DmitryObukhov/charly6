# GUI Visualization Prompt

## Purpose

Define the Charly6 Tkinter GUI visualization behavior. GUI code may inspect
brain, body, world, and runtime history state, but must not change the public
brain, neuron, or world plugin APIs.

## Brain Map Neuron Rendering

Neurons are drawn as circles. Circle outline encodes neuron role; circle fill
encodes current state.

Outline rules, in priority order:

- Input neuron: blue outline.
- Output neuron: yellow outline.
- High absolute EQ neuron: green outline for positive EQ, red outline for
  negative EQ.
- Ordinary neuron: neutral gray outline.

High EQ detection is configurable through
`visualization.display.eq_outline_threshold_percent`. The value is a percent of
`brain.total_input`; for example `0.1` means highlight neurons where
`abs(neuron.eq) / total_input * 100 > 0.1`.

Fill rules:

- Passive neuron: dark gray fill.
- Active physical input neuron: bright blue fill.
- Active non-input neuron with non-negative EQ: green fill.
- Active non-input neuron with negative EQ: red fill.

Physical input activity is tracked separately from `neuron.active`, because the
simulation cycle may reset `neuron.active` after applying input signals. The
map should indicate active physical input indices from the latest body
translation.

Canvas neuron shapes must carry stable tags in the form `neuron:<index>` so
click selection works on the actual drawn item before falling back to geometric
nearest-neighbor hit testing.

## Activity Summary

The Activity Summary tab plots runtime history over the latest
`summary_depth` periods:

- active neuron count percent
- active input neuron count
- positive CES
- negative CES

The same series may be drawn as a Brain Map overlay when enabled. Overlay
layout must use the same plot margins as the tab view so time alignment remains
predictable.

## TES Spectrogram

TES is the signed total emotional signal:

```text
TES = CES_pos + CES_neg
```

The TES Spectrogram tab draws a heatmap over the same visible time depth as the
Activity Summary. The shared `summary_depth` controls the visible time window.

The spectrogram control `D` is the Fourier window depth. Each visible
spectrogram column represents a Fourier transform over `D` consecutive TES
periods ending at that column's time position. If a visible time position does
not yet have `D` available periods, leave that column blank.

When the spectrogram is shown on the Brain Map, align its left and right plot
margins with Activity Summary (`42 px` left, `6 px` right). If both overlays are
enabled, reserve vertical space for both and draw the spectrogram immediately
above the Activity Summary.

Keep the spectrogram dependency-free. Use the standard library DFT
implementation unless an explicit project dependency is introduced elsewhere.
