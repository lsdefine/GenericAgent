import OpenAI from '@lobehub/icons/es/OpenAI/components/Mono';
import Anthropic from '@lobehub/icons/es/Anthropic/components/Mono';
import DeepSeek from '@lobehub/icons/es/DeepSeek/components/Mono';
import Qwen from '@lobehub/icons/es/Qwen/components/Mono';
import Google from '@lobehub/icons/es/Google/components/Mono';
import Meta from '@lobehub/icons/es/Meta/components/Mono';
import Mistral from '@lobehub/icons/es/Mistral/components/Mono';
import Moonshot from '@lobehub/icons/es/Moonshot/components/Mono';
import Volcengine from '@lobehub/icons/es/Volcengine/components/Mono';
import Minimax from '@lobehub/icons/es/Minimax/components/Mono';
import Zhipu from '@lobehub/icons/es/Zhipu/components/Mono';
import Stepfun from '@lobehub/icons/es/Stepfun/components/Mono';
import Kimi from '@lobehub/icons/es/Kimi/components/Mono';
import OpenRouter from '@lobehub/icons/es/OpenRouter/components/Mono';
import Groq from '@lobehub/icons/es/Groq/components/Mono';
import Cohere from '@lobehub/icons/es/Cohere/components/Mono';
import XAI from '@lobehub/icons/es/XAI/components/Mono';
import Baichuan from '@lobehub/icons/es/Baichuan/components/Mono';
import ByteDance from '@lobehub/icons/es/ByteDance/components/Mono';

export interface ProviderIconDef {
  key: string;
  displayName: string;
  color: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  Component: any;
}

export const PROVIDER_ICONS: Record<string, ProviderIconDef> = {
  openai: { key: 'openai', displayName: 'OpenAI', color: '#10A37F', Component: OpenAI },
  anthropic: { key: 'anthropic', displayName: 'Claude', color: '#D97706', Component: Anthropic },
  deepseek: { key: 'deepseek', displayName: 'DeepSeek', color: '#4D6BFE', Component: DeepSeek },
  qwen: { key: 'qwen', displayName: 'Qwen', color: '#615CED', Component: Qwen },
  google: { key: 'google', displayName: 'Google', color: '#4285F4', Component: Google },
  meta: { key: 'meta', displayName: 'Meta', color: '#0081FB', Component: Meta },
  mistral: { key: 'mistral', displayName: 'Mistral', color: '#FF7000', Component: Mistral },
  moonshot: { key: 'moonshot', displayName: 'Moonshot', color: '#7C3AED', Component: Moonshot },
  doubao: { key: 'doubao', displayName: '火山引擎', color: '#006EFF', Component: Volcengine },
  minimax: { key: 'minimax', displayName: 'MiniMax', color: '#F23F5D', Component: Minimax },
  zhipu: { key: 'zhipu', displayName: 'Zhipu', color: '#3859FF', Component: Zhipu },
  stepfun: { key: 'stepfun', displayName: 'StepFun', color: '#005AFF', Component: Stepfun },
  kimi: { key: 'kimi', displayName: 'Kimi', color: '#000000', Component: Kimi },
  openrouter: { key: 'openrouter', displayName: 'OpenRouter', color: '#6366F1', Component: OpenRouter },
  groq: { key: 'groq', displayName: 'Groq', color: '#F55036', Component: Groq },
  cohere: { key: 'cohere', displayName: 'Cohere', color: '#39594D', Component: Cohere },
  xai: { key: 'xai', displayName: 'xAI', color: '#000000', Component: XAI },
  baichuan: { key: 'baichuan', displayName: 'Baichuan', color: '#4A90E2', Component: Baichuan },
  bytedance: { key: 'bytedance', displayName: 'ByteDance', color: '#006EFF', Component: ByteDance },
};

export function getProviderIcon(key: string): ProviderIconDef | undefined {
  return PROVIDER_ICONS[key];
}

export function providerFromModel(model: string): string | null {
  const raw = (model || '').toLowerCase();
  const slash = raw.lastIndexOf('/');
  const m = slash >= 0 ? raw.slice(slash + 1) : raw;
  if (m.startsWith('claude') || raw.includes('anthropic')) return 'anthropic';
  if (m.startsWith('gpt') || m.startsWith('o1') || m.startsWith('o3') || m.startsWith('o4')) return 'openai';
  if (raw.includes('deepseek')) return 'deepseek';
  if (m.startsWith('qwen')) return 'qwen';
  if (m.startsWith('moonshot')) return 'moonshot';
  if (m.startsWith('glm')) return 'zhipu';
  if (m.startsWith('step-')) return 'stepfun';
  if (m.startsWith('doubao')) return 'doubao';
  if (m.startsWith('minimax') || m.startsWith('abab')) return 'minimax';
  if (raw.includes('gemini')) return 'google';
  if (m.startsWith('llama') || raw.includes('meta-llama')) return 'meta';
  if (m.startsWith('mistral') || m.startsWith('mixtral') || m.startsWith('codestral')) return 'mistral';
  if (m.startsWith('command')) return 'cohere';
  if (m.startsWith('grok')) return 'xai';
  if (m.startsWith('baichuan')) return 'baichuan';
  if (m.startsWith('kimi')) return 'kimi';
  return null;
}
