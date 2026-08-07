# docs/mcp-demo.gif — the same profiler seen from inside an MCP client.
#
#   docker build -t mcp-data-profiler-vhs docs/vhs
#   docker run --rm -v "$PWD:/vhs" mcp-data-profiler-vhs docs/mcp-demo.tape
#
# The conversation is staged and paced by docs/vhs/mcp_session.py, but every
# figure it prints comes from a real profile_dataset() call — see the module
# docstring. The script is started off camera so the frame holds nothing but
# the conversation.

Output docs/mcp-demo.gif

Set Shell "bash"
Set FontFamily "JetBrains Mono"
Set FontSize 20
Set Width 1220
Set Height 780
Set Padding 24
Set Margin 40
Set MarginFill "#15161e"
Set BorderRadius 10
Set WindowBar Colorful
Set WindowBarSize 40
Set Theme "Catppuccin Mocha"
Set TypingSpeed 55ms
Set Framerate 24

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
Type "python docs/vhs/mcp_session.py" Enter
# Cover the interpreter starting up; the script clears its own command line and
# holds for a beat, so the visible recording opens on an empty frame.
Sleep 1500ms
Show

# mcp_session.py paces itself; this is just the recording window.
Sleep 15s
