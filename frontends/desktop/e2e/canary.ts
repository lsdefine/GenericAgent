const base = process.env.GA_E2E_CANARY_BASE;
const key = process.env.GA_E2E_CANARY_KEY;
const model = process.env.GA_E2E_CANARY_MODEL;

if (!base || !key || !model) {
  throw new Error('Canary is manual/nightly only; set GA_E2E_CANARY_BASE, GA_E2E_CANARY_KEY, and GA_E2E_CANARY_MODEL');
}
const url = new URL('/v1/chat/completions', base);
const response = await fetch(url, {
  method: 'POST',
  headers: { authorization: `Bearer ${key}`, 'content-type': 'application/json' },
  body: JSON.stringify({
    model,
    stream: false,
    max_tokens: 16,
    messages: [{ role: 'user', content: 'Reply with OK.' }],
  }),
});
if (!response.ok) throw new Error(`Canary protocol failed: HTTP ${response.status}`);
const body = await response.json() as {
  choices?: Array<{ message?: { content?: string } }>;
  usage?: { prompt_tokens?: number; completion_tokens?: number };
};
if (!body.choices?.[0]?.message?.content) throw new Error('Canary returned no assistant content');
if ((body.usage?.prompt_tokens || 0) + (body.usage?.completion_tokens || 0) <= 0) {
  throw new Error('Canary returned no token usage');
}
process.stdout.write('Canary protocol, assistant content, and usage checks passed.\n');
