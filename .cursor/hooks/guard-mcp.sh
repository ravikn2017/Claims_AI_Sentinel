#!/bin/bash
# Postgres MCP stays read-only. Langfuse writes wait for confirmation.
input=$(cat)
if ! command -v jq >/dev/null 2>&1; then
  printf '%s\n' '{ "permission": "allow" }'
  exit 0
fi

server=$(printf '%s' "$input" | jq -r '.mcp_server_name // empty')
tool=$(printf '%s' "$input" | jq -r '.tool_name // empty')
tool_input=$(printf '%s' "$input" | jq -r '.tool_input // empty')
sql=$(printf '%s' "$tool_input" | jq -r 'fromjson? | .sql // .query // .statement // empty' 2>/dev/null || true)
if [ -z "$sql" ]; then
  sql=$tool_input
fi

deny() {
  jq -n --arg message "$1" '{permission:"deny", user_message:$message, agent_message:$message}'
  exit 0
}

ask() {
  jq -n --arg message "$1" '{permission:"ask", user_message:$message, agent_message:$message}'
  exit 0
}

if [ "$server" = "postgres" ] && printf '%s' "$sql" | grep -Eiq '\b(insert|update|delete|drop|truncate|alter|create|grant|revoke)\b'; then
  deny "Postgres MCP is read-only. Claim changes go through the payer service."
fi

if [ "$server" = "langfuse" ] && printf '%s' "$tool" | grep -Eiq 'create|update|delete|upsert|archive'; then
  ask "Langfuse tool ${tool} can change project data. Confirm before it runs."
fi

printf '%s\n' '{ "permission": "allow" }'
exit 0
