
oai_config = {
    'apikey':'sk-uklURcj',
    'apibase':"http://243.55.19.137:2001",
    'model':"openai/gpt-5.1",
    'api_mode':"chat_completions",  # optional: "chat_completions" | "responses"
    'max_retries': 2,               # optional: retries for 429/timeout/5xx
    'connect_timeout': 10,          # optional: seconds
    'read_timeout': 120             # optional: seconds (stream read)
}

# or

sider_cookie = 'token=Bearer%20eyJhbGciOiJIUz...'

# feel free to add more ~
oai_config2 = {
    'apikey':'sk-uklURcj...',
    'apibase':"http://243.55.19.137:2001",
    'model':"claude-opus-4-6-20260206"
}


claude_config = {
    'apikey':'klURcj...',
    'apibase':"http://233.85.13.149:2001",
    'model':"claude-opus"
}

# If you need them
# tg_bot_token = '84102K2gYZ...'
# tg_allowed_users = [6806...]

# proxy = "http://127.0.0.1:2082"
