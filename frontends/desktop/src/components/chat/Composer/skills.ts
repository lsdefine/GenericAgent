export interface SkillDef {
  id: string;
  title: string;
  desc: { zh: string; en: string };
  prompt: string;
}

export const BUILTIN_SKILLS: SkillDef[] = [
  {
    id: 'plan',
    title: 'Plan',
    desc: { en: 'Explore, plan, execute, verify', zh: '探索、规划、执行、验证' },
    prompt: 'Enter Plan mode: read memory/plan_sop.md, follow Explore → Plan → Execute → Verify flow for the task I describe next.',
  },
  {
    id: 'goal',
    title: 'Goal',
    desc: { en: 'Achieve a specific objective autonomously', zh: '自主达成指定目标' },
    prompt: 'Enter Goal mode: read L3 goal mode SOP, autonomously achieve the goal I describe next.',
  },
  {
    id: 'autonomous',
    title: 'Autonomous',
    desc: { en: 'Select tasks and execute independently', zh: '自主选取任务并独立执行' },
    prompt: 'Enter autonomous mode: read memory/autonomous_operation_sop.md, select or plan tasks, execute independently and produce a report.',
  },
  {
    id: 'hive',
    title: 'Hive',
    desc: { en: 'Multi-agent parallel collaboration', zh: '多 agent 并行协作' },
    prompt: 'Start Goal Hive mode: follow hive SOP, spawn multiple workers to collaboratively achieve my next goal.',
  },
  {
    id: 'review',
    title: 'Review',
    desc: { en: 'Critical review of latest output', zh: '对最近产出做严格复核' },
    prompt: 'Enter reviewer mode: rigorously critique the latest output, check each item and report issues.',
  },
  {
    id: 'findwork',
    title: 'Find Work',
    desc: { en: 'Analyze context, suggest next tasks', zh: '分析当前情况，推荐下一步' },
    prompt: 'Analyze my situation using the autonomous planning approach, generate a batch of TODOs that would interest me.',
  },
];

export function matchSkillPrefix(content: string): { id: string; rest: string } | null {
  for (const skill of BUILTIN_SKILLS) {
    if (content.startsWith(skill.prompt)) {
      const rest = content.slice(skill.prompt.length).trimStart();
      return { id: skill.id, rest };
    }
  }
  return null;
}
