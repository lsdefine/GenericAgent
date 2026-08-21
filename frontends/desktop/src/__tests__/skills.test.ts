// @vitest-environment node
import { describe, it, expect } from 'vitest';
import { BUILTIN_SKILLS, matchSkillPrefix } from '../components/chat/Composer/skills';

describe('BUILTIN_SKILLS', () => {
  it('has unique ids', () => {
    const ids = BUILTIN_SKILLS.map((s) => s.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it('all skills have non-empty prompts', () => {
    for (const skill of BUILTIN_SKILLS) {
      expect(skill.prompt.length).toBeGreaterThan(10);
    }
  });

  it('all skills have bilingual descriptions', () => {
    for (const skill of BUILTIN_SKILLS) {
      expect(skill.desc.zh).toBeTruthy();
      expect(skill.desc.en).toBeTruthy();
    }
  });
});

describe('matchSkillPrefix', () => {
  it('matches plan skill prompt', () => {
    const planSkill = BUILTIN_SKILLS.find((s) => s.id === 'plan')!;
    const result = matchSkillPrefix(planSkill.prompt + ' build a chat app');
    expect(result).not.toBeNull();
    expect(result!.id).toBe('plan');
    expect(result!.rest).toBe('build a chat app');
  });

  it('matches goal skill prompt with no rest', () => {
    const goalSkill = BUILTIN_SKILLS.find((s) => s.id === 'goal')!;
    const result = matchSkillPrefix(goalSkill.prompt);
    expect(result).not.toBeNull();
    expect(result!.id).toBe('goal');
    expect(result!.rest).toBe('');
  });

  it('returns null for non-matching content', () => {
    expect(matchSkillPrefix('Hello world')).toBeNull();
    expect(matchSkillPrefix('')).toBeNull();
  });

  it('returns null for partial prefix match', () => {
    const planSkill = BUILTIN_SKILLS.find((s) => s.id === 'plan')!;
    expect(matchSkillPrefix(planSkill.prompt.slice(0, 10))).toBeNull();
  });

  it('matches all built-in skills by their own prompt', () => {
    for (const skill of BUILTIN_SKILLS) {
      const result = matchSkillPrefix(skill.prompt + ' extra text');
      expect(result, `failed for skill "${skill.id}"`).not.toBeNull();
      expect(result!.id).toBe(skill.id);
    }
  });
});
