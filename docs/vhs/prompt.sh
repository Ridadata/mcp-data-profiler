# A minimal shell prompt for the recordings.
#
# Sourced from a file rather than typed into the tape: VHS mangles non-ASCII
# and escape-heavy input on its way through ttyd, and a file bypasses that.
PS1='\[\e[38;5;111m\]>\[\e[0m\] '
PS2='  '
unset PROMPT_COMMAND
