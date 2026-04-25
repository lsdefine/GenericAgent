import os

# 设置代理环境变量
os.environ['HTTP_PROXY'] = 'http://127.0.0.1:6789'
os.environ['HTTPS_PROXY'] = 'http://127.0.0.1:6789'

from litellm import completion

# 添加 GitHub Copilot 所需的头部
extra_headers = {
    "Editor-Version": "vscode/1.85.1",
    "Editor-Plugin-Version": "copilot/1.155.0",
    "Copilot-Integration-Id": "vscode-chat",
    "User-Agent": "GitHubCopilotChat/0.35.0"
}

response = completion(
    model="github_copilot/gpt-4",
    messages=[{"role": "user", "content": "Hello, who are you?"}],
    stream=False,
    extra_headers=extra_headers
)

print("Response:", response)
print("\nContent:", response.choices[0].message.content)