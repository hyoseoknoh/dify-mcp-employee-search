#!/bin/bash

SESSION="mcp"
PROJECT_DIR="$HOME/Downloads/test_MCP"

if tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "이미 '$SESSION' 세션이 실행 중입니다."
    echo "다시 접속합니다."
    tmux attach-session -t "$SESSION"
    exit 0
fi

tmux new-session -d -s "$SESSION" -n "MCP_server"

tmux send-keys -t "$SESSION:MCP_server" \
"cd \"$PROJECT_DIR\" && source .venv/bin/activate && python server.py" C-m

tmux new-window -t "$SESSION" -n "mail_server"
tmux send-keys -t "$SESSION:mail_server" \
"cd \"$PROJECT_DIR\" && source .venv/bin/activate && python mail_server.py" C-m

tmux new-window -t "$SESSION" -n "ngrok8000"
tmux send-keys -t "$SESSION:ngrok8000" \
"ngrok http 8000" C-m

tmux new-window -t "$SESSION" -n "cloudflare8001"
tmux send-keys -t "$SESSION:cloudflare8001" \
"cloudflared tunnel --url http://localhost:8001" C-m

tmux new-window -t "$SESSION" -n "inspector"
tmux send-keys -t "$SESSION:inspector" \
"npx @modelcontextprotocol/inspector" C-m

tmux select-window -t "$SESSION:MCP_server"
tmux attach-session -t "$SESSION"