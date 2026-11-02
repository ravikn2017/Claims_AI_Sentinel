#!/bin/bash
# Block shell commands that drop the database or rewrite git history.
input=$(cat)
if ! command -v jq >/dev/null 2>&1; then
  printf '%s\n' '{ "permission": "allow" }'
  exit 0
fi

command=$(printf '%s' "$input" | jq -r '.command // empty')

deny() {
  jq -n --arg message "$1" '{permission:"deny", user_message:$message, agent_message:$message}'
  exit 0
}

ask() {
  jq -n --arg message "$1" '{permission:"ask", user_message:$message, agent_message:$message}'
  exit 0
}

if printf '%s' "$command" | grep -Eiq 'drop[[:space:]]+(schema|database)'; then
  deny "Dropping a schema or database is blocked. Add a numbered file under db/sql/ instead."
fi

if printf '%s' "$command" | grep -Eiq 'git[[:space:]]+push' \
  && printf '%s' "$command" | grep -Eiq -- '--force|--force-with-lease|(^|[[:space:]])-f([[:space:]]|$)'; then
  deny "Force push is blocked."
fi

if printf '%s' "$command" | grep -Eiq 'git[[:space:]]+reset[[:space:]]+--hard'; then
  deny "git reset --hard is blocked."
fi

if printf '%s' "$command" | grep -Eiq 'git[[:space:]]+clean[[:space:]]+[^;&|]*-[[:alnum:]]*f'; then
  deny "git clean -f is blocked."
fi

if printf '%s' "$command" | grep -Eiq '(git[[:space:]]+add|cat|cp|pbcopy|tee)[[:space:]].*\.env'; then
  ask "This command reads or stages .env. Confirm it does not expose or commit secrets."
fi

printf '%s\n' '{ "permission": "allow" }'
exit 0
