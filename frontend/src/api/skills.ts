import axios from 'axios';
import { Skill, SkillVersion, SkillExecutionResult } from '../types/skill';

export const listSkills = async (includeSystem = true): Promise<Skill[]> => {
  const response = await axios.get('/api/skills', { params: { include_system: includeSystem } });
  return response.data;
};

export const getSkill = async (skillId: string): Promise<{ skill: Skill; version: SkillVersion }> => {
  const response = await axios.get(`/api/skills/${skillId}`);
  return response.data;
};

export const createSkill = async (payload: any): Promise<{ skill: Skill; version: SkillVersion }> => {
  const response = await axios.post('/api/skills', payload);
  return response.data;
};

export const executeSkill = async (skillId: string, kwargs: Record<string, any>): Promise<SkillExecutionResult> => {
  const response = await axios.post(`/api/skills/${skillId}/execute`, { kwargs });
  return response.data;
};
