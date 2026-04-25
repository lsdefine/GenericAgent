import openai
client = openai.OpenAI(api_key='anything', base_url='http://localhost:8000/v1')
try:
    response = client.chat.completions.create(
        model='claude-sonnet-4.5',
        messages=[{'role': 'user', 'content': 'Hello, are you Claude?'}]
    )
    print('Response:', response.choices[0].message.content)
except Exception as e:
    print('Error:', e)

