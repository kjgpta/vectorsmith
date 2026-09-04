# Terminal half of the launch demo. Re-record:
#   vhs docs/assets/demo-terminal.tape
# Requires local Qdrant on :6333 with the invoices collection seeded.

Output docs/assets/demo-terminal.gif
Output docs/assets/demo-terminal.mp4

Set Shell zsh
Set FontFamily "Menlo"
Set FontSize 15
Set Width 980
Set Height 720
Set Padding 16
Set Theme "Catppuccin Mocha"
Set TypingSpeed 36ms
Set PlaybackSpeed 0.95
Set Framerate 20
Set WindowBar Colorful
Set WaitTimeout 45s
Set CursorBlink false

Hide
Type `# demo setup`
Enter
Type `export PATH="/Users/kshitijgupta/Claude/vectorsmith-demo/.venv/bin:$PATH"`
Enter
Type `cd /tmp/vectorsmith-demo`
Enter
Type `export PS1=$'%F{cyan}demo%f %F{white}❯%f '`
Enter
Type `clear`
Enter
Show

Type `grep -E '^- name:|path: tenant' tools.yaml`
Enter
Sleep 2.5s

Type `vectorsmith validate tools.yaml --env-file .env`
Enter
Sleep 1.2s

Type `vectorsmith test tools.yaml list_overdue_invoices \`
Enter
Type `  --args '{"client":"Globex"}' --env-file .env`
Enter
Sleep 2.5s

Type `vectorsmith test tools.yaml search_paid_invoices \`
Enter
Type `  --args '{"client":"Globex"}' --env-file .env`
Enter
Sleep 3.5s

Sleep 4s
