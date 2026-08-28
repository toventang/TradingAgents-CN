import { ApiClient } from './request';
import type { Skill, SkillVersion, SkillExecutionResult } from '../types/skill';

export const listSkills = async (includeSystem = true): Promise<Skill[]> => {
  const res = await ApiClient.get<Skill[]>('/api/skills', { include_system: includeSystem });
  return res as unknown as Skill[];
};

export const getSkill = async (skillId: string): Promise<{ skill: Skill; version: SkillVersion }> => {
  const res = await ApiClient.get<{ skill: Skill; version: SkillVersion }>(`/api/skills/${skillId}`);
  return res as unknown as { skill: Skill; version: SkillVersion };
};

export const createSkill = async (payload: any): Promise<{ skill: Skill; version: SkillVersion }> => {
  const res = await ApiClient.post<{ skill: Skill; version: SkillVersion }>('/api/skills', payload);
  return res as unknown as { skill: Skill; version: SkillVersion };
};

export const executeSkill = async (skillId: string, kwargs: Record<string, any>): Promise<SkillExecutionResult> => {
  const res = await ApiClient.post<SkillExecutionResult>(`/api/skills/${skillId}/execute`, { kwargs });
  return res as unknown as SkillExecutionResult;
};
