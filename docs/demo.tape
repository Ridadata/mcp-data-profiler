# docs/demo.gif — the hero recording: one command, a whole dataset characterised.
#
#   docker build -t mcp-data-profiler-vhs docs/vhs
#   docker run --rm -v "$PWD:/vhs" mcp-data-profiler-vhs docs/demo.tape
#
# See docs/vhs/README.md. Non-ASCII characters are never typed here — VHS
# mangles them on the way through ttyd — so every glyph on screen is written by
# the program itself.

Output docs/demo.gif

Set Shell "bash"
Set FontFamily "JetBrains Mono"
Set FontSize 20
Set Width 1220
# Tall enough for the command plus all 20 lines of output without scrolling:
# the last frame is the one the README shows, so nothing may fall off the top.
Set Height 800
Set Padding 24
Set Margin 40
Set MarginFill "#15161e"
Set BorderRadius 10
Set WindowBar Colorful
Set WindowBarSize 40
Set Theme "Catppuccin Mocha"
Set TypingSpeed 55ms
Set Framerate 24

# Set the prompt and warm the import cache, off camera: the first pandas import
# of a container's life is slow, and dead air is not part of the demo.
# Each Sleep waits for the shell to actually finish: VHS types the next line
# whether or not the last one has returned, and anything still queued when
# Show fires ends up on camera.
Hide
Type "source docs/vhs/prompt.sh" Enter
Sleep 500ms
Type "python -c 'import pandas'" Enter
Sleep 3s
Type "clear" Enter
Sleep 500ms
Show

Sleep 900ms
Type "python demo.py"
Sleep 700ms
Enter

# The run itself takes well under a second; the rest is reading time.
Sleep 2s
Sleep 9s
